"""Durable generation retries never masquerade as completed or idle work."""
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from generation import GenerationError
from store import Conflict, Store, dumps, now


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITORIAL_DATA', str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER', 'false')
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    spec = importlib.util.spec_from_file_location('editorial_retry_app', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_once(worker, monkeypatch):
    class OneIteration:
        calls = 0

        def wait(self, seconds):
            self.calls += 1
            return self.calls > 1

    monkeypatch.setattr(worker, 'stop', OneIteration())
    worker.work()


@pytest.mark.parametrize('kind', ['plan', 'draft', 'render', 'demand', 'companion'])
def test_transient_error_stays_active_until_retry_is_exhausted(worker, monkeypatch, kind):
    store = worker.store
    target = store.prepare('2030-10-28')
    if kind != 'plan':
        week = target
        target = 'retry-item'
        with store.db() as db:
            db.execute('DELETE FROM jobs')
            db.execute('INSERT INTO items(id,week_id,kind,slot,content,scheduled_at) VALUES(?,?,?,?,?,?)',
                       (target, week, 'social', 0, dumps({'title': 'Texte déjà conservé'}), '2030-10-28T12:00:00+00:00'))
            store.job(db, kind, target)

    owner, method = {
        'plan': (worker.generator, 'plan'),
        'draft': (worker.generator, 'draft'),
        'render': (worker.generator, 'render'),
        'demand': (worker.conversation, 'draft'),
        'companion': (worker.companion, 'run'),
    }[kind]

    def unavailable(identifier):
        assert identifier == target
        raise GenerationError('Le service IA est indisponible.')

    monkeypatch.setattr(owner, method, unavailable)
    table = 'weeks' if kind == 'plan' else 'items'
    run_once(worker, monkeypatch)
    with store.db() as db:
        job = db.execute('SELECT status,attempts FROM jobs WHERE target=?', (target,)).fetchone()
        state = db.execute(f'SELECT status,error FROM {table} WHERE id=?', (target,)).fetchone()
    assert tuple(job) == ('queued', 1)
    assert tuple(state) == ('preparing' if kind == 'plan' else 'queued', None)
    if kind != 'plan':
        with pytest.raises(Conflict, match='modifié actuellement'):
            store.save_item(target, 1, {}, '2030-10-28T12:00:00+00:00', 'owner')
        assert store.item(target)['content']['title'] == 'Texte déjà conservé'

    run_once(worker, monkeypatch)
    with store.db() as db:
        job = db.execute('SELECT status,attempts FROM jobs WHERE target=?', (target,)).fetchone()
        state = db.execute(f'SELECT status,error FROM {table} WHERE id=?', (target,)).fetchone()
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
    assert tuple(job) == ('failed', 2)
    assert tuple(state) == ('failed', 'Le service IA est indisponible.')


@pytest.mark.parametrize('attempts,job_status,week_status', [(1, 'queued', 'preparing'), (2, 'failed', 'failed')])
def test_recovery_keeps_week_consistent_with_interrupted_plan(tmp_path, attempts, job_status, week_status):
    store = Store(tmp_path)
    week = store.prepare('2030-10-28')
    with store.db() as db:
        db.execute("UPDATE jobs SET status='running',attempts=? WHERE target=?", (attempts, week))
    store.recover()
    with store.db() as db:
        job = db.execute('SELECT status FROM jobs WHERE target=?', (week,)).fetchone()[0]
        state = db.execute('SELECT status,error FROM weeks WHERE id=?', (week,)).fetchone()
    assert job == job_status
    assert state['status'] == week_status
    assert bool(state['error']) == (week_status == 'failed')
    assert store.prepare('2030-10-28') == week  # Recovery never creates a duplicate week.


def test_recovery_does_not_discard_a_plan_already_saved_before_worker_exit(tmp_path):
    store = Store(tmp_path)
    week = store.prepare('2030-10-28')
    with store.db() as db:
        db.execute("UPDATE weeks SET status='plan_review',plan=? WHERE id=?", (dumps({'subjects': ['ready']}), week))
        db.execute("UPDATE jobs SET status='running',attempts=2 WHERE target=?", (week,))
    store.recover()
    with store.db() as db:
        state = db.execute('SELECT status,plan,error FROM weeks WHERE id=?', (week,)).fetchone()
    assert tuple(state) == ('plan_review', dumps({'subjects': ['ready']}), None)


def test_recovery_repairs_an_already_failed_plan_job_after_previous_restart(tmp_path):
    store = Store(tmp_path)
    week = store.prepare('2030-10-28')
    with store.db() as db:
        db.execute("UPDATE jobs SET status='failed',attempts=2,updated=? WHERE target=?", (now(), week))
    store.recover()
    with store.db() as db:
        state = db.execute('SELECT status,error FROM weeks WHERE id=?', (week,)).fetchone()
    assert state['status'] == 'failed'
    assert 'relancer' in state['error']

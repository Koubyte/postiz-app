"""Independent regression review of strategy scheduling, replay and draft safety."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agent import AgentService
from store import Conflict, PARIS, Store, dumps, now, uid
from strategy import Strategy


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    store = Store(tmp_path)
    agent = AgentService(store, lambda: [])
    generator = SimpleNamespace(ask=lambda _: {
        'title': 'Pratiquer à domicile', 'summary': 'Trois conseils complémentaires.', 'blog_angle': 'Guide complet',
        'steps': [{'title': f'Conseil {i+1}', 'brief': f'Conseil utile numéro {i+1}, dans une pièce de musique différente.', 'product_query': ''} for i in range(3)],
    })
    strategy = Strategy(store, generator, None, agent)
    return store, agent, strategy


def tomorrow():
    return (datetime.now(PARIS) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)


def planned(strategy):
    day = tomorrow().date().isoformat()
    campaign = strategy.create_campaign(uid(), 'Des conseils pour pratiquer à domicile', day, day, create_blog=True)
    strategy.plan_campaign(campaign['id'])
    return campaign['id']


def add_idea(store):
    idea = {'id': 'watch-test-idea', 'title': 'Choisir un casque de pratique', 'angle': 'Comprendre les types de casques.',
            'kind': 'advice', 'product_query': '', 'sources': [{'title': 'Fabricant', 'url': 'https://maker.example/guide'}]}
    with store.db() as db:
        db.execute('INSERT INTO watch_ideas(id,run_id,body,created) VALUES(?,?,?,?)', (idea['id'], 'run-example', dumps(idea), now()))
    return idea['id']


def test_bad_watch_date_can_be_corrected_without_permanently_locking_idea(system):
    store, agent, strategy = system
    idea = add_idea(store)
    with pytest.raises(Conflict):
        strategy.prepare_idea(idea, uid(), scheduled_at='not-a-date')
    receipt = strategy.prepare_idea(idea, uid(), scheduled_at=tomorrow().isoformat())
    assert store.item(receipt['item_id'])['status'] == 'queued'
    assert store.item(receipt['item_id'])['approval_hash'] is None


def test_calendar_change_cannot_push_campaign_outside_owner_period(system):
    store, agent, strategy = system
    identifier = planned(strategy)
    day = tomorrow()
    agent.calendar = lambda: [day.replace(hour=hour) for hour in range(9, 21)]
    try:
        strategy.draft_campaign(identifier)
    except Conflict:
        pass  # A readable conflict is preferable to silently leaving the chosen period.
    with store.db() as db:
        dates = [datetime.fromisoformat(r[0]).astimezone(PARIS).date() for r in db.execute('SELECT scheduled_at FROM items')]
    assert all(d == day.date() for d in dates), 'Campaign escaped its selected end date after native-calendar changes'


def test_recover_creation_before_campaign_receipt_does_not_duplicate_content(system, monkeypatch):
    store, agent, strategy = system
    identifier = planned(strategy)
    original = agent.prepare
    def crash_after_success(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('crash after committing the first item')
    monkeypatch.setattr(agent, 'prepare', crash_after_success)
    with pytest.raises(RuntimeError):
        strategy.draft_campaign(identifier)
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM campaign_items').fetchone()[0] == 0
    monkeypatch.setattr(agent, 'prepare', original)
    strategy.draft_campaign(identifier)
    strategy.draft_campaign(identifier)
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 3
        assert db.execute('SELECT count(*) FROM campaign_items').fetchone()[0] == 3
        assert db.execute('SELECT count(*) FROM items WHERE approval_hash IS NOT NULL').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
        assert db.execute('SELECT sum(blog_requested) FROM items').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM weeks').fetchone()[0] == 0
    assert store.public_articles() == []


def test_repeated_schedule_tick_is_durable_research_only_and_pause_blocks_new_slot(system):
    store, agent, strategy = system
    monday = datetime(2026, 11, 2, 8, 31, tzinfo=PARIS)
    for _ in range(3):
        strategy.tick(monday)
    with store.db() as db:
        assert [r[0] for r in db.execute('SELECT kind FROM jobs ORDER BY kind')] == ['performance', 'watch']
        assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM published').fetchone()[0] == 0
        db.execute("UPDATE settings SET value='true' WHERE key='paused'")
    with pytest.raises(Conflict, match='suspendu'):
        strategy.tick(monday+timedelta(days=3))
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2


def test_campaign_drafts_have_spacing_and_never_change_weekly_plan(system):
    store, agent, strategy = system
    week = store.prepare()
    with store.db() as db:
        before = dict(db.execute('SELECT * FROM weeks WHERE id=?', (week,)).fetchone())
    identifier = planned(strategy)
    strategy.prepare_campaign(identifier, 1, uid())
    strategy.draft_campaign(identifier)
    campaign = strategy.campaign(identifier)
    dates = [datetime.fromisoformat(i['scheduled_at']) for i in campaign['items']]
    assert all(b-a >= timedelta(hours=2) for a, b in zip(dates, dates[1:]))
    assert all(i['status'] == 'queued' for i in campaign['items'])
    with store.db() as db:
        assert dict(db.execute('SELECT * FROM weeks WHERE id=?', (week,)).fetchone()) == before
        assert db.execute('SELECT count(*) FROM items WHERE approved_at IS NOT NULL').fetchone()[0] == 0

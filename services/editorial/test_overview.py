"""Content discovery crosses weeks and conversations without changing production."""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from overview import content_detail, list_contents
from store import Store, dumps


NOW = datetime(2030, 1, 15, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path)
    with result.db() as db:
        db.execute('INSERT INTO weeks(id,week,status,plan,created) VALUES(?,?,?,?,?)',
                   ('week-1', '2030-01-14', 'review', dumps({'subjects': [{'slot': 7, 'title': 'Sujet encore en préparation'}]}), NOW.isoformat()))
    return result


def add(store, identifier, *, status='review', source='weekly', kind='social', due=None, title='Un conseil', captions=None, slot=None):
    due = due or NOW + timedelta(days=1)
    content = {'title': title, **(captions or {})} if title else (captions or {})
    with store.db() as db:
        index = db.execute('SELECT count(*) FROM items').fetchone()[0]
        cid = 'discussion-' + identifier
        week = 'week-1' if source == 'weekly' else 'demand:' + cid
        db.execute('INSERT INTO items(id,week_id,kind,slot,status,scheduled_at,content,media,approval_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier, week, kind, index if slot is None else slot, status, due.isoformat(), dumps(content),
                    dumps({'media': identifier + '.png', 'blog_media': identifier + '-cover.png'}), 'private-server-seal'))
        if source != 'weekly':
            db.execute('INSERT INTO conversations VALUES(?,?,?)', (cid, 'Demande particulière', NOW.isoformat()))
            db.execute('INSERT INTO demand_items VALUES(?,?,?,?,?,?)',
                       (identifier, cid, 'message-' + identifier, 0, dumps({'title': 'Brief à préparer'}), None))
        if source == 'companion':
            db.execute('INSERT INTO companion_articles VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('parent-' + identifier, identifier, 1, 'parent-seal', 'owner', NOW.isoformat(), 1, 'active', None, '{}'))
    return identifier


def test_index_finds_all_sources_and_searches_accents_without_exposing_documents(store):
    add(store, 'weekly', title='Écouter une guitare', captions={'instagram': 'Des mélodies précises'})
    add(store, 'demand', source='on_demand', title='Le piano', captions={'facebook': 'Découvrez le modèle orange'})
    add(store, 'companion', source='companion', kind='blog', title='Un guide', captions={'markdown': 'Un grand article sur les enceintes à évents'})
    result = list_contents(store, current=NOW)
    assert result['total'] == 3
    assert [item['source'] for item in result['items']] == ['companion', 'on_demand', 'weekly']
    assert result['items'][0]['conversation_id'] == 'discussion-companion'
    assert result['items'][2]['week'] == '2030-01-14'
    assert list_contents(store, q='e\u0301COUTER', current=NOW)['items'][0]['id'] == 'weekly'
    assert list_contents(store, q='MELODIES', current=NOW)['items'][0]['id'] == 'weekly'
    assert list_contents(store, q='modele ORANGE', current=NOW)['items'][0]['id'] == 'demand'
    assert list_contents(store, q='events', current=NOW)['items'][0]['id'] == 'companion'
    assert list_contents(store, q="' OR 1=1 --", current=NOW)['total'] == 0
    assert all('content' not in item and 'approval_hash' not in item and 'search_text' not in item for item in result['items'])
    assert list_contents(store, q='impossible', current=NOW)['counts'] == result['counts']


def test_counts_and_attention_distinguish_unapproved_dates_from_calendar_authority(store):
    past = NOW - timedelta(days=1)
    add(store, 'ready')
    add(store, 'urgent', due=NOW + timedelta(minutes=4))
    add(store, 'failed', source='on_demand', status='failed', due=past)
    add(store, 'scheduled', status='scheduled', due=past)
    add(store, 'managed', status='managed', due=past)
    add(store, 'published', kind='blog', status='published', due=past)
    add(store, 'working', status='queued')
    add(store, 'article', source='companion', kind='blog', status='rendering', due=past)
    result = list_contents(store, q='no match', filter='attention', current=NOW)
    assert result['items'] == []
    assert result['counts'] == {'all': 8, 'review': 2, 'attention': 2, 'scheduled': 1, 'published': 1, 'progress': 2, 'blog': 2}
    attention = list_contents(store, filter='attention', current=NOW)
    assert {item['id'] for item in attention['items']} == {'urgent', 'failed'}
    scheduled = {item['id']: item for item in list_contents(store, filter='scheduled', current=NOW)['items']}
    # Native management also covers conversion to a draft or deletion, so it
    # cannot be counted as a confirmed scheduled publication.
    assert 'managed' not in scheduled
    managed = next(item for item in list_contents(store, current=NOW)['items'] if item['id'] == 'managed')
    assert managed['status'] == 'managed'
    assert managed['scheduled_at'] is None
    assert managed['schedule_authority'] == 'postiz'
    assert not managed['overdue'] and not managed['warning']
    assert scheduled['scheduled']['scheduled_at'] == past.isoformat()
    assert all(not item['overdue'] and not item['warning'] for item in scheduled.values())
    companion = list_contents(store, q='conseil', filter='progress', current=NOW)['items'][0]
    assert companion['source'] == 'companion' and not companion['overdue']


@pytest.mark.parametrize('status', ['approved', 'publishing', 'scheduled', 'managed', 'published'])
def test_approved_or_transferred_items_never_show_stale_approval_deadlines(store, status):
    add(store, 'item', status=status, due=NOW - timedelta(days=30))
    result = list_contents(store, current=NOW)
    assert not result['items'][0]['overdue']
    assert result['counts']['attention'] == 0


def test_pagination_is_deterministic_across_equal_dates_and_searches(store):
    for index in range(9):
        add(store, 'item-' + str(index), title=('Piano' if index % 2 else 'Guitare'))
    first = list_contents(store, limit=3, current=NOW)
    second = list_contents(store, offset=3, limit=3, current=NOW)
    third = list_contents(store, offset=6, limit=3, current=NOW)
    ids = [item['id'] for page in (first, second, third) for item in page['items']]
    assert ids == ['item-' + str(index) for index in reversed(range(9))]
    assert len(set(ids)) == 9
    assert first == list_contents(store, limit=3, current=NOW)
    assert list_contents(store, q='piano', limit=2, offset=2, current=NOW)['total'] == 4
    assert [item['id'] for item in list_contents(store, q='piano', limit=2, offset=2, current=NOW)['items']] == ['item-3', 'item-1']
    assert list_contents(store, offset=100, current=NOW)['items'] == []


def test_pending_titles_come_from_briefs_and_week_plan(store):
    add(store, 'week-queued', title='', status='queued', slot=7)
    add(store, 'demand-queued', title='', status='queued', source='on_demand')
    items = {item['id']: item for item in list_contents(store, current=NOW)['items']}
    assert items['week-queued']['title'] == 'Sujet encore en préparation'
    assert items['demand-queued']['title'] == 'Brief à préparer'
    assert list_contents(store, q='brief a preparer', current=NOW)['total'] == 1


def test_detail_supports_existing_editor_without_exporting_delivery_payloads(store):
    identifier = add(store, 'item', source='on_demand', captions={'facebook': 'Texte entier'})
    with store.db() as db:
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?,?)',
                   ('delivery', identifier, 1, 'facebook', 'submitted', dumps({'id': 'native', 'token': 'not-for-browser'}), NOW.isoformat()))
    before = store.item(identifier)
    detail = content_detail(store, identifier)
    assert detail['content']['facebook'] == 'Texte entier'
    assert detail['conversation_id'] == 'discussion-item'
    assert detail['media_url'] == '/editorial/media/item.png'
    assert detail['blog_media_url'] == '/editorial/media/item-cover.png'
    assert detail['source_media_url'] is None
    assert detail['deliveries'][0]['channel'] == 'facebook'
    assert detail['deliveries'][0]['status'] == 'submitted'
    assert 'approval_hash' not in detail
    assert 'not-for-browser' not in dumps(detail)
    assert store.item(identifier) == before


def test_http_requires_existing_owner_session_for_index_and_detail(store, monkeypatch):
    from fastapi.testclient import TestClient
    for key, value in {'EDITORIAL_DATA': str(store.root), 'EDITORIAL_WORKER': 'false',
                       'PUBLIC_URL': 'https://postiz.example.com', 'POSTIZ_INTERNAL_URL': 'http://postiz',
                       'POSTIZ_ORG_ID': 'planete-laser', 'EDITORIAL_OWNER_EMAIL': 'owner@example.com'}.items():
        monkeypatch.setenv(key, value)
    identifier = add(store, 'private', source='on_demand')
    spec = importlib.util.spec_from_file_location('overview_http_test', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = {'id': 'owner', 'orgId': 'planete-laser', 'email': 'owner@example.com'}
    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: identity))
    with TestClient(module.app, base_url='https://postiz.example.com') as client:
        urls = ['/editorial/api/contents', '/editorial/api/contents/' + identifier]
        for url in urls:
            assert client.get(url).status_code == 401
            assert client.get(url, headers={'Authorization': 'Bearer arbitrary-agent-token'}).status_code == 401
        client.cookies.set('auth', 'owner-session')
        identity['orgId'] = 'another-org'
        assert all(client.get(url).status_code == 403 for url in urls)
        identity['orgId'] = 'planete-laser'
        identity['email'] = 'teammate@example.com'
        assert all(client.get(url).status_code == 403 for url in urls)
        identity['email'] = 'owner@example.com'
        identity['impersonate'] = True
        assert all(client.get(url).status_code == 403 for url in urls)
        identity['impersonate'] = False
        assert client.get(urls[0]).json()['items'][0]['id'] == identifier
        assert client.get(urls[1]).json()['content']['title'] == 'Un conseil'
        assert client.get(urls[0] + '?offset=-1').status_code == 422
        assert client.get(urls[0] + '?limit=10000').status_code == 422
        assert client.get(urls[0], params={'q': 'x' * 1001}).status_code == 422
        assert client.get(urls[0] + '?filter=anything').status_code == 409
        assert client.get('/editorial/api/contents/missing').status_code == 409

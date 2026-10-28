"""Meta provider fixtures cover daily series versus window/lifetime snapshots."""
import copy
from datetime import datetime, timezone

import pytest

from performance import generate_report
from store import Store, dumps


NOW = datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc)


def metric(label, *values):
    return {'label': label, 'percentageChange': 5, 'data': [{'date': date, 'total': value} for date, value in values]}


def post(identifier, *, channel='fb', date='2026-10-22T10:00:00.000Z', **extra):
    return {'id': identifier, 'content': 'Un conseil utile ' + identifier, 'publishDate': date,
            'releaseId': 'release_' + identifier, 'releaseURL': 'https://www.facebook.com/posts/' + identifier,
            'state': 'PUBLISHED', 'integration': {'id': channel, 'providerIdentifier': 'facebook' if channel == 'fb' else 'instagram', 'name': 'Planète Laser'},
            'settings': dumps({'post_type': 'post', '__type': 'facebook'}), **extra}


class API:
    def __init__(self):
        self.channels = [{'id': 'fb', 'identifier': 'facebook', 'name': 'Planète Laser', 'disabled': False},
                         {'id': 'ig', 'identifier': 'instagram', 'name': 'planete_laser', 'disabled': False}]
        self.posts = []
        self.analytics = {}
        self.failures = set()
        self.calls = []

    def api(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        assert method == 'GET'
        if path in self.failures:
            raise RuntimeError('secret-access-token and upstream private URL')
        if path == '/integrations':
            return copy.deepcopy(self.channels)
        if path == '/posts':
            return {'posts': copy.deepcopy(self.posts)}
        return copy.deepcopy(self.analytics.get(path, []))


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def test_previous_complete_week_uses_paris_dst_and_exclusive_end(store):
    api = API()
    api.posts = [post('before', date='2026-10-18T21:59:59.000Z'),
                 post('first', date='2026-10-18T22:00:00.000Z'),
                 post('last', date='2026-10-25T22:59:59.999Z'),
                 post('after', date='2026-10-25T23:00:00.000Z'),
                 post('scheduled', state='QUEUE'), post('draft', state='DRAFT'),
                 post('no-timezone', date='2026-10-22T10:00:00')]
    result = generate_report(store, api, current=NOW)
    assert result['period']['start'] == '2026-10-19T00:00:00+02:00'
    assert result['period']['end'] == '2026-10-26T00:00:00+01:00'
    assert {row['id'] for row in result['posts']} == {'first', 'last'}
    call = next(call for call in api.calls if call[1] == '/posts')
    assert call[2]['params'] == {'startDate': '2026-10-18T22:00:00+00:00', 'endDate': '2026-10-25T22:59:59.999999+00:00'}
    assert result['channels'][0]['published_count'] == 2
    assert 'heure de Paris' in result['period']['label']


def test_meta_real_shape_distinguishes_daily_and_window_totals_without_summing(store):
    api = API()
    api.analytics['/analytics/fb'] = [
        metric('Page Impressions', ('2026-10-25', 100), ('2026-10-26', 125), ('2026-10-27', 70)),
        metric('Page followers', ('2026-10-26', 3), ('2026-10-27', 2)),
        metric('Posts Engagement', ('2026-10-26', 12), ('2026-10-27', 0)),
        metric('Media views', ('2026-10-27', 150)),
    ]
    api.analytics['/analytics/ig'] = [
        metric('Follower Count', ('2026-10-26', 2), ('2026-10-27', 1)),
        metric('Reach', ('2026-10-26', 101), ('2026-10-27', 95)),
        metric('Likes', ('2026-10-28', 25)),
        metric('Views', ('2026-10-28', 1200)),
        metric('Comments', ('2026-10-28', 0)),
    ]
    result = generate_report(store, api, current=NOW)
    fb = {value['key']: value for value in result['channels'][0]['metrics']}
    ig = {value['key']: value for value in result['channels'][1]['metrics']}
    assert fb['reach']['value'] == 70 and fb['reach']['scope'] == 'daily_last'
    assert fb['reach']['series'] == [{'date': '2026-10-25', 'value': 100}, {'date': '2026-10-26', 'value': 125}, {'date': '2026-10-27', 'value': 70}]
    assert fb['follows']['value'] == 2
    assert fb['engagement']['value'] == 0
    assert ig['followers']['value'] == 1 and ig['reach']['value'] == 95
    assert ig['likes']['value'] == 25 and ig['likes']['scope'] == 'requested_window'
    assert ig['views']['value'] == 1200
    assert ig['comments']['value'] == 0
    assert all(channel['status'] == 'available' for channel in result['channels'])
    assert 'percentageChange' not in dumps(result)
    assert '7 jours glissants' in result['channels'][0]['period']['label']
    assert all(call[2]['params']['date'] == '7' for call in api.calls if call[1].startswith('/analytics/'))


def test_native_only_posts_and_studio_context_keep_lifetime_metrics_and_zero(store):
    api = API()
    api.posts = [post('native'), post('editorial', channel='ig')]
    api.analytics['/analytics/post/native'] = [metric('Impressions', ('2026-10-28', '400')), metric('Clicks', ('2026-10-28', '6')),
                                              metric('Clicks by Type', ('2026-10-28', '6')), metric('Reactions', ('2026-10-28', '0'))]
    api.analytics['/analytics/post/editorial'] = [metric('Saves', ('2026-10-28', '3')), metric('Views', ('2026-10-28', '250'))]
    with store.db() as db:
        db.execute('INSERT INTO weeks(id,week,status,created,plan) VALUES(?,?,?,?,?)',
                   ('week', '2026-10-19', 'review', NOW.isoformat(), dumps({'subjects': [{'slot': 0, 'kind': 'advice', 'angle': 'Choisir un piano pour débuter'}]})))
        db.execute('INSERT INTO items(id,week_id,kind,slot,status,content,media,scheduled_at) VALUES(?,?,?,?,?,?,?,?)',
                   ('item', 'week', 'social', 0, 'published', dumps({'title': 'Quel piano choisir ?'}), dumps({'product_snapshot': {'title': 'Piano exact', 'token': 'secret'}}), NOW.isoformat()))
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?,?)', ('delivery', 'item', 1, 'instagram', 'published', dumps([{'postId': 'editorial', 'token': 'secret'}]), NOW.isoformat()))
    result = generate_report(store, api, current=NOW)
    posts = {row['id']: row for row in result['posts']}
    assert posts['native']['source'] == 'postiz'
    assert posts['editorial']['source'] == 'studio' and posts['editorial']['item_id'] == 'item'
    assert posts['editorial']['title'] == 'Quel piano choisir ?'
    assert posts['editorial']['subject_kind'] == 'advice' and posts['editorial']['product'] == 'Piano exact'
    assert posts['editorial']['angle'] == 'Choisir un piano pour débuter'
    assert {metric['key']: metric['value'] for metric in posts['native']['metrics']} == {'reach': 400, 'clicks': 6, 'reactions': 0}
    assert all(metric['scope'] == 'lifetime' for post in result['posts'] for metric in post['metrics'])
    assert 'secret' not in dumps(result)
    assert any('Cumul depuis' in note for note in result['limitations'])


def test_missing_and_failures_are_not_zero_and_do_not_export_error_payloads(store):
    api = API()
    api.channels[0]['disabled'] = True
    api.posts = [post('fbpost'), post('missing', channel='ig'), post('error', channel='ig')]
    api.analytics['/analytics/post/missing'] = {'missing': True}
    api.failures = {'/analytics/ig', '/analytics/post/error'}
    result = generate_report(store, api, current=NOW)
    assert result['channels'][0]['status'] == 'disconnected'
    assert result['channels'][1]['status'] == 'unavailable'
    assert all(row['status'] == 'unavailable' and row['metrics'] == [] for row in result['posts'])
    assert all(call[1] not in ('/analytics/fb', '/analytics/post/fbpost') for call in api.calls)
    assert 'secret-access-token' not in dumps(result)
    assert any('3 publication(s)' in note for note in result['limitations'])
    assert any('Vérifier' in recommendation for recommendation in result['recommendations'])
    api.failures = {'/posts'}
    result = generate_report(store, api, current=NOW)
    assert result['posts'] == [] and all(row['published_count'] is None for row in result['channels'])
    assert 'Bilan partiel' in result['summary']
    api.failures = {'/integrations'}
    assert 'Bilan partiel' in generate_report(store, api, current=NOW)['summary']


def test_recurrence_and_duplicate_native_or_release_identifiers_are_not_new_posts(store):
    api = API()
    original = post('recurrence', date='2026-10-21T10:00:00Z', actualDate='2026-10-21T10:00:00Z', intervalInDays=1)
    api.posts = [original, {**original, 'publishDate': '2026-10-22T10:00:00Z'},
                 {**original, 'publishDate': '2026-10-23T10:00:00Z'},
                 post('old-recurrence', actualDate='2026-09-01T10:00:00Z', intervalInDays=1),
                 post('duplicate'), post('duplicate'), post('same-physical-post', releaseId='release_duplicate'),
                 post('another-network', channel='ig', releaseId='release_duplicate')]
    result = generate_report(store, api, current=NOW)
    assert {row['id'] for row in result['posts']} == {'recurrence', 'duplicate', 'another-network'}
    assert sum(call[1] == '/analytics/post/recurrence' for call in api.calls) == 1
    assert next(row for row in result['posts'] if row['id'] == 'recurrence')['published_at'] == '2026-10-21T10:00:00+00:00'


def test_rankings_require_same_account_format_metric_and_actual_difference(store):
    api = API()
    api.posts = [post('leader'), post('second'), post('video', settings={'post_type': 'reel'}), post('instagram', channel='ig'), post('unknown', settings='{}')]
    for identifier, count in [('leader', 10), ('second', 2), ('video', 1000), ('instagram', 2000), ('unknown', 4000)]:
        api.analytics['/analytics/post/' + identifier] = [metric('Reactions', ('2026-10-28', str(count)))]
    result = generate_report(store, api, current=NOW)
    assert 'leader' in result['recommendations'][0]
    assert '2 publications de même type déclaré' in result['recommendations'][0]
    assert 'ancienneté' in result['recommendations'][0]
    assert 'video' not in result['recommendations'][0] and 'instagram' not in result['recommendations'][0]
    api.analytics['/analytics/post/second'] = [metric('Reactions', ('2026-10-28', 10))]
    assert generate_report(store, api, current=NOW)['recommendations'][0].startswith('Aucun écart')


def test_invalid_duplicate_and_unknown_metrics_cannot_inflate_a_report(store):
    api = API()
    api.posts = [post('sample')]
    api.analytics['/analytics/fb'] = [
        metric('Page Impressions', ('2026-10-20', 9999), ('2026-10-27', 10), ('2026-10-27', 10), ('2026-10-29', 8888)),
        metric('Page followers', ('2026-10-27', 3), ('2026-10-27', 4)),
        metric('Media views', ('2026-10-27', 'NaN')),
        metric('Posts Engagement', ('2026-10-27', True)),
        metric('Conversion Rate', ('2026-10-27', 100)),
    ]
    api.analytics['/analytics/post/sample'] = [metric('Reactions', ('2026-10-28', 3)), metric('Reactions', ('2026-10-28', 4)),
                                             metric('Clicks', ('2026-10-28', 0)), metric('Views', ('2026-10-28', '-3'))]
    result = generate_report(store, api, current=NOW)
    assert result['channels'][0]['status'] == 'partial'
    assert [value['value'] for value in result['channels'][0]['metrics']] == [10]
    assert result['posts'][0]['status'] == 'partial'
    assert [(value['key'], value['value']) for value in result['posts'][0]['metrics']] == [('clicks', 0)]


def test_report_is_readonly_ignores_ai_and_filters_secret_bearing_url(store):
    api = API()
    api.channels += [dict(api.channels[0]), {'id': 'other', 'identifier': 'youtube', 'name': 'Other'}]
    api.channels[1]['identifier'] = 'instagram-standalone'
    api.posts = [post('safe', channel='ig', releaseURL='https://instagram.com/p/safe'),
                 post('unsafe', releaseURL='https://facebook.com/p/unsafe?access_token=secret')]
    class NoAI:
        def ask(self, prompt):
            raise AssertionError('Reports should not spend AI quota or send analytics elsewhere')
    with store.db() as db:
        before = list(db.execute('SELECT * FROM items'))
    result = generate_report(store, api, NoAI(), current=NOW)
    assert len(result['channels']) == 2
    assert next(post for post in result['posts'] if post['id'] == 'safe')['url'] == 'https://instagram.com/p/safe'
    assert next(post for post in result['posts'] if post['id'] == 'unsafe')['url'] is None
    assert 'secret' not in dumps(result)
    with store.db() as db:
        assert list(db.execute('SELECT * FROM items')) == before

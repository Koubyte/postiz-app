"""Read-only, evidence-based weekly digest of the connected Meta channels.

Postiz's Meta providers return lifetime *post* snapshots, not a seven-day
increment. Instagram account analytics mix daily series and window totals.
Keep those scopes explicit and never use provider ``percentageChange`` (some
providers currently return a constant placeholder).
"""
import html
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from store import PARIS


PROVIDERS = {'facebook': 'Facebook', 'instagram': 'Instagram', 'instagram-standalone': 'Instagram'}
LABELS = {
    'page impressions': ('reach', 'Portée quotidienne'),
    'posts engagement': ('engagement', 'Interactions quotidiennes'),
    'page followers': ('follows', 'Abonnements quotidiens'),
    'media views': ('views', 'Vues quotidiennes'),
    'follower count': ('followers', 'Mesure quotidienne des abonnements'),
    'followers': ('followers', 'Mesure des abonnements'),
    'reach': ('reach', 'Portée'),
    'impressions': ('reach', 'Portée'),
    'views': ('views', 'Vues'),
    'plays': ('plays', 'Lectures'),
    'likes': ('likes', 'Mentions J’aime'),
    'comments': ('comments', 'Commentaires'),
    'shares': ('shares', 'Partages'),
    'saves': ('saves', 'Enregistrements'),
    'replies': ('replies', 'Réponses'),
    'reactions': ('reactions', 'Réactions'),
    'clicks': ('clicks', 'Clics'),
    'engagement': ('engagement', 'Interactions'),
}
INSTAGRAM_WINDOW = {'likes', 'views', 'comments', 'shares', 'saves', 'replies'}
DAILY_NOTE = 'Dernière mesure quotidienne reçue ; les jours ne sont pas additionnés.'
POST_NOTE = 'Cumul depuis la publication au dernier relevé fourni ; ce ne sont pas les gains de la semaine.'


def _text(value, limit=240):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value if isinstance(value, str) else ''))).strip()[:limit]


def _json(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return int(result) if result.is_integer() else result


def _public_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value[:2000] if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.query else None
    except ValueError:
        return None


def _metrics(raw, provider, current, *, post=False):
    """Allowlist labels and numbers, preserving upstream scope and real zeros."""
    if not isinstance(raw, list):
        return [], True
    groups = defaultdict(list)
    invalid = False
    for entry in raw:
        if not isinstance(entry, dict):
            invalid = True
            continue
        label = entry.get('label', '')
        match = LABELS.get(label.casefold()) if isinstance(label, str) else None
        # Clicks by Type is the same underlying clicks broken down, never an
        # additional metric to add to Clicks. Unknown rates/labels stay omitted.
        if not match:
            continue
        key, friendly = match
        points = {}
        ambiguous = set()
        values = entry.get('data')
        if not isinstance(values, list):
            invalid = True
            continue
        for point in values:
            day = _day(point.get('date')) if isinstance(point, dict) else None
            value = _number(point.get('total')) if isinstance(point, dict) else None
            if day is None or value is None:
                invalid = True
                continue
            if day > current.astimezone(PARIS).date() or (not post and day < current.astimezone(PARIS).date() - timedelta(days=7)):
                continue
            date = day.isoformat()
            if date in points and points[date] != value:
                ambiguous.add(date)
                invalid = True
            points[date] = value
        for date in ambiguous:
            points.pop(date, None)
        if not points:
            continue
        series = [{'date': date, 'value': points[date]} for date in sorted(points)]
        if post:
            scope, note = 'lifetime', POST_NOTE
        elif provider.startswith('instagram') and key in INSTAGRAM_WINDOW:
            scope, note = 'requested_window', 'Total de la fenêtre de 7 jours demandée au réseau ; date du relevé, pas activité de ce seul jour.'
        else:
            scope, note = 'daily_last', DAILY_NOTE
        groups[key].append({'key': key, 'label': friendly, 'value': series[-1]['value'],
                            'scope': scope, 'observed_at': series[-1]['date'], 'series': series, 'note': note})
    metrics = []
    for values in groups.values():
        # Duplicate identical metrics are harmless; conflicting metrics with the
        # same name cannot be disambiguated after the provider's mapping.
        if all(value == values[0] for value in values):
            metrics.append(values[0])
        else:
            invalid = True
    return metrics, invalid


def _studio_context(store):
    """Join native IDs to editorial facts without exporting stored payloads."""
    context = {}
    with store.db() as db:
        rows = db.execute('''SELECT d.result,d.item_id,i.content,i.media,i.slot,w.plan,q.brief
            FROM deliveries d JOIN items i ON i.id=d.item_id
            LEFT JOIN weeks w ON w.id=i.week_id LEFT JOIN demand_items q ON q.item_id=i.id
            ORDER BY d.revision DESC,d.updated DESC''').fetchall()
    for row in rows:
        content, media, plan, brief = [_json(row[key]) or {} for key in ('content', 'media', 'plan', 'brief')]
        if not all(isinstance(value, dict) for value in (content, media, plan, brief)):
            continue
        subjects = plan.get('subjects', [])
        if not brief and isinstance(subjects, list):
            brief = next((subject for subject in subjects if isinstance(subject, dict) and subject.get('slot') == row['slot']), {})
        product = media.get('product_snapshot', {})
        if not isinstance(product, dict):
            product = {}
        result = _json(row['result'])
        for native in result if isinstance(result, list) else [result]:
            if not isinstance(native, dict):
                continue
            identifier = native.get('postId') or native.get('id')
            if isinstance(identifier, str) and identifier not in context:
                context[identifier] = {'item_id': row['item_id'], 'title': _text(content.get('title'), 180),
                    'subject_kind': brief.get('kind') if brief.get('kind') in ('product', 'advice', 'news') else None,
                    'angle': _text(brief.get('angle'), 500), 'product': _text(product.get('title'), 180) or None}
    return context


def _format(value):
    settings = _json(value) or {}
    kind = settings.get('post_type') if isinstance(settings, dict) else None
    return {'post': 'post', 'feed': 'post', 'reel': 'reel', 'reels': 'reel', 'video': 'video',
            'story': 'story', 'stories': 'story', 'carousel': 'carousel'}.get(kind, 'unknown')


def _recommendations(posts, channels):
    recommendations = []
    # Same account and format, same metric; no cross-network league table and
    # no invented combined engagement score. A sample is a testing lead only.
    groups = defaultdict(list)
    for post in posts:
        if post['format'] == 'unknown':
            continue
        for metric in post['metrics']:
            if metric['key'] in ('saves', 'shares', 'comments', 'clicks', 'reactions', 'likes'):
                groups[(post['channel_id'], post['format'], metric['key'])].append((post, metric))
    for key in sorted(groups, key=lambda k: (('saves', 'shares', 'comments', 'clicks', 'reactions', 'likes').index(k[2]), k[0], k[1])):
        entries = groups[key]
        if len(entries) < 2:
            continue
        entries.sort(key=lambda row: (-row[1]['value'], row[0]['id']))
        leader, metric = entries[0]
        if metric['value'] <= entries[1][1]['value'] or metric['value'] == 0:
            continue
        if any(leader['id'] == seen[0] for seen in recommendations):
            continue
        angle = leader['angle'] or leader['title']
        recommendations.append((leader['id'],
            f"Sur {PROVIDERS[leader['provider']]} ({leader['channel_name']}), « {leader['title']} » a le plus de {metric['label'].lower()} "
            f"parmi {len(entries)} publications de même type déclaré mesurées ({metric['value']}). "
            f"Tester un nouveau contenu autour de « {angle[:180]} », puis comparer ; les cumuls dépendent aussi de l’ancienneté des posts."))
        if len(recommendations) >= 3:
            break
    result = [text for _, text in recommendations]
    if not result:
        measured = sum(bool(post['metrics']) for post in posts)
        if measured < 2:
            result.append('Pas assez de publications comparables mesurées pour recommander un sujet gagnant. Conserver des angles variés et refaire le bilan après de nouvelles publications.')
        else:
            result.append('Aucun écart exploitable entre publications comparables cette semaine. Tester un seul changement d’angle à la fois, sans modifier automatiquement les horaires.')
    unavailable = [channel['name'] for channel in channels if channel['status'] in ('unavailable', 'disconnected')]
    if unavailable:
        result.append('Vérifier les statistiques et la connexion de ' + ', '.join(unavailable) + ' dans Postiz avant de tirer des conclusions sur ces comptes.')
    return result


def generate_report(store, publisher, generator=None, *, current=None):
    """Return a credential-free report; never writes posts or changes schedules.

    ``generator`` is accepted for callers sharing their worker dependency set.
    Calculations/recommendations are deliberately deterministic and need no AI.
    ``current`` makes calendar/DST boundaries reproducible in tests.
    """
    current = (current or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = current.astimezone(PARIS)
    end = datetime.combine(local.date() - timedelta(days=local.weekday()), datetime.min.time(), PARIS)
    start = end - timedelta(days=7)
    period = {'start': start.isoformat(), 'end': end.isoformat(),
              'label': f"Du {start:%d/%m/%Y} au {end - timedelta(days=1):%d/%m/%Y} (heure de Paris)",
              'end_exclusive': True}
    limitations = [POST_NOTE,
        'Les comptes présentent les 7 jours glissants demandés au réseau, distincts de la semaine complète des publications. Les bornes et dates quotidiennes sont celles du fournisseur.',
        'Seules les publications enregistrées dans Postiz sont incluses ; des publications faites directement sur les réseaux peuvent manquer au détail des posts.',
        'Aucun total d’abonnés, portée unique ou taux n’est additionné ; les pourcentages de variation fournis par Postiz sont ignorés.',
        'Les écarts observés ne prouvent pas qu’un angle, un format ou un horaire cause de meilleurs résultats. Aucun horaire n’est modifié.']
    channels_available = True
    try:
        raw_channels = publisher.api('GET', '/integrations')
        if not isinstance(raw_channels, list):
            raise ValueError('invalid channels')
    except Exception:
        raw_channels = []
        channels_available = False
        limitations.append('La liste des comptes connectés est indisponible. Ce bilan est incomplet, pas un résultat à zéro.')
    channels = []
    seen_channels = set()
    for channel in raw_channels:
        if not isinstance(channel, dict) or channel.get('identifier') not in PROVIDERS or not isinstance(channel.get('id'), str) or channel['id'] in seen_channels:
            continue
        seen_channels.add(channel['id'])
        provider = channel['identifier']
        result = {'id': channel['id'], 'name': _text(channel.get('name')) or PROVIDERS[provider], 'provider': provider,
                  'status': 'disconnected' if channel.get('disabled') else 'unavailable', 'metrics': [], 'published_count': 0,
                  'period': {'start': (local.date() - timedelta(days=7)).isoformat(), 'end': local.date().isoformat(),
                             'label': '7 jours glissants demandés au réseau ; relevé le ' + local.strftime('%d/%m/%Y')}}
        if not channel.get('disabled'):
            try:
                raw = publisher.api('GET', '/analytics/' + quote(channel['id'], safe=''), params={'date': '7'})
                result['metrics'], partial = _metrics(raw, provider, current)
                if result['metrics']:
                    result['status'] = 'partial' if partial else 'available'
            except Exception:
                pass  # Never expose upstream error bodies, URLs or credentials.
        channels.append(result)
    channel_by_id = {channel['id']: channel for channel in channels}
    posts = []
    list_available = True
    try:
        response = publisher.api('GET', '/posts', params={'startDate': start.astimezone(timezone.utc).isoformat(),
                                                        'endDate': (end.astimezone(timezone.utc) - timedelta(microseconds=1)).isoformat()})
        raw_posts = response.get('posts') if isinstance(response, dict) else None
        if not isinstance(raw_posts, list):
            raise ValueError('invalid post listing')
    except Exception:
        raw_posts = []
        list_available = False
        limitations.append('La liste des publications Postiz est indisponible ; le nombre de publications n’est pas connu.')
    context = _studio_context(store)
    seen_posts, seen_releases = set(), set()
    for raw in raw_posts:
        if not isinstance(raw, dict) or raw.get('state') != 'PUBLISHED' or not isinstance(raw.get('id'), str):
            continue
        integration = raw.get('integration')
        channel_id = integration.get('id') if isinstance(integration, dict) else integration
        channel = channel_by_id.get(channel_id) if isinstance(channel_id, str) else None
        if not channel:
            continue
        # Recurring listings contain projected duplicates. actualDate is the
        # stored date; future/older projections aren't additional publications.
        published = _date(raw.get('actualDate') or raw.get('publishDate'))
        if published is None or not start <= published < end or raw['id'] in seen_posts:
            continue
        release = raw.get('releaseId')
        release_key = (channel_id, release) if isinstance(release, str) and release and release != 'missing' else None
        if release_key and release_key in seen_releases:
            continue
        seen_posts.add(raw['id'])
        if release_key:
            seen_releases.add(release_key)
        details = context.get(raw['id'], {})
        post = {'id': raw['id'], 'channel_id': channel_id, 'channel_name': channel['name'], 'provider': channel['provider'],
                'title': details.get('title') or _text(raw.get('content'), 180) or 'Publication sans texte',
                'published_at': published.isoformat(), 'url': _public_url(raw.get('releaseURL')), 'format': _format(raw.get('settings')),
                'item_id': details.get('item_id'), 'source': 'studio' if details else 'postiz',
                'subject_kind': details.get('subject_kind'), 'angle': details.get('angle') or '', 'product': details.get('product'),
                'metrics': [], 'status': 'unavailable'}
        if channel['status'] != 'disconnected':
            try:
                raw_metrics = publisher.api('GET', '/analytics/post/' + quote(raw['id'], safe=''), params={'date': '7'})
                post['metrics'], partial = _metrics(raw_metrics, channel['provider'], current, post=True)
                if post['metrics']:
                    post['status'] = 'partial' if partial else 'available'
            except Exception:
                pass
        posts.append(post)
        channel['published_count'] += 1
    posts.sort(key=lambda post: (post['published_at'], post['id']), reverse=True)
    if not list_available or not channels_available:
        for channel in channels:
            channel['published_count'] = None
    if not channels:
        limitations.append('Aucun compte Facebook ou Instagram exploitable dans la réponse reçue.')
    unavailable_count = sum(not post['metrics'] for post in posts)
    if unavailable_count:
        limitations.append(f'{unavailable_count} publication(s) sans statistiques exploitables : donnée absente ne signifie pas zéro interaction.')
    measured = len(posts) - unavailable_count
    summary = (f'{len(posts)} publication(s) Facebook/Instagram sur la semaine complète ; {measured} avec des statistiques exploitables.'
               if list_available and channels_available else 'Bilan partiel : les comptes ou la liste des publications de la semaine n’ont pas pu être chargés.')
    return {'generated_at': current.isoformat(), 'period': period, 'summary': summary, 'channels': channels, 'posts': posts,
            'recommendations': _recommendations(posts, channels), 'limitations': limitations}

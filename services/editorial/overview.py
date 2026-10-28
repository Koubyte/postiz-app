"""Private, read-only content index for weekly and on-demand production."""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from store import Conflict


FILTERS = {'all', 'review', 'attention', 'scheduled', 'published', 'progress', 'blog'}
PROGRESS = {'queued', 'generating', 'rendering', 'publishing'}
SCHEDULED = {'approved', 'scheduled'}
UNAPPROVED = {'queued', 'generating', 'rendering', 'review', 'rejected', 'failed', 'blocked'}
MEDIA_FIELDS = ('media', 'blog_media', 'source_media', 'source_media_2', 'source_media_3', 'mask_media')


def normalized(value):
    """French search accepts É/é/e and decomposed accents alike."""
    return ''.join(char for char in unicodedata.normalize('NFKD', value or '').casefold()
                   if not unicodedata.combining(char))


def media_url(filename):
    return '/editorial/media/' + filename if isinstance(filename, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', filename) else None


def rows(db):
    # Do not send full articles, product snapshots, approval seals or delivery
    # payloads with every index refresh. The independent detail endpoint supplies
    # the selected content. rowid is an immutable, deterministic creation order.
    return db.execute('''
        SELECT i.id,i.week_id,i.kind,i.slot,i.status,i.revision,i.scheduled_at,i.error,
               w.week,d.conversation_id,a.parent_id,a.state AS companion_state,
               COALESCE(NULLIF(json_extract(i.content,'$.title'),''),
                        NULLIF(json_extract(d.brief,'$.title'),''),
                        CASE WHEN i.kind='blog' THEN json_extract(w.plan,'$.article.title')
                             ELSE (SELECT json_extract(subject.value,'$.title')
                                   FROM json_each(w.plan,'$.subjects') subject
                                   WHERE json_extract(subject.value,'$.slot')=i.slot LIMIT 1)
                        END,
                        CASE WHEN i.kind='blog' THEN 'Article en préparation' ELSE 'Post en préparation' END) AS title,
               substr(COALESCE(NULLIF(json_extract(i.content,'$.facebook'),''),
                               NULLIF(json_extract(i.content,'$.instagram'),''),
                               json_extract(i.content,'$.excerpt'),''),1,220) AS preview,
               json_extract(i.media,'$.media') AS media,
               json_extract(i.media,'$.blog_media') AS blog_media,
               COALESCE(json_extract(i.content,'$.facebook'),'') || ' ' ||
               COALESCE(json_extract(i.content,'$.instagram'),'') || ' ' ||
               COALESCE(json_extract(i.content,'$.markdown'),'') || ' ' ||
               COALESCE(json_extract(i.content,'$.excerpt'),'') AS search_text
          FROM items i
          LEFT JOIN weeks w ON w.id=i.week_id
          LEFT JOIN demand_items d ON d.item_id=i.id
          LEFT JOIN companion_articles a ON a.article_id=i.id
         ORDER BY i.rowid DESC
    ''')


def summarize(row, current):
    status = row['status']
    source = 'companion' if row['parent_id'] else 'on_demand' if row['conversation_id'] else 'weekly'
    overdue = False
    # An active companion already has authorization from its parent post, and
    # its actual publication time is chosen by Companion.run after writing.
    if status in UNAPPROVED and not (source == 'companion' and row['companion_state'] == 'active'):
        try:
            due = datetime.fromisoformat(row['scheduled_at'].replace('Z', '+00:00'))
            overdue = due.tzinfo is not None and due <= current + timedelta(minutes=5)
        except (AttributeError, ValueError):
            pass
    postiz = status in {'scheduled', 'managed'} or (status == 'published' and row['kind'] == 'social')
    result = {key: row[key] for key in ('id', 'kind', 'slot', 'status', 'revision', 'conversation_id', 'week_id', 'week')}
    result.update(
        title=str(row['title'])[:240], preview=row['preview'], source=source,
        scheduled_at=None if status == 'managed' else row['scheduled_at'],
        schedule_authority='postiz' if postiz else 'studio',
        overdue=overdue,
        warning='Choisissez un nouvel horaire avant de valider.' if overdue else None,
        error=row['error'], media_url=media_url(row['media']), blog_media_url=media_url(row['blog_media']),
    )
    return result


def categories(item):
    return {
        'all': True,
        'review': item['status'] == 'review',
        'attention': item['status'] in {'failed', 'blocked', 'rejected'} or item['overdue'],
        'scheduled': item['status'] in SCHEDULED,
        'published': item['status'] == 'published',
        'progress': item['status'] in PROGRESS,
        'blog': item['kind'] == 'blog',
    }


def list_contents(store, *, q='', filter='all', offset=0, limit=30, current=None):
    if filter not in FILTERS:
        raise Conflict('Filtre de contenus inconnu.')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise Conflict('Pagination invalide.')
    current = current or datetime.now(timezone.utc)
    query = normalized(q.strip())
    counts = dict.fromkeys(('all', 'review', 'attention', 'scheduled', 'published', 'progress', 'blog'), 0)
    selected = []
    total = 0
    with store.db() as db:
        for row in rows(db):
            item = summarize(row, current)
            groups = categories(item)
            for key, matches in groups.items():
                counts[key] += int(matches)
            if not groups[filter] or (query and query not in normalized(row['title'] + ' ' + row['search_text'])):
                continue
            if offset <= total < offset + limit:
                selected.append(item)
            total += 1
    return {'items': selected, 'total': total, 'offset': offset, 'limit': limit, 'counts': counts}


def content_detail(store, identifier):
    with store.db() as db:
        item = store.item(identifier, db)
        row = db.execute('''SELECT d.conversation_id,w.week,a.parent_id
                              FROM items i
                              LEFT JOIN demand_items d ON d.item_id=i.id
                              LEFT JOIN weeks w ON w.id=i.week_id
                              LEFT JOIN companion_articles a ON a.article_id=i.id
                             WHERE i.id=?''', (identifier,)).fetchone()
        item.update(
            conversation_id=row['conversation_id'], week=row['week'],
            source='companion' if row['parent_id'] else 'on_demand' if row['conversation_id'] else 'weekly',
            schedule_authority='postiz' if item['status'] in {'scheduled', 'managed'} or (item['status'] == 'published' and item['kind'] == 'social') else 'studio',
        )
        for key in MEDIA_FIELDS:
            item[key + '_url'] = media_url(item['media'].get(key))
        # Approval seals are server-side implementation details, never needed by
        # the owner editor. Delivery metadata suffices to show channel status.
        item.pop('approval_hash', None)
        item['deliveries'] = [dict(delivery) for delivery in db.execute(
            'SELECT id,item_id,revision,channel,status,updated FROM deliveries WHERE item_id=? ORDER BY channel,revision',
            (identifier,),
        )]
    return item

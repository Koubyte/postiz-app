"""Reserve on-demand slots against both the weekly studio and native Postiz."""
import json
from datetime import datetime,timedelta,timezone
from store import Conflict,PARIS

GAP=timedelta(hours=2)

def calendar_times(publisher,exclude_ids=()):
    start=datetime.now(timezone.utc)-timedelta(days=2)
    result=publisher.api('GET','/posts',params={'startDate':start.isoformat(),'endDate':(start+timedelta(days=96)).isoformat()})
    if not isinstance(result,dict) or not isinstance(result.get('posts'),list):raise Conflict('Le calendrier Postiz n’a pas pu être vérifié. Réessayez avant de préparer ce post.')
    times=[]
    for p in result['posts']:
        if p.get('id') in exclude_ids or p.get('state') not in ('QUEUE','PUBLISHED'):continue
        raw=p.get('publishDate')
        try:
            d=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if d.tzinfo is None:raise ValueError()
        except (ValueError,AttributeError):raise Conflict('Un horaire du calendrier Postiz est illisible. Vérifiez le calendrier.')
        times.append(d)
    return times

def reservations(db,exclude=None):
    result=[]
    for row in db.execute("SELECT id,scheduled_at FROM items WHERE kind='social' AND status NOT IN ('rejected','failed','blocked')"):
        if row['id']!=exclude:result.append(datetime.fromisoformat(row['scheduled_at']))
    for row in db.execute("SELECT plan FROM weeks WHERE status IN ('plan_review','revising')"):
        for s in json.loads(row['plan']).get('subjects',[]):
            if s.get('scheduled_at'):result.append(datetime.fromisoformat(s['scheduled_at'].replace('Z','+00:00')))
    return result

def available_slot(requested,occupied):
    due=datetime.fromisoformat(requested)
    limit=due+timedelta(days=7)
    while due<limit:
        conflicts=[other for other in occupied if abs(other-due)<GAP]
        if not conflicts:return due.astimezone(timezone.utc).isoformat()
        due=max(conflicts)+GAP
        local=due.astimezone(PARIS)
        if local.hour>=21:due=(local+timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0)
        elif local.hour<9:due=local.replace(hour=9,minute=0,second=0,microsecond=0)
    raise Conflict('Aucun créneau suffisamment espacé dans les sept prochains jours. Choisissez une autre date.')

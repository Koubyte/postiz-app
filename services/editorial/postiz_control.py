"""Organization-scoped native Postiz tools, with durable mutation receipts."""
import json
import re
import secrets
import threading
from datetime import datetime,timedelta,timezone
from store import Conflict,dumps,digest,now
from spacing import available_slot,calendar_times,reservations
from conversation import checked_date

ID=r'[A-Za-z0-9_-]+'
READ=(r'/posts',rf'/posts/{ID}',r'/integrations',rf'/integration-settings/{ID}',r'/media',rf'/media/{ID}/status',r'/groups',r'/notifications',rf'/analytics/{ID}',rf'/analytics/post/{ID}')
WRITE={'POST':(r'/posts',r'/upload-from-url'), 'PUT':(rf'/posts/{ID}/settings',rf'/posts/{ID}/status'), 'DELETE':(rf'/posts/{ID}',)}

class PostizControl:
    def __init__(self,store,publisher):
        self.store=store;self.publisher=publisher;self.lock=threading.RLock()
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS postiz_changes (token TEXT PRIMARY KEY, body TEXT NOT NULL, snapshots TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS postiz_operations (request_id TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL, status TEXT NOT NULL, result TEXT, created TEXT NOT NULL)')
    def capabilities(self):
        return {'calendar_url':'/launches','read_paths':list(READ),'write_paths':WRITE,
          'workflow':'read_postiz -> preview_postiz_change -> apply_postiz_change. Draft edits need no publication approval. Scheduling, changing an active scheduled post, and deletion require the owner’s explicit agreement to the returned preview. Same preview and request_id on retry.',
          'create_or_edit':{'method':'POST','path':'/posts','body':{'type':'draft or schedule','date':'ISO date with timezone','shortLink':False,'tags':[], 'posts':[{'integration':{'id':'channel id from /integrations'},'group':'existing group only when editing','value':[{'id':'existing post ID only when editing','content':'Grok’s finished text','image':[{'id':'media id','path':'media URL'}]}],'settings':{'__type':'facebook or instagram','post_type':'post'}}]}},
          'editing':'Read /posts/ID. Preserve every entry of posts (threads), image, group, settings, tags and interval unless deliberately changing it. Include existing IDs, never recreate an existing post as new. Editing with type=draft withdraws it from scheduling until approval. Use type=schedule with the complete desired content/date to reschedule in place. Published social content cannot be edited on the network through these Postiz endpoints; do not republish it as a workaround.',
          'media':'GET /media lists reusable media. POST /upload-from-url body {url: HTTPS_URL} imports an image without publishing. Read /integration-settings/ID for the provider schema.',
          'studio':'get_content also returns postiz_posts for delivered studio items. Edit those native IDs using these tools. edit_content changes studio draft text directly without Codex. prepare_content/revise_content remain available for AI research or images.'}
    def read(self,path,query=None):
        if not any(re.fullmatch(pattern,path) for pattern in READ):raise Conflict('Chemin de lecture Postiz non reconnu. Consultez get_postiz_capabilities.')
        if query is not None and not isinstance(query,dict):raise Conflict('Paramètres de lecture invalides.')
        query=dict(query or {})
        if path=='/posts':
            query.setdefault('startDate',(datetime.now(timezone.utc)-timedelta(days=30)).isoformat())
            query.setdefault('endDate',(datetime.now(timezone.utc)+timedelta(days=96)).isoformat())
        return self.publisher.api('GET',path,params=query)
    def targets(self,method,path,body):
        if path=='/posts':return list(dict.fromkeys(v['id'] for p in body.get('posts',[]) for v in p.get('value',[]) if v.get('id')))
        match=re.fullmatch(r'/posts/('+ID+r')(?:/(?:settings|status))?',path)
        return [match[1]] if match else []
    def linked(self,ids,db):
        linked=set()
        for row in db.execute('SELECT item_id,result FROM deliveries'):
            value=json.loads(row['result']);entries=value if isinstance(value,list) else [value]
            if any(e.get('postId',e.get('id')) in ids for e in entries if isinstance(e,dict)):linked.add(row['item_id'])
        return linked
    def occupied(self,ids):
        with self.store.db() as db:
            linked=self.linked(ids,db)
            related=set(ids)
            for row in db.execute('SELECT item_id,result FROM deliveries'):
                if row['item_id'] not in linked:continue
                value=json.loads(row['result']);entries=value if isinstance(value,list) else [value]
                related.update(e.get('postId',e.get('id')) for e in entries if isinstance(e,dict))
            # Exclude only the local reservations for the same delivered subjects.
            local=[datetime.fromisoformat(r['scheduled_at']) for r in db.execute("SELECT id,scheduled_at FROM items WHERE kind='social' AND status NOT IN ('rejected','failed','blocked','managed')") if r['id'] not in linked]
            for row in db.execute("SELECT plan FROM weeks WHERE status IN ('plan_review','revising')"):
                local += [datetime.fromisoformat(s['scheduled_at'].replace('Z','+00:00')) for s in json.loads(row['plan']).get('subjects',[]) if s.get('scheduled_at')]
        return calendar_times(self.publisher,related)+local
    def preview(self,method,path,body=None):
        if not any(re.fullmatch(pattern,path) for pattern in WRITE.get(method,())):raise Conflict('Opération Postiz non reconnue. Consultez get_postiz_capabilities.')
        body=json.loads(dumps(body or {}))
        if not isinstance(body,dict):raise Conflict('Le corps de la demande doit être un objet JSON.')
        if path=='/posts':
            if body.get('type') not in ('draft','schedule'):raise Conflict('Utilisez draft pour préparer ou schedule pour programmer après accord.')
            if not isinstance(body.get('posts'),list) or not body['posts']:raise Conflict('Indiquez au moins un post et son canal.')
            channels={c['id'] for c in self.read('/integrations') if not c.get('disabled')}
            for p in body['posts']:
                if not isinstance(p,dict) or p.get('integration',{}).get('id') not in channels:raise Conflict('Canal Postiz inconnu ou déconnecté.')
                if not isinstance(p.get('value'),list) or not p['value']:raise Conflict('Le contenu du post manque.')
                for v in p['value']:
                    if not isinstance(v,dict) or not isinstance(v.get('content'),str):raise Conflict('Texte du post invalide.')
                    if not isinstance(v.get('image'),list):raise Conflict('Indiquez image: [] ou les médias du post à conserver.')
                p.pop('date',None)
            body.setdefault('shortLink',False)
            body['date']=checked_date(body.get('date') or (datetime.now(timezone.utc)+timedelta(hours=3)).isoformat())
        ids=self.targets(method,path,body)
        snapshots={id:self.read('/posts/'+id) for id in ids}
        requires=method=='DELETE' or body.get('type')=='schedule'
        for snapshot in snapshots.values():
            if any(p['state']=='PUBLISHED' for p in snapshot['posts']):raise Conflict('Ce post est déjà publié. Ces outils modifient le calendrier Postiz, pas les publications déjà en ligne sur le réseau.')
            if any(p['state']=='QUEUE' for p in snapshot['posts']):requires=True
        if path=='/posts':
            for p in body['posts']:
                existing=[v['id'] for v in p['value'] if v.get('id')]
                if p.get('group') and not existing:raise Conflict('Un groupe existant exige les identifiants des posts à modifier.')
                if existing:
                    snap=snapshots[existing[0]]
                    if p.get('group')!=snap['group'] or p['integration']['id']!=snap['integration']:raise Conflict('Conservez le groupe et le canal du post existant.')
                    if any(v['id'] not in {x['id'] for x in snap['posts']} for v in p['value'] if v.get('id')):raise Conflict('Ne mélangez pas plusieurs fils dans un même post.')
            if 'tags' not in body:
                tags=[s.get('tags',[]) for s in snapshots.values()]
                if tags and any(t!=tags[0] for t in tags):raise Conflict('Ces posts ont des étiquettes différentes ; modifiez-les séparément pour les conserver.')
                body['tags']=tags[0] if tags else []
            intervals={p.get('intervalInDays') for s in snapshots.values() for p in s['posts']}
            if 'inter' not in body and intervals:
                if len(intervals)>1:raise Conflict('Modifiez séparément les posts aux récurrences différentes.')
                body['inter']=intervals.pop()
            body['date']=available_slot(body['date'],self.occupied(ids))
        if path.endswith('/status'):
            if body.get('status')!='draft':raise Conflict('Pour programmer, utilisez POST /posts avec type=schedule et la date souhaitée afin de vérifier l’espacement.')
        if path=='/upload-from-url':
            from urllib.parse import urlsplit
            url=urlsplit(body.get('url',''))
            if url.scheme!='https' or not url.hostname or url.username:raise Conflict('Indiquez une URL HTTPS de média.')
        token=secrets.token_urlsafe(32)
        change={'method':method,'path':path,'body':body,'requires_owner_confirmation':requires}
        with self.store.db() as db:db.execute('INSERT INTO postiz_changes VALUES(?,?,?,?)',(token,dumps(change),dumps(snapshots),now()))
        return {'preview_token':token,**change,'current_posts':snapshots,'calendar_url':'/launches'}
    def operation(self,request_id):
        with self.store.db() as db:row=db.execute('SELECT * FROM postiz_operations WHERE request_id=?',(request_id,)).fetchone()
        if not row:raise Conflict('Opération inconnue.')
        return {'request_id':request_id,'status':row['status'],'result':json.loads(row['result']) if row['result'] else None}
    def apply(self,request_id,token,owner_confirmation=''):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',request_id):raise Conflict('Utilisez un request_id unique (UUID).')
        with self.lock:
            with self.store.db() as db:
                previous=db.execute('SELECT * FROM postiz_operations WHERE request_id=? OR token=?',(request_id,token)).fetchone()
                if previous:
                    if previous['token']!=token:raise Conflict('Ce request_id désigne un autre aperçu.')
                    if previous['status']=='done':return json.loads(previous['result'])
                    raise Conflict('Résultat précédent à vérifier dans Postiz ; aucune répétition automatique de cette opération.')
                row=db.execute('SELECT * FROM postiz_changes WHERE token=?',(token,)).fetchone()
                if not row:raise Conflict('Aperçu inconnu.')
                change=json.loads(row['body']);snapshots=json.loads(row['snapshots'])
                if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':raise Conflict('Le studio est suspendu.')
            if change['requires_owner_confirmation'] and not owner_confirmation.strip():raise Conflict('Montrez l’aperçu et transmettez l’accord explicite du propriétaire avant de programmer ou modifier un post actif.')
            for id,snapshot in snapshots.items():
                if digest(self.read('/posts/'+id))!=digest(snapshot):raise Conflict('Ce post a changé depuis l’aperçu ; préparez un nouvel aperçu.')
            body=change['body']
            if change['path']=='/posts' and body['type']=='schedule':
                due=datetime.fromisoformat(body['date'])
                if due<=datetime.now(timezone.utc):raise Conflict('La date est passée ; préparez un nouvel horaire.')
                if available_slot(body['date'],self.occupied(list(snapshots)))!=body['date']:raise Conflict('Le calendrier a changé depuis l’aperçu ; proposez le nouveau créneau.')
            with self.store.db() as db:
                db.execute("INSERT INTO postiz_operations VALUES(?,?,'pending',NULL,?)",(request_id,token,now()))
            try:
                result=self.publisher.api(change['method'],change['path'],**({'json':body} if change['method']!='DELETE' else {}))
                if change['path']=='/posts' and (not isinstance(result,list) or not result or any(not e.get('postId') for e in result)):raise Conflict('Postiz n’a pas confirmé les identifiants.')
                output={'result':result,'calendar_url':'/launches','requires_owner_approval':body.get('type')=='draft'}
                with self.store.db() as db:
                    # Native Postiz becomes the source of truth for edited deliveries.
                    for item_id in self.linked(set(snapshots),db):
                        item=self.store.item(item_id,db);self.store.snapshot(db,item)
                        db.execute("UPDATE items SET status='managed',revision=revision+1,error=NULL WHERE id=?",(item_id,))
                        db.execute("UPDATE deliveries SET status='managed' WHERE item_id=?",(item_id,))
                    db.execute("UPDATE postiz_operations SET status='done',result=? WHERE request_id=?",(dumps(output),request_id))
                    self.store.event(db,'Grok Bot : '+change['method']+' '+change['path']+(' · Accord : '+owner_confirmation[:2000] if owner_confirmation else ''),'grok-agent')
                return output
            except Exception:
                with self.store.db() as db:db.execute("UPDATE postiz_operations SET status='uncertain' WHERE request_id=?",(request_id,))
                raise Conflict('Postiz n’a pas confirmé le résultat. Consultez get_postiz_operation et le calendrier avant une nouvelle action ; ne recréez pas le post.')

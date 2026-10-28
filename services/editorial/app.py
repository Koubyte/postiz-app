import asyncio
import json
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from store import Store, Conflict, now, uid, dumps, PARIS, monday_next
from generation import Generator, GenerationError, validate_plan, validate_content, safe_sources
from publisher import Publisher
from media import MediaBlocked
from conversation import Conversation
from companion import Companion
from agent import AgentService, BearerGate, build_mcp, INSTRUCTIONS
from spacing import calendar_times as read_calendar, reservations, available_slot
from overview import list_contents, content_detail
from strategy import Strategy, JOBS as STRATEGY_JOBS

ROOT=Path(__file__).parent
store=Store(os.environ.get('EDITORIAL_DATA','/data'))
generator=Generator(store)
publisher=Publisher(store,generator)
conversation=Conversation(store,generator)
companion=Companion(store,generator)
stop=threading.Event()

def calendar_times(exclude_ids=()):return read_calendar(publisher,exclude_ids)

agent_service=AgentService(store,calendar_times,publisher)
strategy=Strategy(store,generator,publisher,agent_service)
agent_service.strategy=strategy
agent_mcp=build_mcp(agent_service)
agent_asgi=BearerGate(agent_mcp.streamable_http_app(),agent_service)

def safe_error(exc):
    return str(exc)[:500] if isinstance(exc,(Conflict,GenerationError,MediaBlocked)) else 'Une étape a échoué. Aucun nouvel envoi ne sera effectué sans vérification.'

def work(chat_only=False):
    while not stop.wait(3):
        if store.paused():continue
        with store.db() as db:
            row=db.execute("SELECT * FROM jobs WHERE status='queued' AND (kind='chat')=? ORDER BY updated LIMIT 1",(int(chat_only),)).fetchone()
            if not row:continue
            job=dict(row)
            db.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated=? WHERE id=?",(now(),job['id']))
            if job['kind'] in STRATEGY_JOBS:strategy.started(db,job['kind'],job['target'])
            if job['kind']=='plan':db.execute("UPDATE weeks SET status='preparing' WHERE id=?",(job['target'],))
            if job['kind']=='render':db.execute("UPDATE items SET status='rendering' WHERE id=?",(job['target'],))
            if job['kind'] in ('draft','demand','companion'):db.execute("UPDATE items SET status='generating' WHERE id=? AND status IN ('queued','failed')",(job['target'],))
        try:
            if job['kind'] in STRATEGY_JOBS:strategy.run(job['kind'],job['target'])
            else:{'plan':generator.plan,'draft':generator.draft,'render':generator.render,'revise':generator.revise,'chat':conversation.answer,'demand':conversation.draft,'companion':companion.run}[job['kind']](job['target'])
            with store.db() as db:
                db.execute("UPDATE jobs SET status='done',updated=? WHERE id=?",(now(),job['id']))
                db.execute("UPDATE weeks SET status='review' WHERE status='generating' AND EXISTS(SELECT 1 FROM items WHERE week_id=weeks.id) AND NOT EXISTS(SELECT 1 FROM items WHERE week_id=weeks.id AND status IN ('queued','generating','rendering'))")
        except Exception as exc:
            message=safe_error(exc)
            with store.db() as db:
                # Bounded retries for generation only. Publishing is a separate path.
                retry=job['attempts']<1
                db.execute('UPDATE jobs SET status=?,updated=? WHERE id=?',('queued' if retry else 'failed',now(),job['id']))
                if job['kind'] in STRATEGY_JOBS:
                    strategy.failed(db,job['kind'],job['target'],message,retry)
                elif job['kind']=='chat':
                    db.execute('UPDATE messages SET status=?,error=? WHERE id=?',('queued' if retry else 'failed',message,job['target']))
                elif job['kind']=='revise':
                    if not retry:store.fail_revision(db,job['target'],message)
                else:
                    table='weeks' if job['kind']=='plan' else 'items'
                    # A queued retry is still active work, not a terminal failure.
                    # Keep manual retry/edit controls unavailable until this job ends.
                    status=('preparing' if job['kind']=='plan' else 'queued') if retry else 'failed'
                    db.execute(f"UPDATE {table} SET status=?,error=? WHERE id=?",(status,None if retry else message,job['target']))
                store.event(db,message)
                if not retry:db.execute("UPDATE weeks SET status='review' WHERE status='generating' AND EXISTS(SELECT 1 FROM items WHERE week_id=weeks.id) AND NOT EXISTS(SELECT 1 FROM items WHERE week_id=weeks.id AND status IN ('queued','generating','rendering'))")

def schedule():
    count=0
    while not stop.wait(15):
        if store.paused():continue
        # Catch up the current due slot once; these jobs only research/read or draft.
        try:strategy.tick()
        except Conflict:pass  # Pause or a full queue can be retried next tick.
        local=datetime.now(timezone.utc).astimezone(PARIS)
        if local.weekday()>4 or (local.weekday()==4 and local.hour>=9):store.prepare()
        with store.db() as db:due=[r[0] for r in db.execute("SELECT id FROM items WHERE status='approved' AND (kind='social' OR scheduled_at<=?) ORDER BY scheduled_at",(now(),))]
        for id in due:
            try:publisher.deliver(id)
            except Exception as exc:
                with store.db() as db:
                    db.execute("UPDATE items SET status='blocked',error=? WHERE id=?",(safe_error(exc),id));store.event(db,safe_error(exc))
        count+=1
        if count%4==0:
            try:publisher.reconcile()
            except Exception:pass  # Later reconciliation is safe and never creates a post.

@asynccontextmanager
async def lifespan(app):
    store.recover()
    strategy.recover()
    threads=[]
    if os.environ.get('EDITORIAL_WORKER','true')=='true':
        # One process per persistent store; no duplicate workers across uvicorn instances.
        import fcntl
        lock=open(store.root/'worker.lock','w')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for target in (work,schedule):
            t=threading.Thread(target=target,daemon=True);t.start();threads.append(t)
        t=threading.Thread(target=work,args=(True,),daemon=True);t.start();threads.append(t)
    async with agent_mcp.session_manager.run():
        try:yield
        finally:stop.set()

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.mount('/editorial/agent',agent_asgi)
app.mount('/editorial/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(Conflict)
@app.exception_handler(GenerationError)
async def problem(request,exc):return JSONResponse({'error':safe_error(exc)},status_code=409)

async def actor(request):
    cookie=request.headers.get('cookie','')
    if not cookie:raise HTTPException(401,'Connectez-vous à Postiz.')
    try:
        response=await asyncio.to_thread(requests.get,os.environ['POSTIZ_INTERNAL_URL'].rstrip('/')+'/api/user/self',headers={'Cookie':cookie,'Host':os.environ['PUBLIC_URL'].split('://')[1]},timeout=8,allow_redirects=False)
        data=response.json() if response.status_code==200 else {}
    except Exception:raise HTTPException(401,'Connexion Postiz indisponible.')
    if data.get('orgId')!=os.environ['POSTIZ_ORG_ID'] or data.get('email','').casefold()!=os.environ['EDITORIAL_OWNER_EMAIL'].casefold() or data.get('impersonate'):
        raise HTTPException(403,'Ce studio est réservé au propriétaire Planète Laser.')
    return str(data['id'])

async def body(request):
    if request.headers.get('origin')!=os.environ['PUBLIC_URL'].rstrip('/') or request.headers.get('x-editorial-action')!='1':raise HTTPException(403,'Origine de la demande refusée.')
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>512*1024:raise HTTPException(413,'Demande trop volumineuse.')
        chunks.append(chunk)
    try:data=json.loads(b''.join(chunks))
    except ValueError:raise HTTPException(400,'JSON invalide.')
    if not isinstance(data,dict):raise HTTPException(400,'Objet JSON requis.')
    return data

def date(value):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        if not d.tzinfo:raise ValueError()
        return d.astimezone(timezone.utc).isoformat()
    except (ValueError,AttributeError):raise Conflict('La date doit comporter un fuseau horaire.')

def editable_content(value,item):
    if not isinstance(value,dict):raise Conflict('Contenu invalide.')
    merged={**item['content'],**{k:v for k,v in value.items() if k in ('title','headline','facebook','instagram','markdown','excerpt','slug','category','alt','sources')}}
    # Do not flag a catalogue price that was already injected by the studio.
    checked=dict(merged)
    price=item['content'].get('price_text')
    if price:
        for field in ('facebook','instagram','markdown'):
            if field in checked:checked[field]=checked[field].replace('Prix : '+price+'.','').replace('Prix Planète Laser : '+price+'.','')
    checked=validate_content(checked,item['kind'])
    for key in ('title','headline','excerpt','slug','category','alt','sources'):
        if key in checked:merged[key]=checked[key]
    merged['editorial_notes']=list(dict.fromkeys(item['content'].get('editorial_notes',[])+checked['editorial_notes']))
    return merged

@app.get('/health')
def health():return {'status':'ok'}
@app.get('/editorial')
def redirect():return FileResponse(ROOT/'static'/'index.html')
@app.get('/editorial/')
def index():return FileResponse(ROOT/'static'/'index.html')

@app.get('/editorial/api/state')
async def state(request:Request):
    await actor(request)
    with store.db() as db:
        weeks=[]
        for row in db.execute('SELECT * FROM weeks ORDER BY week DESC LIMIT 12'):
            week=dict(row);week['plan']=json.loads(week['plan']);week['items']=[]
            for ir in db.execute('SELECT id FROM items WHERE week_id=? ORDER BY kind DESC,slot',(week['id'],)):
                item=store.item(ir[0],db)
                for key,field in [('media','media_url'),('blog_media','blog_media_url'),('source_media','source_media_url'),('source_media_2','source_media_2_url'),('source_media_3','source_media_3_url'),('mask_media','mask_media_url')]:
                    item[field]='/editorial/media/'+item['media'][key] if item['media'].get(key) else None
                item['deliveries']=[{**dict(r),'result':json.loads(r['result'])} for r in db.execute('SELECT * FROM deliveries WHERE item_id=?',(item['id'],))]
                week['items'].append(item)
            change=db.execute("SELECT slot FROM plan_changes WHERE week_id=? AND status='queued' ORDER BY created DESC LIMIT 1",(week['id'],)).fetchone()
            week['pending_slot']=change['slot'] if change else None
            weeks.append(week)
        reqs=[dict(r) for r in db.execute('SELECT * FROM requests ORDER BY created DESC LIMIT 100')]
        events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 40')]
        paused=db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true'
    products=[{k:p.get(k) for k in ('id','title','ean','url','thumbnail','price','available')} for p in generator.catalogue]
    return {'paused':paused,'weeks':weeks,'requests':reqs,'products':products,'events':events}

@app.post('/editorial/api/requests')
async def add_request(request:Request):
    who=await actor(request);data=await body(request)
    query=str(data.get('query','')).strip();note=str(data.get('note','')).strip()
    mode=data.get('price_mode','hide');price=data.get('price')
    if not query or len(query)>500 or len(note)>3000 or mode not in ('hide','catalogue','custom'):raise Conflict('Demande invalide.')
    if mode=='custom':
        try:
            price=float(price)
            if not 0<price<100000:raise ValueError()
        except (TypeError,ValueError):raise Conflict('Indiquez un prix TTC positif.')
    else:price=None
    with store.db() as db:
        if db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0]>=50:raise Conflict('La file contient déjà cinquante demandes.')
        id=uid();db.execute('INSERT INTO requests(id,query,note,price_mode,price,priority,created) VALUES(?,?,?,?,?,?,?)',(id,query,note,mode,price,1 if data.get('priority') in ('high',1) else 0,now()));store.event(db,'Demande de mise en avant ajoutée.',who)
    return {'id':id}

@app.get('/editorial/api/contents')
async def contents(request:Request,q:str=Query('',max_length=1000),filter:str='all',offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=1000)):
    await actor(request)
    return list_contents(store,q=q,filter=filter,offset=offset,limit=limit)

@app.get('/editorial/api/contents/{id}')
async def content(id:str,request:Request):
    await actor(request)
    return content_detail(store,id)

@app.get('/editorial/api/strategy')
async def strategy_context(request:Request):
    await actor(request)
    return strategy.context()

@app.post('/editorial/api/strategy/watch')
@app.post('/editorial/api/strategy/report')
async def strategy_refresh(request:Request):
    await actor(request);data=await body(request)
    return strategy.queue('watch' if request.url.path.endswith('/watch') else 'performance',data.get('request_id'))

@app.post('/editorial/api/strategy/ideas/{id}/prepare')
async def strategy_idea(id:str,request:Request):
    await actor(request);data=await body(request)
    return await asyncio.to_thread(strategy.prepare_idea,id,data.get('request_id'),data.get('create_blog',False),data.get('scheduled_at'))

@app.post('/editorial/api/strategy/campaigns')
async def strategy_campaign(request:Request):
    await actor(request);data=await body(request)
    return strategy.create_campaign(data.get('request_id'),data.get('brief'),data.get('start_date'),data.get('end_date'),data.get('post_count',3),data.get('create_blog',True))

@app.post('/editorial/api/strategy/campaigns/{id}/prepare')
async def strategy_campaign_prepare(id:str,request:Request):
    await actor(request);data=await body(request)
    return strategy.prepare_campaign(id,data.get('revision'),data.get('request_id'))

@app.post('/editorial/api/strategy/campaigns/{id}/retry')
async def strategy_campaign_retry(id:str,request:Request):
    await actor(request);data=await body(request)
    return strategy.retry_campaign(id,data.get('revision'),data.get('request_id'))

@app.post('/editorial/api/prepare')
async def prepare(request:Request):
    await actor(request);await body(request)
    return {'id':store.prepare()}

@app.post('/editorial/api/pause')
async def pause(request:Request):
    who=await actor(request);data=await body(request)
    if type(data.get('paused')) is not bool:raise Conflict('Choisissez pause ou reprise.')
    with store.db() as db:
        db.execute("UPDATE settings SET value=? WHERE key='paused'",('true' if data['paused'] else 'false',));store.event(db,'Préparation et publication suspendues.' if data['paused'] else 'Préparation et publication reprises.',who)
    return {'ok':True}

@app.post('/editorial/api/weeks/{id}/subjects/{slot}/revise')
async def revise_subject(id:str,slot:int,request:Request):
    who=await actor(request);data=await body(request)
    return {'id':store.revise_subject(id,slot,data.get('revision'),data.get('instruction',''),data.get('request_id'),who)}

@app.post('/editorial/api/weeks/{id}/save')
@app.post('/editorial/api/weeks/{id}/approve')
async def plan_action(id:str,request:Request):
    who=await actor(request);data=await body(request)
    approve=request.url.path.endswith('/approve')
    with store.db() as db:
        row=db.execute('SELECT * FROM weeks WHERE id=?',(id,)).fetchone()
        if not row:raise Conflict('Plan introuvable.')
        week=dict(row)
        if week['revision']!=data.get('revision') or week['status']!='plan_review':raise Conflict('Ce plan a changé ou est déjà en production.')
        plan=json.loads(week['plan'])
        if not approve:
            updated=validate_plan(data.get('plan'),plan['products'],week['week'])
            for subject in updated['subjects']+[updated['article']]:subject['scheduled_at']=date(subject['scheduled_at'])
            plan.update(updated)
            db.execute('UPDATE weeks SET plan=?,revision=revision+1 WHERE id=?',(dumps(plan),id));store.event(db,'Plan modifié, en attente de validation.',who)
        else:
            for brief in plan['subjects']+[plan['article']]:
                if datetime.fromisoformat(date(brief['scheduled_at']))<=datetime.now(timezone.utc):raise Conflict('Le plan contient une date passée. Corrigez-la avant validation.')
            for kind,slot,brief in [('social',s['slot'],s) for s in plan['subjects']]+[('blog',0,plan['article'])]:
                item_id=uid();db.execute('INSERT INTO items(id,week_id,kind,slot,scheduled_at) VALUES(?,?,?,?,?)',(item_id,id,kind,slot,date(brief['scheduled_at'])));store.job(db,'draft',item_id)
            db.execute("UPDATE weeks SET status='generating' WHERE id=?",(id,));store.event(db,'Plan approuvé : rédaction lancée. Les contenus finis devront être approuvés séparément.',who)
    return {'ok':True}

@app.post('/editorial/api/weeks/{id}/retry')
async def retry_week(id:str,request:Request):
    who=await actor(request);data=await body(request)
    with store.db() as db:
        row=db.execute('SELECT * FROM weeks WHERE id=?',(id,)).fetchone()
        if not row or row['status']!='failed' or row['revision']!=data.get('revision') or db.execute('SELECT 1 FROM items WHERE week_id=?',(id,)).fetchone():raise Conflict('Ce plan ne peut pas être repris.')
        db.execute("UPDATE requests SET status='pending',week_id=NULL WHERE week_id=?",(id,))
        db.execute("UPDATE weeks SET status='preparing',revision=revision+1,error=NULL WHERE id=?",(id,))
        db.execute("DELETE FROM jobs WHERE kind='plan' AND target=?",(id,));store.job(db,'plan',id);store.event(db,'Préparation du plan relancée.',who)
    return {'ok':True}

@app.post('/editorial/api/items/{id}/save')
@app.post('/editorial/api/items/{id}/approve')
@app.post('/editorial/api/items/{id}/reject')
@app.post('/editorial/api/items/{id}/retry')
async def item_action(id:str,request:Request):
    who=await actor(request);data=await body(request);action=request.url.path.rsplit('/',1)[-1]
    if action=='save':
        item=store.item(id)
        store.save_item(id,data.get('revision'),editable_content(data.get('content',{}),item),date(data.get('scheduled_at')),who)
    elif action=='approve':
        item=store.item(id);editable_content(item['content'],item)
        with store.db() as db:
            demand=db.execute('SELECT 1 FROM demand_items WHERE item_id=?',(id,)).fetchone()
        if demand and item['kind']=='social':
            occupied=await asyncio.to_thread(calendar_times)
            with store.db() as db:
                proposed=available_slot(item['scheduled_at'],occupied+reservations(db,id))
                if proposed!=item['scheduled_at']:
                    label=datetime.fromisoformat(proposed).astimezone(PARIS).strftime('%d/%m à %H:%M')
                    raise Conflict('Ce créneau est trop proche d’un autre sujet. Enregistrez un nouvel horaire, par exemple le '+label+' (Paris), puis validez.')
        # The authenticated approval click includes the owner's standing media confirmation.
        store.approve_item(id,data.get('revision'),who,True,data.get('create_blog',False))
    else:
        with store.db() as db:
            item=store.item(id,db);store.check_revision(item,data.get('revision'))
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(id,)).fetchone():raise Conflict('Une livraison existe : vérifiez Postiz avant toute nouvelle tentative.')
            if item['status'] not in ('review','approved','rejected','failed','blocked'):raise Conflict('Cette opération est indisponible pendant le traitement.')
            if action=='reject':
                item['content']['_feedback']=str(data.get('note','À revoir'))[:2000]
                db.execute('UPDATE items SET content=? WHERE id=?',(dumps(item['content']),id))
                db.execute("UPDATE items SET status='rejected',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=? WHERE id=?",(str(data.get('note','À revoir'))[:1000],id));store.event(db,'Contenu renvoyé en correction.',who)
            else:
                # Explicit retry may replace text and media; always revoke approval.
                store.snapshot(db,item)
                db.execute("UPDATE items SET status='queued',revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL,media='{}' WHERE id=?",(id,))
                db.execute("DELETE FROM jobs WHERE target=?",(id,));store.job(db,'demand' if db.execute('SELECT 1 FROM demand_items WHERE item_id=?',(id,)).fetchone() else 'draft',id);store.event(db,'Nouvelle proposition demandée ; validation annulée.',who)
    return {'ok':True}

@app.get('/editorial/media/{name}')
async def media(name:str,request:Request):
    await actor(request)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',name):raise HTTPException(404)
    path=store.root/'media'/name
    if not path.is_file() or path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise HTTPException(404)
    return FileResponse(path)

@app.get('/editorial/public/articles')
def articles():return {'articles':store.public_articles()}

@app.get('/editorial/public/media/{name}')
def public_media(name:str):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or not any(p.get('imageUrl','').endswith('/'+name) for p in store.public_articles()):raise HTTPException(404)
    path=store.root/'media'/name
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path)

async def binary_body(request,limit):
    if request.headers.get('origin')!=os.environ['PUBLIC_URL'].rstrip('/') or request.headers.get('x-editorial-action')!='1':raise HTTPException(403,'Origine de la demande refusée.')
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>limit:raise HTTPException(413,'Fichier trop volumineux.')
        chunks.append(chunk)
    if not size:raise HTTPException(400,'Fichier vide.')
    return b''.join(chunks)

@app.get('/editorial/api/conversations')
async def conversations(request:Request):
    who=await actor(request)
    with store.db() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM conversations ORDER BY created DESC LIMIT 100')]
    return {'conversations':rows,'voice':bool(os.environ.get('TRANSCRIPTION_URL')),'spacing_minutes':120,'owner_id':who}

@app.post('/editorial/api/conversations')
async def new_conversation(request:Request):
    await actor(request);await body(request)
    return {'id':conversation.create()}

@app.get('/editorial/api/conversations/{id}')
async def get_conversation(id:str,request:Request):
    await actor(request)
    with store.db() as db:
        conversation.require(db,id)
        messages=[]
        for row in db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY created',(id,)):
            msg=dict(row);msg['attachments']=json.loads(msg['attachments']);msg['proposals']=json.loads(msg['proposals'])
            msg['accepted']={str(i):r[0] for i in range(len(msg['proposals'])) if (r:=db.execute('SELECT value FROM settings WHERE key=?',('accepted:'+msg['id']+':'+str(i),)).fetchone())}
            messages.append(msg)
        photos=[{**dict(r),'url':'/editorial/media/'+r['filename']} for r in db.execute('SELECT id,name,filename FROM chat_photos WHERE conversation_id=?',(id,))]
        items=[]
        for row in db.execute('SELECT item_id FROM demand_items WHERE conversation_id=? ORDER BY rowid',(id,)):
            item=store.item(row[0],db)
            for key,field in [('media','media_url'),('blog_media','blog_media_url'),('source_media','source_media_url'),('source_media_2','source_media_2_url'),('source_media_3','source_media_3_url')]:
                item[field]='/editorial/media/'+item['media'][key] if item['media'].get(key) else None
            item['deliveries']=[{**dict(r),'result':json.loads(r['result'])} for r in db.execute('SELECT * FROM deliveries WHERE item_id=?',(item['id'],))]
            items.append(item)
    return {'messages':messages,'photos':photos,'items':items}

@app.post('/editorial/api/conversations/{id}/messages')
async def send_message(id:str,request:Request):
    who=await actor(request);data=await body(request)
    return {'id':conversation.send(id,data,who)}

@app.post('/editorial/api/conversations/{id}/photos')
async def add_photo(id:str,request:Request):
    await actor(request)
    data=await binary_body(request,12*1024*1024)
    from urllib.parse import unquote
    try:return await asyncio.to_thread(conversation.photo,id,data,unquote(request.headers.get('x-file-name','Photo produit')))
    except MediaBlocked as exc:raise Conflict(str(exc))

@app.post('/editorial/api/conversations/{id}/proposals/{message_id}')
async def prepare_proposal(id:str,message_id:str,request:Request):
    who=await actor(request);data=await body(request)
    # Calendar reads happen outside the write transaction; local reservations are
    # then rechecked under the transaction to serialize simultaneous requests.
    with store.db() as db:
        message=db.execute('SELECT proposals,target FROM messages WHERE id=? AND conversation_id=?',(message_id,id)).fetchone()
        index=data.get('index')
        proposals=json.loads(message['proposals']) if message else []
        if type(index) is not int or not 0<=index<len(proposals):raise Conflict('Proposition introuvable.')
        kind=store.item(message['target'],db)['kind'] if message['target'] else proposals[index].get('format','social')
    occupied=await asyncio.to_thread(calendar_times) if kind=='social' else []
    return {'id':conversation.accept(id,message_id,data,who,occupied)}

@app.post('/editorial/api/conversations/{id}/retry/{message_id}')
async def retry_message(id:str,message_id:str,request:Request):
    await actor(request);await body(request)
    with store.db() as db:
        if not db.execute("SELECT 1 FROM messages WHERE id=? AND conversation_id=? AND role='user' AND status='failed'",(message_id,id)).fetchone():raise Conflict('Ce message ne peut pas être relancé.')
        if db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND status IN ('queued','running')",(id,)).fetchone():raise Conflict('Une réponse est déjà en cours.')
        db.execute("UPDATE messages SET status='queued',error=NULL WHERE id=?",(message_id,))
        db.execute("DELETE FROM jobs WHERE kind='chat' AND target=?",(message_id,));store.job(db,'chat',message_id)
    return {'ok':True}

@app.post('/editorial/api/transcribe')
async def transcribe(request:Request):
    await actor(request)
    data=await binary_body(request,12*1024*1024)
    url=os.environ.get('TRANSCRIPTION_URL')
    if not url:raise Conflict('La dictée est momentanément indisponible. Vous pouvez écrire votre brief.')
    def invoke():
        try:
            response=requests.post(url.rstrip('/')+'/transcribe',data=data,headers={'Authorization':'Bearer '+os.environ['CODEX_BRIDGE_TOKEN'],'Content-Type':'application/octet-stream'},timeout=180)
            if response.status_code==429:raise Conflict('Une transcription est déjà en cours. Réessayez dans un instant.')
            if response.status_code==422:raise Conflict('Audio illisible ou trop long. Dictez un message de moins de trois minutes.')
            if response.status_code!=200:raise Conflict('La transcription est indisponible. Votre message n’a pas été envoyé à l’IA.')
            text=response.json().get('text','')
            if not isinstance(text,str) or len(text)>6000:raise ValueError()
            return {'text':text}
        except requests.RequestException:raise Conflict('La transcription a pris trop de temps. Réessayez avec un message plus court.')
        except ValueError:raise Conflict('Réponse de transcription invalide.')
    return await asyncio.to_thread(invoke)


@app.get('/editorial/connect')
def connect_page():return FileResponse(ROOT/'static'/'connect.html')

@app.get('/editorial/api/agent-connection')
async def agent_connection(request:Request):
    await actor(request)
    return {**agent_service.token_status(),'url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/agent/mcp','instructions':INSTRUCTIONS}

@app.post('/editorial/api/agent-connection')
async def change_agent_connection(request:Request):
    who=await actor(request);data=await body(request)
    if data.get('action')=='rotate':return {'token':agent_service.rotate(who)}
    if data.get('action')=='revoke':agent_service.revoke(who);return {'ok':True}
    raise Conflict('Action inconnue.')

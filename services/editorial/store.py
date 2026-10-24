import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

PARIS = ZoneInfo('Europe/Paris')
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid.uuid4())
def dumps(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))
def digest(value): return hashlib.sha256(dumps(value).encode()).hexdigest()
def monday_next(value=None):
    value = (value or datetime.now(timezone.utc)).astimezone(PARIS)
    return (value.date() + timedelta(days=7-value.weekday())).isoformat()
def planned_date(week, day, hour=12):
    d = datetime.fromisoformat(week).replace(tzinfo=PARIS) + timedelta(days=day, hours=hour)
    return d.astimezone(timezone.utc).isoformat()

class Conflict(ValueError): pass

class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path = self.root / 'editorial.sqlite3'
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS weeks (id TEXT PRIMARY KEY, week TEXT UNIQUE NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, plan TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, error TEXT);
            CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, week_id TEXT NOT NULL, kind TEXT NOT NULL, slot INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued', revision INTEGER NOT NULL DEFAULT 1, content TEXT NOT NULL DEFAULT '{}', media TEXT NOT NULL DEFAULT '{}', scheduled_at TEXT NOT NULL, approval_hash TEXT, approved_by TEXT, approved_at TEXT, error TEXT, UNIQUE(week_id,kind,slot));
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, query TEXT NOT NULL, note TEXT NOT NULL, price_mode TEXT NOT NULL, price TEXT, priority INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', week_id TEXT, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL, UNIQUE(kind,target));
            CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, item_id TEXT NOT NULL, revision INTEGER NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', updated TEXT NOT NULL, UNIQUE(item_id,revision,channel));
            CREATE TABLE IF NOT EXISTS plan_changes (id TEXT PRIMARY KEY, week_id TEXT NOT NULL, slot INTEGER NOT NULL, revision INTEGER NOT NULL, instruction TEXT NOT NULL, request_id TEXT, status TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, message TEXT NOT NULL, actor TEXT);
            CREATE TABLE IF NOT EXISTS published (slug TEXT PRIMARY KEY, item_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (item_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(item_id,revision));
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL, attachments TEXT NOT NULL DEFAULT '[]', target TEXT, target_revision INTEGER, status TEXT NOT NULL, proposals TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL, error TEXT, UNIQUE(conversation_id,id));
            CREATE TABLE IF NOT EXISTS chat_photos (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, name TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS visual_directions (item_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(item_id,revision));
            CREATE TABLE IF NOT EXISTS companion_articles (parent_id TEXT PRIMARY KEY, article_id TEXT UNIQUE NOT NULL, parent_revision INTEGER NOT NULL, parent_hash TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL, article_revision INTEGER NOT NULL, state TEXT NOT NULL, auto_hash TEXT, source_snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS demand_items (item_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, proposal_index INTEGER NOT NULL, brief TEXT NOT NULL, product TEXT, UNIQUE(message_id,proposal_index));
            ''')
            if 'blog_requested' not in {r[1] for r in db.execute('PRAGMA table_info(items)')}:
                db.execute('ALTER TABLE items ADD COLUMN blog_requested INTEGER NOT NULL DEFAULT 0')
            db.execute("INSERT OR IGNORE INTO settings VALUES ('paused','false')")
        os.chmod(self.path, 0o600)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path, timeout=20)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()
    def event(self, db, message, actor=None): db.execute('INSERT INTO events(created,message,actor) VALUES(?,?,?)',(now(),message,actor))
    def job(self, db, kind, target): db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,'queued',0,?)",(uid(),kind,target,now()))
    def paused(self):
        with self.db() as db: return db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true'
    def prepare(self, week=None):
        week=week or monday_next()
        with self.db() as db:
            old=db.execute('SELECT id FROM weeks WHERE week=?',(week,)).fetchone()
            if old:return old[0]
            id=uid()
            db.execute("INSERT INTO weeks(id,week,status,created) VALUES(?,?,'preparing',?)",(id,week,now()))
            self.job(db,'plan',id); self.event(db,'Préparation du plan de la semaine du '+week)
            return id
    def revise_subject(self, week_id, slot, revision, instruction, request_id, actor):
        if type(slot) is not int or not 0<=slot<=6:raise Conflict('Créneau invalide.')
        if not isinstance(instruction,str) or len(instruction)>3000:raise Conflict('Consigne invalide.')
        if request_id is not None and (not isinstance(request_id,str) or len(request_id)>100):raise Conflict('Demande produit invalide.')
        instruction=instruction.strip()
        if not instruction and not request_id:raise Conflict('Indiquez une consigne ou choisissez une demande produit.')
        with self.db() as db:
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week_id,)).fetchone()
            if not row or row['revision']!=revision or row['status']!='plan_review':raise Conflict('Ce plan a changé ou est déjà en production.')
            if db.execute('SELECT 1 FROM items WHERE week_id=?',(week_id,)).fetchone():raise Conflict('Modifiez le contenu individuel déjà rédigé.')
            if request_id and not db.execute("SELECT 1 FROM requests WHERE id=? AND status='pending'",(request_id,)).fetchone():raise Conflict('Cette demande produit n’est plus en attente.')
            if request_id and db.execute("SELECT 1 FROM plan_changes WHERE request_id=? AND status='queued'",(request_id,)).fetchone():raise Conflict('Cette demande est déjà en cours de traitement.')
            id=uid()
            db.execute("INSERT INTO plan_changes VALUES(?,?,?,?,?,?,'queued',?)",(id,week_id,slot,revision,instruction,request_id,now()))
            db.execute("UPDATE weeks SET status='revising',error=NULL WHERE id=?",(week_id,))
            self.job(db,'revise',id)
            self.event(db,'Modification demandée pour le post '+str(slot+1)+' uniquement.',actor)
            return id
    def fail_revision(self, db, change_id, message):
        row=db.execute('SELECT * FROM plan_changes WHERE id=?',(change_id,)).fetchone()
        if row:
            db.execute("UPDATE plan_changes SET status='failed' WHERE id=?",(change_id,))
            db.execute("UPDATE weeks SET status='plan_review',error=? WHERE id=? AND revision=? AND status='revising'",(message,row['week_id'],row['revision']))
    def item(self, id, db=None):
        if db is None:
            with self.db() as conn:return self.item(id,conn)
        row=db.execute('SELECT * FROM items WHERE id=?',(id,)).fetchone()
        if not row: raise Conflict('Contenu introuvable.')
        r=dict(row);r['blog_requested']=bool(r['blog_requested']);r['content']=json.loads(r['content']);r['media']=json.loads(r['media'])
        linked=db.execute('SELECT a.article_id,a.state,i.status,i.error,d.conversation_id FROM companion_articles a JOIN items i ON i.id=a.article_id JOIN demand_items d ON d.item_id=i.id WHERE a.parent_id=?',(id,)).fetchone()
        r['companion_article']=dict(linked) if linked else None
        grant=db.execute('SELECT parent_id,state,auto_hash FROM companion_articles WHERE article_id=?',(id,)).fetchone()
        r['derived_from_post']=dict(grant) if grant else None
        if r['derived_from_post']:r['derived_from_post'].pop('auto_hash',None)
        return r
    def content_hash(self, item):
        return digest({k:item[k] for k in ('id','revision','kind','content','media','scheduled_at')})
    def check_revision(self,item,revision):
        if item['revision']!=revision:raise Conflict('Ce contenu a changé. Rechargez avant de valider.')
    def snapshot(self,db,item):
        db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)',(item['id'],item['revision'],dumps(item),now()))
    def save_item(self,id,revision,content,scheduled_at,actor):
        with self.db() as db:
            item=self.item(id,db);self.check_revision(item,revision)
            if item['status'] not in ('review','approved','rejected','blocked','failed'):raise Conflict('Ce contenu ne peut pas être modifié actuellement.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status NOT IN ('failed')",(id,)).fetchone():raise Conflict('Une livraison existe déjà : réconciliation nécessaire avant modification.')
            self.snapshot(db,item)
            # Price and product identity are controlled by the approved plan, not the model/editor JSON.
            allowed=('title','facebook','instagram','markdown','excerpt','slug','category','headline','alt','sources','editorial_notes')
            merged={**item['content'],**{k:v for k,v in content.items() if k in allowed}}
            changed_visual=any(merged.get(k)!=item['content'].get(k) for k in ('headline','title'))
            media=item['media']
            status='queued' if changed_visual else 'review'
            if changed_visual:media={}
            db.execute('UPDATE items SET content=?,media=?,scheduled_at=?,revision=revision+1,status=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?',(dumps(merged),dumps(media),scheduled_at,status,id))
            if changed_visual:
                db.execute("DELETE FROM jobs WHERE kind='render' AND target=?",(id,));self.job(db,'render',id)
            self.event(db,'Contenu modifié ; validation précédente annulée.',actor)
    def approve_item(self,id,revision,actor,media_reviewed,create_blog=False,*,db=None):
        if type(create_blog) is not bool:raise Conflict('Option article invalide.')
        if media_reviewed is not True:raise Conflict('Vérifiez le visuel, la fidélité du produit et les droits des photos avant validation.')
        with (self.db() if db is None else nullcontext(db)) as db:
            item=self.item(id,db);self.check_revision(item,revision)
            if item['status']!='review' or not item['media'].get('media'):raise Conflict('Le contenu et son visuel doivent être prêts à relire.')
            if datetime.fromisoformat(item['scheduled_at']) <= datetime.now(timezone.utc)+timedelta(minutes=5):raise Conflict('Choisissez une date au moins cinq minutes dans le futur.')
            db.execute('UPDATE items SET blog_requested=? WHERE id=?',(int(create_blog),id))
            approval=self.content_hash(item)
            db.execute("UPDATE items SET status='approved',approval_hash=?,approved_by=?,approved_at=?,error=NULL WHERE id=?",(approval,actor,now(),id))
            # A direct owner approval supersedes any previous automatic article seal.
            db.execute('UPDATE companion_articles SET auto_hash=NULL WHERE article_id=?',(id,))
            if item['kind']=='social' or create_blog:
                from companion import authorize
                authorize(self,db,self.item(id,db),actor,create_blog)
            self.snapshot(db,self.item(id,db));self.event(db,'Version approuvée pour publication à la date affichée.',actor)
    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET status=CASE WHEN attempts<2 THEN 'queued' ELSE 'failed' END,updated=? WHERE status='running'",(now(),))
            db.execute("UPDATE messages SET status=(SELECT status FROM jobs WHERE kind='chat' AND target=messages.id),error='Réponse interrompue ; réessayez si nécessaire.' WHERE status IN ('running','queued') AND EXISTS(SELECT 1 FROM jobs WHERE kind='chat' AND target=messages.id)")
            db.execute("UPDATE items SET status='failed',error='Préparation interrompue. Vous pouvez la relancer.' WHERE status IN ('generating','rendering') AND EXISTS(SELECT 1 FROM jobs WHERE target=items.id AND status='failed')")
            for row in db.execute("SELECT target FROM jobs WHERE kind='revise' AND status='failed'").fetchall():
                self.fail_revision(db,row[0],'Modification interrompue. Le plan initial est conservé ; vous pouvez réessayer.')
            db.execute("UPDATE items SET status='blocked',error='Envoi interrompu : vérifier dans Postiz avant toute nouvelle tentative.' WHERE status='publishing'")
            db.execute("UPDATE deliveries SET status='uncertain' WHERE status='sending'")
    def public_articles(self):
        with self.db() as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM published ORDER BY slug')]

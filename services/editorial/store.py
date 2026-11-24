import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

PARIS = ZoneInfo('Europe/Paris')
EXTERNAL_VISUAL_WARNING = 'Le titre a changé ; vérifiez que le texte éventuellement incrusté dans le visuel fourni reste cohérent.'
VISUAL_TEMPLATES = ('classic', 'minimal', 'raw', 'tip_card')
DEFAULT_EDITORIAL_RULES = {
    'custom_instructions': '',
    'default_template': 'auto',
    'weekly_blog_link': True,
    'signature_note': 'Planète Laser · Forbach (Moselle-Est) — conseil, essai en magasin et prix du web depuis 1989.',
}


def visual_edit_requires_render(item, updated):
    """Preserve a supplied finished visual and flag potential title mismatch."""
    media = item['media']
    has_visual = bool(media.get('media'))
    changed_title = any(updated.get(key) != item['content'].get(key) for key in ('headline', 'title'))
    changed_template = (updated.get('template') or 'classic') != (item['content'].get('template') or 'classic')
    changed_slides = (updated.get('carousel_slides') or []) != (item['content'].get('carousel_slides') or [])
    supplied = has_visual and (media.get('provenance') or {}).get('image_mode') == 'agent-supplied-final'
    previous_notes = item['content'].get('editorial_notes') or []
    if supplied and (changed_title or EXTERNAL_VISUAL_WARNING in previous_notes):
        notes = updated.get('editorial_notes') or []
        if not isinstance(notes, list):notes = []
        if EXTERNAL_VISUAL_WARNING not in notes:notes = [*notes, EXTERNAL_VISUAL_WARNING]
        updated['editorial_notes'] = notes
    return not has_visual or ((changed_title or changed_template or changed_slides) and not supplied)


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
            CREATE TABLE IF NOT EXISTS store_scenes (id TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', filename TEXT NOT NULL, sha256 TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, actor TEXT);
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
    def revise_subject(self, week_id, slot, revision, instruction, request_id, actor, *, db=None):
        if type(slot) is not int or not 0<=slot<=6:raise Conflict('Créneau invalide.')
        if not isinstance(instruction,str) or len(instruction)>3000:raise Conflict('Consigne invalide.')
        if request_id is not None and (not isinstance(request_id,str) or len(request_id)>100):raise Conflict('Demande produit invalide.')
        instruction=instruction.strip()
        if not instruction and not request_id:raise Conflict('Indiquez une consigne ou choisissez une demande produit.')
        with (self.db() if db is None else nullcontext(db)) as db:
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
            allowed=('title','facebook','instagram','markdown','excerpt','slug','category','headline','alt','sources','editorial_notes','seo_title','seo_description','tags','template','carousel_slides','visual_instructions')
            merged={**item['content'],**{k:v for k,v in content.items() if k in allowed}}
            full_payload=('markdown' in content) or ('facebook' in content and 'instagram' in content)
            for opt in ('seo_title','seo_description','tags','carousel_slides','visual_instructions'):
                if (opt in content and not content[opt]) or (full_payload and opt not in content):
                    merged.pop(opt,None)
            changed_visual=visual_edit_requires_render(item,merged)
            media=item['media']
            status='queued' if changed_visual else 'review'
            if changed_visual:media={}
            db.execute('UPDATE items SET content=?,media=?,scheduled_at=?,revision=revision+1,status=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?',(dumps(merged),dumps(media),scheduled_at,status,id))
            if changed_visual:
                demand=db.execute('SELECT product FROM demand_items WHERE item_id=?',(id,)).fetchone()
                job_kind='demand_render' if demand and not demand['product'] else 'render'
                db.execute("DELETE FROM jobs WHERE kind IN ('render','demand_render') AND target=?",(id,));self.job(db,job_kind,id)
            self.event(db,'Contenu modifié ; validation précédente annulée.',actor)
    def get_rules(self, db=None):
        if db is None:
            with self.db() as conn:return self.get_rules(conn)
        row=db.execute("SELECT value FROM settings WHERE key='editorial_rules'").fetchone()
        stored=json.loads(row[0]) if row else {}
        if not isinstance(stored,dict):stored={}
        return {**DEFAULT_EDITORIAL_RULES,**{k:v for k,v in stored.items() if k in DEFAULT_EDITORIAL_RULES}}
    def save_rules(self, data, actor):
        if not isinstance(data,dict):raise Conflict('Règles invalides.')
        with self.db() as db:
            current=self.get_rules(db)
            custom=data.get('custom_instructions',current['custom_instructions'])
            if not isinstance(custom,str) or len(custom)>8000:raise Conflict('Consignes personnalisées invalides (8 000 caractères maximum).')
            template=data.get('default_template',current['default_template'])
            if template not in (*VISUAL_TEMPLATES,'auto'):raise Conflict('Gabarit visuel par défaut inconnu.')
            weekly_blog=data.get('weekly_blog_link',current['weekly_blog_link'])
            if type(weekly_blog) is not bool:raise Conflict('Option article hebdomadaire invalide.')
            signature=data.get('signature_note',current['signature_note'])
            if not isinstance(signature,str) or len(signature)>500:raise Conflict('Signature magasin invalide (500 caractères maximum).')
            updated={
                'custom_instructions':custom.strip(),
                'default_template':template,
                'weekly_blog_link':weekly_blog,
                'signature_note':signature.strip(),
            }
            db.execute("INSERT OR REPLACE INTO settings VALUES('editorial_rules',?)",(dumps(updated),))
            self.event(db,'Règles éditoriales mises à jour.',actor)
            return updated
    def add_request(self, query, note='', price_mode='hide', price=None, priority='normal', actor='owner', *, db=None):
        query=str(query or '').strip();note=str(note or '').strip()
        mode=price_mode or 'hide'
        if not query or len(query)>500 or len(note)>3000 or mode not in ('hide','catalogue','custom'):
            raise Conflict('Demande invalide.')
        if mode=='custom':
            try:
                price=float(price)
                if not 0<price<100000:raise ValueError()
            except (TypeError,ValueError):raise Conflict('Indiquez un prix TTC positif.')
        else:price=None
        prio=1 if priority in ('high',1,True) else 0
        with (self.db() if db is None else nullcontext(db)) as db:
            if db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0]>=50:
                raise Conflict('La file contient déjà cinquante demandes.')
            identifier=uid()
            db.execute('INSERT INTO requests(id,query,note,price_mode,price,priority,created) VALUES(?,?,?,?,?,?,?)',(identifier,query,note,mode,price,prio,now()))
            self.event(db,'Demande de mise en avant ajoutée.',actor)
        return identifier
    def delete_request(self, request_id, actor='owner', *, db=None):
        with (self.db() if db is None else nullcontext(db)) as db:
            row=db.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
            if not row:raise Conflict('Demande introuvable.')
            if row['status']!='pending':raise Conflict('Seule une demande en attente peut être supprimée.')
            if db.execute("SELECT 1 FROM plan_changes WHERE request_id=? AND status='queued'",(request_id,)).fetchone():
                raise Conflict('Cette demande est en cours de traitement dans un plan.')
            db.execute('DELETE FROM requests WHERE id=?',(request_id,))
            self.event(db,'Demande produit supprimée : '+row['query'][:80],actor)
    def save_week(self, week_id, revision, plan_data, actor='owner', *, db=None):
        from generation import validate_plan
        def utc_iso(value):
            try:
                d=datetime.fromisoformat(value.replace('Z','+00:00'))
                if not d.tzinfo:raise ValueError()
                return d.astimezone(timezone.utc).isoformat()
            except (ValueError,AttributeError):raise Conflict('La date doit comporter un fuseau horaire.')
        with (self.db() if db is None else nullcontext(db)) as db:
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week_id,)).fetchone()
            if not row:raise Conflict('Plan introuvable.')
            week=dict(row)
            if week['revision']!=revision or week['status']!='plan_review':
                raise Conflict('Ce plan a changé ou est déjà en production.')
            plan=json.loads(week['plan'])
            updated=validate_plan(plan_data,plan['products'],week['week'])
            for subject in updated['subjects']+[updated['article']]:
                subject['scheduled_at']=utc_iso(subject['scheduled_at'])
            plan.update(updated)
            db.execute('UPDATE weeks SET plan=?,revision=revision+1 WHERE id=?',(dumps(plan),week_id))
            self.event(db,'Plan modifié, en attente de validation.',actor)
            return {'week_id':week_id,'revision':week['revision']+1,'status':'plan_review','plan':plan}
    def approve_week(self, week_id, revision, actor='owner', *, db=None):
        def utc_iso(value):
            try:
                d=datetime.fromisoformat(value.replace('Z','+00:00'))
                if not d.tzinfo:raise ValueError()
                return d.astimezone(timezone.utc).isoformat()
            except (ValueError,AttributeError):raise Conflict('La date doit comporter un fuseau horaire.')
        with (self.db() if db is None else nullcontext(db)) as db:
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week_id,)).fetchone()
            if not row:raise Conflict('Plan introuvable.')
            week=dict(row)
            if week['revision']!=revision or week['status']!='plan_review':
                raise Conflict('Ce plan a changé ou est déjà en production.')
            if db.execute('SELECT 1 FROM items WHERE week_id=?',(week_id,)).fetchone():
                raise Conflict('Les contenus de ce plan sont déjà créés.')
            plan=json.loads(week['plan'])
            for brief in plan['subjects']+[plan['article']]:
                if datetime.fromisoformat(utc_iso(brief['scheduled_at']))<=datetime.now(timezone.utc):
                    raise Conflict('Le plan contient une date passée. Corrigez-la avant validation.')
            item_ids=[]
            for kind,slot,brief in [('social',s['slot'],s) for s in plan['subjects']]+[('blog',0,plan['article'])]:
                item_id=uid()
                db.execute('INSERT INTO items(id,week_id,kind,slot,scheduled_at) VALUES(?,?,?,?,?)',(item_id,week_id,kind,slot,utc_iso(brief['scheduled_at'])))
                self.job(db,'draft',item_id)
                item_ids.append(item_id)
            db.execute("UPDATE weeks SET status='generating' WHERE id=?",(week_id,))
            self.event(db,'Plan approuvé : rédaction lancée. Les contenus finis devront être approuvés séparément.',actor)
            return {'week_id':week_id,'status':'generating','item_ids':item_ids}
    def retry_week(self, week_id, revision, actor='owner', *, db=None):
        with (self.db() if db is None else nullcontext(db)) as db:
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week_id,)).fetchone()
            if not row or row['status']!='failed' or row['revision']!=revision or db.execute('SELECT 1 FROM items WHERE week_id=?',(week_id,)).fetchone():
                raise Conflict('Ce plan ne peut pas être repris.')
            db.execute("UPDATE requests SET status='pending',week_id=NULL WHERE week_id=?",(week_id,))
            db.execute("UPDATE weeks SET status='preparing',revision=revision+1,error=NULL WHERE id=?",(week_id,))
            db.execute("DELETE FROM jobs WHERE kind='plan' AND target=?",(week_id,))
            self.job(db,'plan',week_id)
            self.event(db,'Préparation du plan relancée.',actor)
            return {'week_id':week_id,'revision':revision+1,'status':'preparing'}
    def delete_draft(self, item_id, revision, actor='owner', *, db=None):
        with (self.db() if db is None else nullcontext(db)) as db:
            item=self.item(item_id,db);self.check_revision(item,revision)
            if item['status'] not in ('review','rejected','failed','blocked','queued'):
                raise Conflict('Seul un brouillon non validé peut être supprimé.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():
                raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if db.execute('SELECT 1 FROM published WHERE item_id=?',(item_id,)).fetchone():
                raise Conflict('Un article déjà publié ne peut pas être supprimé.')
            if db.execute("SELECT 1 FROM jobs WHERE target=? AND status='running'",(item_id,)).fetchone():
                raise Conflict('Une génération est en cours sur ce brouillon ; attendez sa fin.')
            title=item['content'].get('title') or item_id
            db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
            db.execute('DELETE FROM demand_items WHERE item_id=?',(item_id,))
            db.execute('DELETE FROM visual_directions WHERE item_id=?',(item_id,))
            db.execute('DELETE FROM agent_previews WHERE item_id=?',(item_id,))
            db.execute('DELETE FROM companion_articles WHERE parent_id=? OR article_id=?',(item_id,item_id))
            db.execute('DELETE FROM items WHERE id=?',(item_id,))
            self.event(db,'Brouillon supprimé : '+str(title)[:100],actor)
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

    def update_published_article(self, identifier, revision, markdown=None, actor='owner', *,
                                 title=None, excerpt=None, seo_title=None, seo_description=None,
                                 category=None, tags=None, db=None):
        from generation import validate_content
        if (markdown is None and title is None and excerpt is None and seo_title is None
                and seo_description is None and category is None and tags is None):
            raise Conflict('Indiquez au moins un champ à mettre à jour.')
        with (self.db() if db is None else nullcontext(db)) as db:
            item = self.item(identifier, db)
            self.check_revision(item, revision)
            if item['kind'] != 'blog' or item['status'] != 'published':
                raise Conflict('Seuls les articles déjà publiés peuvent être mis à jour sur le site.')

            row = db.execute('SELECT body FROM published WHERE item_id=?', (identifier,)).fetchone()
            if row is None:
                raise Conflict('La version publique de cet article est introuvable.')
            public = json.loads(row['body'])

            new_content = dict(item['content'])
            new_public = dict(public)
            if markdown is not None:
                validate_content({'markdown': markdown}, 'blog')
                new_content['markdown'] = markdown
                new_public['content'] = markdown
            if title is not None:
                if not isinstance(title, str) or not title.strip() or len(title.strip()) > 220 or re.search(r'<[^>]+>', title):
                    raise Conflict('Titre invalide.')
                new_content['title'] = title.strip()
                new_public['title'] = title.strip()
            if excerpt is not None:
                if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt.strip()) > 1000 or re.search(r'<[^>]+>', excerpt):
                    raise Conflict('Introduction invalide.')
                new_content['excerpt'] = excerpt.strip()
                new_public['excerpt'] = excerpt.strip()
            if seo_title is not None:
                if not isinstance(seo_title, str) or len(seo_title.strip()) > 250 or re.search(r'<[^>]+>', seo_title):
                    raise Conflict('Titre SEO invalide.')
                cleaned = seo_title.strip()
                if cleaned:
                    new_content['seo_title'] = cleaned
                    new_public['seoTitle'] = cleaned
                else:
                    new_content.pop('seo_title', None)
                    new_public.pop('seoTitle', None)
            if seo_description is not None:
                if not isinstance(seo_description, str) or len(seo_description.strip()) > 1000 or re.search(r'<[^>]+>', seo_description):
                    raise Conflict('Meta description invalide.')
                cleaned = seo_description.strip()
                if cleaned:
                    new_content['seo_description'] = cleaned
                    new_public['seoDescription'] = cleaned
                else:
                    new_content.pop('seo_description', None)
                    new_public.pop('seoDescription', None)
            if category is not None:
                if category not in ('guides', 'actualites', 'produits'):
                    raise Conflict('Rubrique invalide.')
                new_content['category'] = category
                new_public['category'] = category
            if tags is not None:
                if (not isinstance(tags, list) or len(tags) > 20
                        or any(not isinstance(t, str) or not t.strip() or len(t.strip()) > 80 or re.search(r'<[^>]+>', t) for t in tags)):
                    raise Conflict('Étiquettes invalides.')
                cleaned_tags = list(dict.fromkeys(t.strip() for t in tags))
                new_content['tags'] = cleaned_tags
                new_public['tags'] = cleaned_tags

            if new_content == item['content'] and new_public == public:
                return

            self.snapshot(db, item)
            updated_at = now()
            updated = {
                **item,
                'content': new_content,
                'revision': revision + 1,
                'approved_by': actor,
                'approved_at': updated_at,
            }
            updated['approval_hash'] = self.content_hash(updated)
            db.execute('''UPDATE items SET content=?,revision=?,approval_hash=?,approved_by=?,approved_at=?
                          WHERE id=?''',
                       (dumps(updated['content']), updated['revision'], updated['approval_hash'],
                        actor, updated_at, identifier))
            new_public['updatedAt'] = updated_at
            db.execute('UPDATE published SET body=? WHERE item_id=?', (dumps(new_public), identifier))
            self.snapshot(db, updated)
            self.event(db, 'Article mis à jour sur le site : ' + new_public['slug'], actor)

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET status=CASE WHEN attempts<2 THEN 'queued' ELSE 'failed' END,updated=? WHERE status='running'",(now(),))
            db.execute("UPDATE messages SET status=(SELECT status FROM jobs WHERE kind='chat' AND target=messages.id),error='Réponse interrompue ; réessayez si nécessaire.' WHERE status IN ('running','queued') AND EXISTS(SELECT 1 FROM jobs WHERE kind='chat' AND target=messages.id)")
            db.execute("UPDATE items SET status='failed',error='Préparation interrompue. Vous pouvez la relancer.' WHERE status IN ('generating','rendering') AND EXISTS(SELECT 1 FROM jobs WHERE target=items.id AND status='failed')")
            db.execute("UPDATE weeks SET status='failed',error='Préparation interrompue. Vous pouvez la relancer.' WHERE status='preparing' AND EXISTS(SELECT 1 FROM jobs WHERE kind='plan' AND target=weeks.id AND status='failed')")
            for row in db.execute("SELECT target FROM jobs WHERE kind='revise' AND status='failed'").fetchall():
                self.fail_revision(db,row[0],'Modification interrompue. Le plan initial est conservé ; vous pouvez réessayer.')
            db.execute("UPDATE items SET status='blocked',error='Envoi interrompu : vérifier dans Postiz avant toute nouvelle tentative.' WHERE status='publishing'")
            db.execute("UPDATE deliveries SET status='uncertain' WHERE status='sending'")
    def public_articles(self):
        with self.db() as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM published ORDER BY slug')]

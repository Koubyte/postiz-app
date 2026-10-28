"""Private research, measurement and campaign plans; never publication authority."""
import json
import re
import threading
from datetime import datetime, timedelta, timezone, date

from store import Conflict, PARIS, now, uid, dumps, digest
from generation import GenerationError, bounded_text
from spacing import available_slot, reservations

JOBS = ('watch', 'performance', 'campaign_plan', 'campaign_draft')
CADENCE = {'watch': 'Chaque lundi et jeudi à 08:00 (Paris)', 'performance': 'Chaque lundi à 08:30 (Paris)'}

class Strategy:
    def __init__(self, store, generator, publisher, agent):
        self.store, self.generator, self.publisher, self.agent = store, generator, publisher, agent
        self._prepare_lock=threading.RLock()
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS strategy_runs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, error TEXT);
            CREATE TABLE IF NOT EXISTS watch_ideas (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL, item_id TEXT, receipt TEXT);
            CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, brief TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, post_count INTEGER NOT NULL, create_blog INTEGER NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, plan TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, error TEXT);
            CREATE TABLE IF NOT EXISTS campaign_items (campaign_id TEXT NOT NULL, slot INTEGER NOT NULL, item_id TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(campaign_id,slot));
            CREATE TABLE IF NOT EXISTS strategy_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
            ''')

    def replay(self, db, request_id, payload):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',request_id):
            raise Conflict('Identifiant de demande invalide. Rechargez puis réessayez.')
        fingerprint=digest(payload)
        old=db.execute('SELECT * FROM strategy_requests WHERE id=?',(request_id,)).fetchone()
        if old:
            if old['fingerprint']!=fingerprint:raise Conflict('Cette demande a déjà été utilisée avec d’autres paramètres.')
            return fingerprint,json.loads(old['result'])
        if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':raise Conflict('Le studio est suspendu.')
        if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=30:raise Conflict('Le studio termine les préparations en cours. Réessayez dans quelques minutes.')
        return fingerprint,None

    def remember(self,db,request_id,fingerprint,result):
        db.execute('INSERT INTO strategy_requests VALUES(?,?,?)',(request_id,fingerprint,dumps(result)))
        return result

    def queue(self,kind,request_id):
        if kind not in ('watch','performance'):raise Conflict('Recherche invalide.')
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,{'kind':kind})
            if old:return old
            # A manual refresh shares active work instead of flooding inference.
            active=db.execute("SELECT id,status FROM strategy_runs WHERE kind=? AND status IN ('queued','running') ORDER BY created DESC LIMIT 1",(kind,)).fetchone()
            if active:result=dict(active)
            else:
                identifier=uid();db.execute("INSERT INTO strategy_runs(id,kind,status,created) VALUES(?,?,'queued',?)",(identifier,kind,now()))
                self.store.job(db,kind,identifier)
                result={'id':identifier,'status':'queued'}
                self.store.event(db,'Veille documentaire demandée.' if kind=='watch' else 'Bilan des performances demandé.')
            return self.remember(db,request_id,fingerprint,result)

    def tick(self,current=None):
        current=(current or datetime.now(timezone.utc)).astimezone(PARIS)
        for kind,days,minute in [('watch',(0,3),0),('performance',(0,),30)]:
            slots=[(current-timedelta(days=offset)).replace(hour=8,minute=minute,second=0,microsecond=0) for offset in range(8)]
            due=max(slot for slot in slots if slot.weekday() in days and slot<=current)
            # The unique due-slot key supplies restart-safe catch-up, including first install.
            self.queue(kind,'automatic-'+kind+'-'+due.date().isoformat())

    def recover(self):
        with self.store.db() as db:
            for kind in JOBS:
                table='strategy_runs' if kind in ('watch','performance') else 'campaigns'
                for row in db.execute('SELECT target,status FROM jobs WHERE kind=?',(kind,)).fetchall():
                    if row['status']=='failed':
                        db.execute(f"UPDATE {table} SET status='failed',error='Préparation interrompue. Vous pouvez la relancer.' WHERE id=? AND status IN ('queued','running','preparing')",(row['target'],))
                    elif row['status']=='queued':
                        db.execute(f"UPDATE {table} SET status=?,error=NULL WHERE id=? AND status IN ('running','preparing')",('preparing' if kind=='campaign_draft' else 'queued',row['target']))

    def started(self,db,kind,target):
        table='strategy_runs' if kind in ('watch','performance') else 'campaigns'
        db.execute(f'UPDATE {table} SET status=?,error=NULL WHERE id=?',('preparing' if kind=='campaign_draft' else 'running',target))

    def failed(self,db,kind,target,message,retry):
        table='strategy_runs' if kind in ('watch','performance') else 'campaigns'
        status=('preparing' if kind=='campaign_draft' else 'queued') if retry else 'failed'
        db.execute(f'UPDATE {table} SET status=?,error=? WHERE id=?',(status,None if retry else message,target))

    def run(self,kind,target):
        if kind=='campaign_plan':return self.plan_campaign(target)
        if kind=='campaign_draft':return self.draft_campaign(target)
        if kind=='watch':
            from watch import generate_watch
            result=generate_watch(self.store,self.generator)
        else:
            from performance import generate_report
            result=generate_report(self.store,self.publisher,self.generator)
        with self.store.db() as db:
            if kind=='watch':
                for idea in result.get('ideas',[]):
                    db.execute('INSERT OR IGNORE INTO watch_ideas(id,run_id,body,created) VALUES(?,?,?,?)',(idea['id'],target,dumps(idea),now()))
                result={k:v for k,v in result.items() if k!='ideas'}
            db.execute("UPDATE strategy_runs SET result=?,status='ready',error=NULL WHERE id=?",(dumps(result),target))
            self.store.event(db,'La veille est prête : choisissez les idées à préparer.' if kind=='watch' else 'Le bilan des performances est disponible.')

    def context(self):
        with self.store.db() as db:
            values={}
            for kind in ('watch','performance'):
                row=db.execute('SELECT * FROM strategy_runs WHERE kind=? ORDER BY created DESC LIMIT 1',(kind,)).fetchone()
                if not row:values[kind]=None;continue
                result=json.loads(row['result'])
                # Keep the last completed report visible while a refresh is running/failed.
                if not result:
                    previous=db.execute("SELECT result FROM strategy_runs WHERE kind=? AND status='ready' ORDER BY created DESC LIMIT 1",(kind,)).fetchone()
                    if previous:result=json.loads(previous['result'])
                values[kind]={**result,**{k:row[k] for k in ('id','status','created','error')}}
            if values['watch'] is not None:
                values['watch']['ideas']=[]
                for row in db.execute('SELECT * FROM watch_ideas ORDER BY created DESC LIMIT 30'):
                    idea=json.loads(row['body']);receipt=json.loads(row['receipt'] or '{}')
                    values['watch']['ideas'].append({**idea,'created_at':row['created'],'status':'prepared' if row['item_id'] else 'new',**receipt})
            values['campaigns']=[self.campaign(row['id'],db) for row in db.execute('SELECT id FROM campaigns ORDER BY created DESC LIMIT 30').fetchall()]
        return {**values,'cadence':CADENCE,'review_home':'/editorial/#strategie'}

    def prepare_idea(self,idea_id,request_id,create_blog=False,scheduled_at=None):
        # One service process per volume. Serialize choice/reconciliation so a
        # failed calendar read never permanently freezes invalid request options.
        with self._prepare_lock:
            return self._prepare_idea(idea_id,request_id,create_blog,scheduled_at)

    def _prepare_idea(self,idea_id,request_id,create_blog,scheduled_at):
        if type(create_blog) is not bool:raise Conflict('Option article invalide.')
        payload={'idea':idea_id,'create_blog':create_blog,'scheduled_at':scheduled_at}
        agent_key='watch-'+digest(idea_id)[:40]
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            row=db.execute('SELECT * FROM watch_ideas WHERE id=?',(idea_id,)).fetchone()
            if not row:raise Conflict('Idée introuvable.')
            if row['receipt']:return self.remember(db,request_id,fingerprint,json.loads(row['receipt']))
            # Reconcile a crash after AgentService committed the draft but before
            # watch receipt storage, regardless of options on a later user retry.
            existing=db.execute('SELECT result FROM agent_requests WHERE id=?',(agent_key,)).fetchone()
            if existing:
                receipt=json.loads(existing['result'])
                db.execute('UPDATE watch_ideas SET item_id=?,receipt=? WHERE id=?',(receipt['item_id'],dumps(receipt),idea_id))
                return self.remember(db,request_id,fingerprint,receipt)
            idea=json.loads(row['body'])
        sources='\n'.join(s['title']+' : '+s['url'] for s in idea.get('sources',[]))
        brief=idea['title']+'\n'+idea['angle']+'\nSources à vérifier avant rédaction :\n'+sources
        receipt=self.agent.prepare(agent_key,brief,'social',product_query=idea.get('product_query',''),scheduled_at=scheduled_at,create_blog=create_blog)
        with self.store.db() as db:
            # The successful draft must be recorded even if the owner paused the
            # studio while the calendar request was in flight.
            db.execute('UPDATE watch_ideas SET item_id=?,receipt=? WHERE id=?',(receipt['item_id'],dumps(receipt),idea_id))
            return self.remember(db,request_id,fingerprint,receipt)

    def campaign(self,identifier,db=None):
        if db is None:
            with self.store.db() as conn:return self.campaign(identifier,conn)
        row=db.execute('SELECT * FROM campaigns WHERE id=?',(identifier,)).fetchone()
        if not row:raise Conflict('Campagne introuvable.')
        value=dict(row);value['plan']=json.loads(value['plan']);value['create_blog']=bool(value['create_blog'])
        value['items']=[]
        for row in db.execute('SELECT c.slot,c.receipt,i.status,i.scheduled_at FROM campaign_items c JOIN items i ON i.id=c.item_id WHERE campaign_id=? ORDER BY c.slot',(identifier,)):
            receipt=json.loads(row['receipt']);value['items'].append({**receipt,'slot':row['slot'],'status':row['status'],'scheduled_at':row['scheduled_at'] if row['status']!='managed' else None})
        return value

    def create_campaign(self,request_id,brief,start_date,end_date,post_count=3,create_blog=True):
        brief=bounded_text(brief,5000)
        if not brief:raise Conflict('Décrivez l’objectif de la campagne.')
        if type(post_count) is not int or not 3<=post_count<=7:raise Conflict('Choisissez entre trois et sept posts.')
        if type(create_blog) is not bool:raise Conflict('Option article invalide.')
        try:
            start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
        except (ValueError,TypeError):raise Conflict('Indiquez les dates de début et de fin.')
        today=datetime.now(PARIS).date()
        payload={'brief':brief,'start_date':start_date,'end_date':end_date,'post_count':post_count,'create_blog':create_blog}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,{'operation':'campaign',**payload})
            if old:return old
            if not today<=start<=end<=today+timedelta(days=85):raise Conflict('Choisissez une période future dans les 85 prochains jours.')
            identifier=uid()
            db.execute("INSERT INTO campaigns(id,brief,start_date,end_date,post_count,create_blog,status,created) VALUES(?,?,?,?,?,?,'queued',?)",(identifier,brief,start_date,end_date,post_count,int(create_blog),now()))
            self.store.job(db,'campaign_plan',identifier)
            self.store.event(db,'Plan de campagne demandé : '+brief[:100])
            return self.remember(db,request_id,fingerprint,{'id':identifier,'status':'queued'})

    def plan_campaign(self,identifier):
        campaign=self.campaign(identifier)
        value=self.generator.ask('Proposez une campagne cohérente pour Planète Laser, magasin d’instruments, DJ, sonorisation et éclairage à Forbach. Objectif propriétaire : '+campaign['brief']+'\nPériode : '+campaign['start_date']+' au '+campaign['end_date']+'. Exactement '+str(campaign['post_count'])+' posts sociaux supplémentaires, adaptés Facebook ET Instagram. Construisez une progression éditoriale utile (découverte, conseils, usages, approfondissement). Le planning hebdomadaire reste inchangé. Ne rédigez pas les posts finaux. Ne supposez pas promotion, prix, événement ou stock. Ne choisissez un modèle précis que si le propriétaire le demande ; sinon proposez des conseils durables. Proposez aussi un angle détaillé d’article lié au dernier sujet si demandé : '+str(campaign['create_blog'])+'.\nJSON : {"title":str,"summary":str,"steps":[{"title":str,"brief":str,"product_query":str}],"blog_angle":str}. Chaque brief décrit l’angle et une scène cohérente ; variez les environnements.')
        steps=value.get('steps')
        if not isinstance(steps,list) or len(steps)!=campaign['post_count']:raise GenerationError('Le plan de campagne est incomplet. Relancez la préparation.')
        start=datetime.fromisoformat(campaign['start_date']).replace(hour=12,tzinfo=PARIS)
        end=datetime.fromisoformat(campaign['end_date']).replace(hour=20,minute=59,tzinfo=PARIS)
        earliest=datetime.now(timezone.utc)+timedelta(hours=3)
        occupied=self.agent.calendar()
        with self.store.db() as db:occupied+=reservations(db)
        clean=[]
        for index,step in enumerate(steps):
            if not isinstance(step,dict):raise GenerationError('Une étape du plan est invalide.')
            day=round((end.date()-start.date()).days*index/(len(steps)-1))
            desired=max(start+timedelta(days=day),earliest)
            due=available_slot(desired.isoformat(),occupied)
            if datetime.fromisoformat(due)>end:raise Conflict('Le calendrier est trop rempli sur cette période. Choisissez une fin plus éloignée.')
            occupied.append(datetime.fromisoformat(due))
            title=bounded_text(step.get('title'),180);brief=bounded_text(step.get('brief'),3000)
            if not title or not brief:raise GenerationError('Une étape du plan manque de détails.')
            clean.append({'slot':index,'title':title,'brief':brief,'product_query':bounded_text(step.get('product_query',''),600),'scheduled_at':due,'create_blog':campaign['create_blog'] and index==len(steps)-1})
        plan={'title':bounded_text(value.get('title'),180),'summary':bounded_text(value.get('summary'),2000),'steps':clean,'blog_angle':bounded_text(value.get('blog_angle',''),2000)}
        with self.store.db() as db:
            db.execute("UPDATE campaigns SET plan=?,status='plan_review',error=NULL WHERE id=?",(dumps(plan),identifier))
            self.store.event(db,'Plan de campagne prêt : '+plan['title'])

    def prepare_campaign(self,identifier,revision,request_id):
        payload={'operation':'prepare_campaign','id':identifier,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            campaign=self.campaign(identifier,db)
            if campaign['revision']!=revision:raise Conflict('Ce plan a changé. Rechargez la campagne.')
            if campaign['status'] in ('preparing','ready'):
                return self.remember(db,request_id,fingerprint,{'id':identifier,'status':campaign['status']})
            if campaign['status'] not in ('plan_review','failed') or not campaign['plan'].get('steps'):raise Conflict('Attendez le plan avant de préparer les contenus.')
            db.execute("UPDATE campaigns SET status='preparing',error=NULL WHERE id=?",(identifier,))
            db.execute("DELETE FROM jobs WHERE kind='campaign_draft' AND target=?",(identifier,));self.store.job(db,'campaign_draft',identifier)
            self.store.event(db,'Préparation des brouillons de campagne demandée ; validation de chaque contenu avant publication.')
            return self.remember(db,request_id,fingerprint,{'id':identifier,'status':'preparing'})

    def draft_campaign(self,identifier):
        campaign=self.campaign(identifier)
        for step in campaign['plan']['steps']:
            with self.store.db() as db:
                if db.execute('SELECT 1 FROM campaign_items WHERE campaign_id=? AND slot=?',(identifier,step['slot'])).fetchone():continue
            brief='Campagne : '+campaign['plan']['title']+'\nObjectif : '+campaign['brief']+'\nÉtape '+str(step['slot']+1)+' : '+step['title']+'\n'+step['brief']
            if step['create_blog']:brief+='\nArticle associé après validation : '+campaign['plan'].get('blog_angle','')
            # Fixed per-step key recovers a timeout/crash between item creation and receipt storage.
            receipt=self.agent.prepare('campaign-'+digest([identifier,step['slot']])[:40],brief,'social',product_query=step['product_query'],scheduled_at=step['scheduled_at'],create_blog=step['create_blog'],schedule_deadline=datetime.fromisoformat(campaign['end_date']).replace(hour=20,minute=59,tzinfo=PARIS).isoformat())
            with self.store.db() as db:
                db.execute('INSERT OR IGNORE INTO campaign_items VALUES(?,?,?,?)',(identifier,step['slot'],receipt['item_id'],dumps(receipt)))
        with self.store.db() as db:db.execute("UPDATE campaigns SET status='ready',error=NULL WHERE id=?",(identifier,))

    def retry_campaign(self,identifier,revision,request_id):
        payload={'operation':'retry_campaign','id':identifier,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            campaign=self.campaign(identifier,db)
            if campaign['revision']!=revision or campaign['status']!='failed':raise Conflict('Cette campagne n’est plus en erreur. Rechargez la page.')
            kind='campaign_draft' if campaign['plan'].get('steps') else 'campaign_plan'
            db.execute('UPDATE campaigns SET status=?,error=NULL WHERE id=?',('preparing' if kind=='campaign_draft' else 'queued',identifier))
            db.execute('DELETE FROM jobs WHERE kind=? AND target=?',(kind,identifier));self.store.job(db,kind,identifier)
            return self.remember(db,request_id,fingerprint,{'id':identifier,'status':'preparing' if kind=='campaign_draft' else 'queued'})

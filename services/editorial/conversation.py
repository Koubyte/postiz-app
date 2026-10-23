"""Private, durable on-demand briefs. Model output can never approve or publish."""
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from PIL import Image
from generation import GenerationError, bounded_text
from store import Conflict, PARIS, dumps, now, uid

EDITABLE = ('review','rejected','failed','blocked')

class Conversation:
    def __init__(self, store, generator):
        self.store=store; self.generator=generator

    def create(self):
        with self.store.db() as db:
            identifier=uid()
            db.execute('INSERT INTO conversations VALUES(?,?,?)',(identifier,'Nouvelle discussion',now()))
        return identifier

    def require(self,db,identifier):
        if not db.execute('SELECT 1 FROM conversations WHERE id=?',(identifier,)).fetchone():raise Conflict('Discussion introuvable.')

    def photo(self,identifier,data,name):
        from media import _decode
        from pillow_heif import register_heif_opener
        register_heif_opener()
        image=_decode(data).convert('RGB');image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        buffer=io.BytesIO();image.save(buffer,'JPEG',quality=92)
        normalized=buffer.getvalue();photo_id=uid();filename='brief-'+photo_id+'.jpg'
        with self.store.db() as db:
            self.require(db,identifier)
            if db.execute('SELECT count(*) FROM chat_photos WHERE conversation_id=?',(identifier,)).fetchone()[0]>=30:raise Conflict('Cette discussion contient déjà 30 photos. Ouvrez une nouvelle discussion.')
            path=self.store.root/'media';path.mkdir(exist_ok=True)
            (path/filename).write_bytes(normalized)
            db.execute('INSERT INTO chat_photos VALUES(?,?,?,?,?,?)',(photo_id,identifier,str(name)[:160],filename,hashlib.sha256(normalized).hexdigest(),now()))
        return {'id':photo_id,'name':str(name)[:160],'url':'/editorial/media/'+filename}

    def send(self,identifier,data,actor):
        text=bounded_text(data.get('text',''),6000)
        if not text:raise Conflict('Écrivez ou dictez votre demande avant de l’envoyer.')
        nonce=data.get('id')
        if not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',nonce):raise Conflict('Identifiant de message invalide.')
        attachments=data.get('attachments',[])
        if not isinstance(attachments,list) or len(attachments)>3 or any(not isinstance(p,str) for p in attachments):raise Conflict('Joignez au maximum trois photos par message.')
        target=data.get('target') or None
        with self.store.db() as db:
            self.require(db,identifier)
            existing=db.execute('SELECT * FROM messages WHERE id=?',(nonce,)).fetchone()
            if existing:
                if existing['conversation_id']!=identifier or existing['body']!=text or json.loads(existing['attachments'])!=attachments or existing['target']!=target:raise Conflict('Ce message existe déjà avec un contenu différent.')
                return nonce
            if db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND status IN ('queued','running')",(identifier,)).fetchone():raise Conflict('L’IA prépare déjà une réponse dans cette discussion.')
            if db.execute('SELECT count(*) FROM messages WHERE conversation_id=?',(identifier,)).fetchone()[0]>=100:raise Conflict('Ouvrez une nouvelle discussion pour continuer.')
            for photo in attachments:
                if not db.execute('SELECT 1 FROM chat_photos WHERE id=? AND conversation_id=?',(photo,identifier)).fetchone():raise Conflict('Photo étrangère à cette discussion.')
            revision=None
            if target:
                item=self.editable(db,target,identifier);revision=item['revision']
            db.execute("INSERT INTO messages(id,conversation_id,role,body,attachments,target,target_revision,status,created) VALUES(?,?,'user',?,?,?,?, 'queued',?)",(nonce,identifier,text,dumps(attachments),target,revision,now()))
            db.execute('UPDATE conversations SET title=? WHERE id=? AND title=?',(text[:70],identifier,'Nouvelle discussion'))
            self.store.job(db,'chat',nonce)
            self.store.event(db,'Brief envoyé dans la discussion à la demande.',actor)
        return nonce

    def editable(self,db,item_id,conversation_id):
        if not db.execute('SELECT 1 FROM demand_items WHERE item_id=? AND conversation_id=?',(item_id,conversation_id)).fetchone():raise Conflict('Choisissez un post à la demande de cette discussion.')
        item=self.store.item(item_id,db)
        if item['status'] not in EDITABLE:raise Conflict('Ce post est en préparation ou déjà approuvé. Gérez les publications programmées dans Postiz.')
        if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce post a déjà été transmis à Postiz.')
        return item

    def answer(self,message_id):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row or row['status']=='done':return
            msg=dict(row)
            db.execute("UPDATE messages SET status='running',error=NULL WHERE id=?",(message_id,))
            history=[{'role':r['role'],'text':r['body'],'proposals':json.loads(r['proposals']),'photos':json.loads(r['attachments'])} for r in db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY created DESC LIMIT 16',(msg['conversation_id'],))][::-1]
            photos=[dict(r) for r in db.execute('SELECT id,name FROM chat_photos WHERE conversation_id=?',(msg['conversation_id'],))]
            target=self.store.item(msg['target'],db) if msg['target'] else None
            if target:
                target={'id':target['id'],'content':target['content'],'scheduled_at':target['scheduled_at'],'brief':json.loads(db.execute('SELECT brief FROM demand_items WHERE item_id=?',(target['id'],)).fetchone()[0])}
        prompt='''Vous dialoguez avec le propriétaire de Planète Laser pour préparer des posts PONCTUELS Facebook + Instagram. Le planning hebdomadaire est hors périmètre. Parlez naturellement et brièvement. Répondez à ses questions, cherchez les produits sur Internet si nécessaire, et ne redemandez pas les informations déjà fournies. Ne lancez ni publication ni programmation. Les propositions sont des briefs : le propriétaire cliquera sur « Préparer » pour créer textes et visuels, puis validera séparément la version finale. N’affirmez pas avoir créé les visuels avant ce clic.
Si le brief suffit, proposez 1 à 5 posts, chacun avec produit exact (nom ou EAN ou URL), angle et décor cohérent avec notre charte. Sinon posez UNE question utile et proposals=[]. Un prix n’est jamais obligatoire. N’inventez ni prix, ni nouvelle arrivée, ni disponibilité. Les photos jointes sont des références fournies par le propriétaire pour la génération d’images ; vous avez ici leurs noms, PAS leurs pixels : ne prétendez pas les avoir vues. Associez les identifiants de photos uniquement aux produits explicitement décrits par le propriétaire. S’il manque cette correspondance, demandez-la. Sans photo fournie, la recherche récupérera une référence fabricant.
Pour une correction, si CIBLE est renseignée, proposez EXACTEMENT un brief complet remplaçant cette cible, en gardant son produit, ses photos, sa date et son prix sauf demande contraire. Une demande de correction sans cible doit demander de choisir le post, pas créer des doublons. Aucun autre post ne sera changé.
Retournez {"reply":str,"proposals":[{"title":str,"kind":"product|advice|news","query":str,"angle":str,"scene":str,"scheduled_at":str|null,"photo_ids":[str],"price":number|null,"price_quote":str}]}. query vide uniquement pour un conseil sans produit. scheduled_at doit avoir un fuseau explicite correspondant à Europe/Paris ; date actuelle ci-dessous. Si aucun horaire n’est donné, laissez null, l’interface proposera un horaire modifiable. Une heure déjà passée doit être signalée. price ne peut être renseigné que si price_quote recopie EXACTEMENT un extrait du propriétaire confirmant son prix TTC ; sinon null. reply peut contenir des liens sources.
'''
        value=self.generator.ask(prompt+'\nDate Paris : '+datetime.now(PARIS).isoformat()+'\nHistorique : '+dumps(history)+'\nPhotos disponibles : '+dumps(photos)+'\nCIBLE : '+dumps(target))
        reply=bounded_text(value.get('reply',''),7000)
        if not reply:raise GenerationError('La réponse de l’IA est vide. Réessayez.')
        proposals=value.get('proposals',[])
        if not isinstance(proposals,list) or len(proposals)>5 or (target and len(proposals)>1):raise GenerationError('Le brief proposé n’est pas exploitable.')
        checked=[]
        allowed={p['id'] for p in photos}
        evidence='\n'.join(h['text'] for h in history if h['role']=='user')
        for p in proposals:
            if not isinstance(p,dict):raise GenerationError('Brief invalide.')
            kind=p.get('kind');query=bounded_text(p.get('query',''),600)
            if kind not in ('product','advice','news') or (kind=='product' and not query):raise GenerationError('Référence produit manquante dans le brief.')
            ids=p.get('photo_ids',[])
            if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(i,str) or i not in allowed for i in ids):raise GenerationError('Référence photo invalide.')
            due=p.get('scheduled_at') or (target['scheduled_at'] if target else (datetime.now(timezone.utc)+timedelta(hours=2)).replace(second=0,microsecond=0).isoformat())
            due=checked_date(due,allow_past=True)
            price=p.get('price');quote=p.get('price_quote')
            if price is not None:
                if type(price) not in (int,float) or not 0<price<100000 or not isinstance(quote,str) or not quote.strip() or quote not in evidence:price=None
                elif not any(abs(float(n.replace(',','.'))-price)<0.001 for n in re.findall(r'\b\d+(?:[.,]\d{1,2})?\b',quote)):price=None
            checked.append({'title':bounded_text(p.get('title',''),160),'kind':kind,'query':query,'angle':bounded_text(p.get('angle',''),2000),'scene':bounded_text(p.get('scene','Décor musical chaleureux et réaliste'),800),'scheduled_at':due,'photo_ids':ids,'price':price})
        with self.store.db() as db:
            current=db.execute('SELECT status FROM messages WHERE id=?',(message_id,)).fetchone()
            if current['status']=='done':return
            db.execute("INSERT INTO messages(id,conversation_id,role,body,target,target_revision,status,proposals,created) VALUES(?,?,'assistant',?,?,?,'done',?,?)",('reply-'+message_id,msg['conversation_id'],reply,msg['target'],msg['target_revision'],dumps(checked),now()))
            db.execute("UPDATE messages SET status='done',error=NULL WHERE id=?",(message_id,))

    def accept(self,identifier,message_id,data,actor,occupied=()):
        index=data.get('index')
        if type(index) is not int or index<0:raise Conflict('Proposition invalide.')
        with self.store.db() as db:
            self.require(db,identifier)
            msg=db.execute("SELECT * FROM messages WHERE id=? AND conversation_id=? AND role='assistant'",(message_id,identifier)).fetchone()
            if not msg:raise Conflict('Proposition introuvable.')
            old=db.execute('SELECT item_id FROM demand_items WHERE message_id=? AND proposal_index=?',(message_id,index)).fetchone()
            # Correction acceptances are also recorded separately: never repeat a mutation.
            marker=db.execute("SELECT value FROM settings WHERE key=?",('accepted:'+message_id+':'+str(index),)).fetchone()
            if marker:return marker[0]
            if old:return old[0]
            proposals=json.loads(msg['proposals'])
            if index>=len(proposals):raise Conflict('Proposition introuvable.')
            brief=proposals[index]
            from spacing import reservations,available_slot
            requested=checked_date(data.get('scheduled_at',brief['scheduled_at']))
            brief['scheduled_at']=available_slot(requested,list(occupied)+reservations(db,msg['target']))
            brief['requested_at']=requested
            price=data.get('price',brief.get('price'))
            if price is not None and (type(price) not in (int,float) or not 0<price<100000):raise Conflict('Indiquez un prix TTC positif ou laissez le champ vide.')
            brief['price']=price
            if msg['target']:
                item=self.editable(db,msg['target'],identifier)
                self.store.check_revision(item,msg['target_revision']);item_id=item['id']
                self.store.snapshot(db,item)
                db.execute("UPDATE demand_items SET brief=?,product=NULL WHERE item_id=?",(dumps(brief),item_id))
                db.execute("UPDATE items SET revision=revision+1,status='queued',content='{}',media='{}',scheduled_at=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(brief['scheduled_at'],item_id))
                db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
            else:
                item_id=uid();slot=db.execute('SELECT count(*) FROM demand_items WHERE conversation_id=?',(identifier,)).fetchone()[0]
                db.execute("INSERT INTO items(id,week_id,kind,slot,scheduled_at) VALUES(?,?,'social',?,?)",(item_id,'demand:'+identifier,slot,brief['scheduled_at']))
                db.execute('INSERT INTO demand_items VALUES(?,?,?,?,?,NULL)',(item_id,identifier,message_id,index,dumps(brief)))
            self.store.job(db,'demand',item_id)
            db.execute('INSERT INTO settings VALUES(?,?)',('accepted:'+message_id+':'+str(index),item_id))
            self.store.event(db,'Préparation d’un post à la demande. La version finale reste à valider.',actor)
        return item_id

    def draft(self,item_id):
        item=self.store.item(item_id)
        if item['status'] not in ('queued','generating','failed'):return
        with self.store.db() as db:
            row=dict(db.execute('SELECT * FROM demand_items WHERE item_id=?',(item_id,)).fetchone())
        brief=json.loads(row['brief']);product=json.loads(row['product']) if row['product'] else None
        if brief['query'] and not product:
            try:catalogue=self.generator.products()
            except Exception:catalogue=[] # Manufacturer research is available even if the shop is offline.
            product=self.generator.match(brief['query'],catalogue) or self.generator.resolve_external(brief['query'])
            product={**product,'note':brief['angle'],'price_mode':'custom' if brief.get('price') is not None else 'hide','custom_price':brief.get('price')}
        if brief['photo_ids']:
            if not product:raise GenerationError('Précisez le produit représenté sur vos photos avant de préparer ce visuel.')
            with self.store.db() as db:
                photos=[dict(db.execute('SELECT * FROM chat_photos WHERE id=? AND conversation_id=?',(id,row['conversation_id'])).fetchone()) for id in brief['photo_ids']]
            refs=[{'photo_id':p['id'],'url':'/editorial/media/'+p['filename'],'label':p['name']} for p in photos]
            product={**product,'thumbnail':refs[0]['url'],'reference_images':refs,'image_mask_required':False,'image_scope':'requested_variants','variant_uncertainty':'','media_note':'Photos fournies par le propriétaire ; fidélité et droits à vérifier.'}
        brief['product_id']=product['id'] if product else None
        with self.store.db() as db:
            db.execute('UPDATE demand_items SET brief=?,product=? WHERE item_id=?',(dumps(brief),dumps(product) if product else None,item_id))
        self.generator.draft(item_id)


def checked_date(value,allow_past=False):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError()
        if d>datetime.now(timezone.utc)+timedelta(days=90):raise Conflict('Choisissez une date dans les 90 prochains jours.')
        if not allow_past and d<=datetime.now(timezone.utc)+timedelta(minutes=5):raise Conflict('Choisissez une date au moins cinq minutes dans le futur, en heure de Paris.')
        return d.astimezone(timezone.utc).isoformat()
    except (ValueError,AttributeError,TypeError):raise Conflict('Date invalide : choisissez un horaire en heure de Paris.')

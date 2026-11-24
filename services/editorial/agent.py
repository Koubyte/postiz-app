"""Community-manager tools; relay explicit owner approval of an exact preview."""
import hashlib
import hmac
import io
import base64
import binascii
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit
from mcp.server.fastmcp import FastMCP, Image as MCPImage
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from conversation import checked_date, EDITABLE
from generation import bounded_text, SOCIAL_GUIDE, social_quality, quality_notes, opener_pattern
from overview import list_contents, normalized
from store import Conflict, dumps, now, uid, PARIS, digest, visual_edit_requires_render, EXTERNAL_VISUAL_WARNING, VISUAL_TEMPLATES
from spacing import available_slot, reservations
from agent_identity import current_identity, independent_key_id

INSTRUCTIONS = '''Vous êtes le community manager autonome de Planète Laser à Forbach (Moselle-Est : magasin d’instruments de musique, sonorisation, éclairage et DJ depuis 1989). Discutez en français avec le propriétaire, notamment à l’oral.

Voix & style éditorial :
- Pour les textes destinés au public, y compris les publications Facebook et Instagram, leurs accroches et les articles de blog, tutoie le lecteur par défaut. Adopte une voix chaleureuse, passionnée de musique, avec une touche rock et un professionnalisme accessible : naturelle et précise, sans familiarité forcée, argot artificiel ni superlatifs creux. Respecte une autre voix uniquement si le propriétaire la demande explicitement pour le contenu concerné.
- Posts Facebook + Instagram : suivez le guide de rédaction ci-dessous. Le studio applique un contrôle qualité automatique : un brouillon dont Facebook et Instagram sont identiques, qui met une URL dans Instagram ou qui ressemble à une fiche technique est refusé avec les corrections à faire. Appelez `check_post_quality` avant `create_direct_draft` ou `edit_content`, et visez un score de 100.
- Pour les articles de blog : réponse directe dès l’intro, H2/H3 clairs, tableau si utile, 700 à 1200 mots conseillés (minimum 500 mots), seo_title <= 60 car., seo_description 130–155 car., tags pertinents, et 2 à 4 liens internes naturels ([ancre](/blog/slug)) vers des articles déjà publiés quand le sujet s’y prête.

Réflexes données & catalogue :
- Avant de proposer ou rédiger sur un produit, appelez `search_catalogue` pour récupérer les vraies références en stock, prix TTC exacts, URLs et photos. Pour un article lié ou du maillage interne, consultez `public_articles` dans `get_editorial_context` ou appelez `get_published_article`.
- N’inventez jamais prix, stock, promotion, nouveauté en magasin ou caractéristique technique. Utilisez `price_mode='catalogue'` avec la référence exacte ou un prix confirmé par le propriétaire.
- Les remarques `content.editorial_notes` sont informatives : signalez-les avec l’aperçu sans bloquer le brouillon.

Gestion complète de la semaine :
- Le programme hebdomadaire comprend 7 sujets Facebook/Instagram (dont >= 3 produits distincts) et 1 article de blog.
- Vous pouvez ajouter/supprimer des demandes produits prioritaires (`add_product_request`, `delete_product_request`), lancer `prepare_week`, modifier directement des créneaux ou l’article (`update_week_plan`), demander une révision IA d’un créneau (`revise_week_slot`), relancer un plan échoué (`retry_week_plan`), et valider le plan (`approve_week_plan`) pour lancer la production des brouillons.

Mode hybride rédaction + visuels & carrousels :
- Mode assisté (recommandé pour les posts produit) : `prepare_content` avec un brief de FAITS vérifiés + l’angle choisi + le public visé. N’y dictez pas de « texte souhaité » : le rédacteur du studio écrit selon le guide, puis vous améliorez via `edit_content`, `revise_content(scope='text'|'visual'|'both')` ou `generate_visual`.
- Mode direct : `create_direct_draft(..., generate_visual=True, template=..., visual_instructions=..., carousel_slides=...)` quand le propriétaire vous dicte un texte précis ou que vous avez écrit deux légendes conformes au guide ; `bind_catalogue_product` verrouille ensuite prix et stock.
- Visuels : préférez `generate_visual` (décors variés par le studio). Si vous importez votre propre visuel, changez de décor d’un post à l’autre : jamais le même canapé, mur ou tapis sur des posts consécutifs.
- Contrôle visuel fin : `generate_visual` permet de générer ou refaire UNIQUEMENT l’image sans toucher aux textes, de choisir le gabarit (`classic`, `minimal`, `raw`, `tip_card`), ou de basculer en mode carrousel (2 à 5 slides via `carousel_slides`). Passez `recomposite_only=True` pour changer de gabarit, accroche ou slides instantanément (< 1 s) sans regénérer la scène photo. Variez les gabarits et les décors entre les posts.
- Vous pouvez aussi rejeter (`reject_content`), relancer (`retry_content`), supprimer un brouillon raté (`delete_draft`) ou mettre à jour un article déjà en ligne (`update_published_article`) pour corriger ou enrichir son maillage interne et son SEO.
- Si vous fournissez vos propres octets d’image (`attach_reference_image`, `import_final_visual`, `create_media_upload`), ne prétendez les avoir envoyés que si l’outil a réussi.

Validation & garde-fou social (obligatoire) :
- Pour tout post social prêt à programmer (`approve_content`) ou toute programmation/modification active Postiz (`apply_postiz_change`), consultez d’abord `get_content` ET `get_visual`, montrez au propriétaire les deux textes, le visuel réel, la date effective en heure de Paris et l’option `create_blog`, puis attendez son accord explicite APRÈS cet aperçu. Copiez ses mots exacts dans `owner_confirmation`. N’inventez jamais son accord.
- Avec `create_blog=true`, la validation du post lance aussi l’article compagnon (suivi via `companion_article` dans `get_content`).
- Vous disposez aussi de `read_postiz`, `preview_postiz_change`, `apply_postiz_change` (calendrier natif Postiz, brouillons, stats) et des outils stratégie (`get_marketing_strategy`, `refresh_watch`, `refresh_performance_report`, `prepare_watch_idea`, `create_campaign`, `prepare_campaign`, `retry_campaign`).

'''+SOCIAL_GUIDE

class AgentService:
    def __init__(self,store,calendar,publisher=None):
        self.store=store;self.calendar=calendar;self.strategy=None
        self._generator_instance=publisher.generator if publisher is not None else None
        if publisher is not None:
            from postiz_control import PostizControl
            self.postiz=PostizControl(store,publisher)
        else:self.postiz=None
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_previews (item_id TEXT PRIMARY KEY, review_token TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_uploads (token_hash TEXT PRIMARY KEY, item_id TEXT NOT NULL, revision INTEGER NOT NULL, purpose TEXT NOT NULL, expires TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_keys (id TEXT PRIMARY KEY, label TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, scope TEXT NOT NULL, created TEXT NOT NULL, last_used TEXT)')
            if 'key_id' not in {r[1] for r in db.execute('PRAGMA table_info(agent_uploads)')}:
                db.execute('ALTER TABLE agent_uploads ADD COLUMN key_id TEXT')

    def _generator(self):
        if self.postiz is not None:return self.postiz.publisher.generator
        if self._generator_instance is None:
            from generation import Generator
            self._generator_instance=Generator(self.store)
        return self._generator_instance

    def create_media_upload(self,item_id,revision,purpose):
        """Issue a short-lived, single-use upload credential, never a URL secret."""
        if purpose not in ('reference','final'):raise Conflict('Choisissez reference ou final.')
        token=secrets.token_urlsafe(32);token_hash=hashlib.sha256(token.encode()).hexdigest()
        expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        with self.store.db() as db:
            key_id=independent_key_id()
            if key_id and not db.execute('SELECT 1 FROM agent_keys WHERE id=?',(key_id,)).fetchone():raise Conflict('Cette clé agent a été révoquée.')
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status'] not in EDITABLE:raise Conflict('Ce brouillon ne peut pas être modifié actuellement.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')",(item_id,)).fetchone():raise Conflict('Une préparation est déjà en cours.')
            db.execute('DELETE FROM agent_uploads WHERE expires<?',(now(),))
            if db.execute('SELECT count(*) FROM agent_uploads WHERE used=0').fetchone()[0]>=50:raise Conflict('Trop de dépôts temporaires en attente.')
            db.execute('INSERT INTO agent_uploads(token_hash,item_id,revision,purpose,expires,used,key_id) VALUES(?,?,?,?,?,0,?)',(token_hash,item_id,revision,purpose,expires,key_id))
        return {'upload_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/media-upload','upload_token':token,'token_header':'X-Editorial-Upload-Token','expires_at':expires,'max_bytes':8*1024*1024,'purpose':purpose}

    def claim_media_upload(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise Conflict('Dépôt temporaire invalide ou expiré.')
        token_hash=hashlib.sha256(token.encode()).hexdigest()
        with self.store.db() as db:
            row=db.execute('SELECT * FROM agent_uploads WHERE token_hash=? AND used=0 AND expires>?',(token_hash,now())).fetchone()
            if not row:raise Conflict('Dépôt temporaire invalide ou expiré.')
            if row['key_id'] and not db.execute('SELECT 1 FROM agent_keys WHERE id=?',(row['key_id'],)).fetchone():raise Conflict('Dépôt temporaire invalide ou expiré.')
            db.execute('UPDATE agent_uploads SET used=1 WHERE token_hash=? AND used=0',(token_hash,))
            return dict(row)

    def attach_reference_image(self,request_id,item_id,revision,image_base64,filename='photo-produit'):
        """Attach an actual owner-supplied image to an existing demand draft.

        The agent must have the image bytes; an image visible in its own chat
        is not automatically accessible to this server. Never accept a path or
        fetch a private URL on behalf of the agent.
        """
        if not isinstance(image_base64,str) or len(image_base64)>((8*1024*1024+2)//3)*4:
            raise Conflict('Photo trop volumineuse : 8 Mo maximum.')
        try:raw=base64.b64decode(image_base64,validate=True)
        except (ValueError,binascii.Error):raise Conflict('Photo base64 invalide.') from None
        if not raw or len(raw)>8*1024*1024:raise Conflict('Photo absente ou trop volumineuse : 8 Mo maximum.')
        from PIL import Image
        from media import _decode
        try:
            with Image.open(io.BytesIO(raw)) as image:
                fmt=image.format
            if fmt not in ('PNG','JPEG','WEBP'):raise Conflict('Formats acceptés : PNG, JPEG ou WebP.')
            _decode(raw)
        except Conflict:raise
        except Exception:raise Conflict('Photo invalide ou dimensions non exploitables.') from None
        name=str(filename or 'photo-produit')[:160]
        image_hash=hashlib.sha256(raw).hexdigest()
        payload={'operation':'attach_reference_image','item_id':item_id,'revision':revision,'sha256':image_hash,'filename':name}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status'] not in EDITABLE:raise Conflict('Ce brouillon est en cours de traitement ou déjà approuvé.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')",(item_id,)).fetchone():raise Conflict('Une préparation est déjà en cours.')
            row=db.execute('SELECT conversation_id,brief FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
            if not row:raise Conflict('Ajoutez la photo à un contenu créé à la demande.')
            brief=json.loads(row['brief'])
            if not brief.get('query'):raise Conflict('Indiquez d’abord la référence exacte du produit.')
            if db.execute('SELECT count(*) FROM chat_photos WHERE conversation_id=?',(row['conversation_id'],)).fetchone()[0]>=30:raise Conflict('Cette discussion contient déjà 30 photos.')
            photo_id=uid();extension={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[fmt];stored='brief-'+photo_id+'.'+extension
            directory=self.store.root/'media';directory.mkdir(exist_ok=True)
            (directory/stored).write_bytes(raw)
            db.execute('INSERT INTO chat_photos VALUES(?,?,?,?,?,?)',(photo_id,row['conversation_id'],name,stored,image_hash,now()))
            brief['photo_ids']=[photo_id]
            db.execute('UPDATE demand_items SET brief=?,product=NULL WHERE item_id=?',(dumps(brief),item_id))
            self.store.snapshot(db,item)
            content=item['content'];has_text=(bool(content.get('facebook')) and bool(content.get('instagram'))) if item['kind']=='social' else bool(content.get('markdown'))
            db.execute("UPDATE items SET status='queued',revision=revision+1,media='{}',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(item_id,))
            db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
            self.store.job(db,'demand_render' if has_text else 'demand',item_id)
            result={'item_id':item_id,'revision':revision+1,'status':'queued','photo_id':photo_id,'sha256':image_hash,'review_url':self.link(item_id,row['conversation_id']),'requires_owner_approval':True}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Photo fournie par le propriétaire jointe au brouillon ; nouveau visuel en préparation.','grok-agent')
        return result
    def create_direct(self,request_id,kind,fields,product_query='',scheduled_at=None,create_blog=False,
                      generate_visual=False,visual_instructions=None,template=None,price_mode=None,
                      price=None,reference_image_url=None,reference_source_url=None,reference_owner_supplied=False):
        """Create a studio draft authored directly by the agent, with optional visual generation."""
        from generation import validate_content
        if kind not in ('social','blog') or not isinstance(fields,dict):raise Conflict('Indiquez un type social ou blog et ses champs de contenu.')
        allowed={'title','headline','facebook','instagram','markdown','excerpt','slug','category','alt','sources','seo_title','seo_description','tags','template','carousel_slides','visual_instructions'}
        if set(fields)-allowed:raise Conflict('Champs éditoriaux inconnus.')
        if type(create_blog) is not bool or (create_blog and kind!='social'):raise Conflict('L’article associé est réservé aux posts sociaux.')
        if type(generate_visual) is not bool:raise Conflict('Option de génération visuelle invalide.')
        if template is not None and template not in VISUAL_TEMPLATES:raise Conflict('Gabarit visuel inconnu.')
        query=bounded_text(product_query,600)
        visual=bounded_text(visual_instructions,6000) if visual_instructions is not None else ''
        if price is not None and (type(price) not in (int,float) or not 0<price<100000 or not query):raise Conflict('Un prix TTC confirmé exige une référence produit et un montant positif.')
        if price_mode not in (None,'hide','catalogue') or (price_mode=='catalogue' and (not query or price is not None)) or (price_mode=='hide' and price is not None):
            raise Conflict('Choisissez le prix catalogue pour un produit précis, un prix confirmé ou aucun prix.')
        reference=None
        if reference_image_url or reference_source_url:
            for url in (reference_image_url,reference_source_url):
                if not isinstance(url,str) or len(url)>2000 or urlsplit(url).scheme!='https' or not urlsplit(url).hostname or urlsplit(url).username:
                    raise Conflict('Une photo suggérée exige son URL HTTPS et la fiche source HTTPS.')
            if not query:raise Conflict('Indiquez le produit exact représenté sur la photo.')
            reference={'url':reference_image_url,'source_url':reference_source_url}
        if type(reference_owner_supplied) is not bool or (reference_owner_supplied and not reference):
            raise Conflict('La photo du propriétaire exige une référence fournie explicitement.')
        checked=validate_content(fields,kind)
        checked.pop('uncertainty',None)
        quality=self.quality_gate(checked) if kind=='social' else None
        if template and 'template' not in checked:checked['template']=template
        if visual and 'visual_instructions' not in checked:checked['visual_instructions']=visual
        payload={'operation':'create_direct_draft','kind':kind,'fields':fields,'product_query':query,'scheduled_at':scheduled_at,'create_blog':create_blog}
        if generate_visual:payload['generate_visual']=True
        if visual:payload['visual_instructions']=visual
        if template is not None:payload['template']=template
        if price_mode is not None:payload['price_mode']=price_mode
        if price is not None:payload['price']=price
        if reference:payload['reference']=reference
        if reference_owner_supplied:payload['reference_owner_supplied']=True
        with self.store.db() as db:
            _,old=self.replay(db,request_id,payload)
            if old:return old
        requested=checked_date(scheduled_at or (datetime.now(timezone.utc)+timedelta(hours=3)).replace(second=0,microsecond=0).isoformat())
        occupied=self.calendar() if kind=='social' else []
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            due=available_slot(requested,occupied+reservations(db)) if kind=='social' else requested
            if kind=='blog':
                slug=checked['slug']
                if db.execute('SELECT 1 FROM published WHERE slug=?',(slug,)).fetchone():raise Conflict('Ce slug est déjà publié ; choisissez une autre adresse.')
                if any(json.loads(row[0]).get('slug')==slug for row in db.execute("SELECT content FROM items WHERE kind='blog' AND status!='rejected'")):
                    raise Conflict('Ce slug appartient déjà à un brouillon ; choisissez une autre adresse.')
            cid=uid();item_id=uid();message_id=uid()
            brief={'title':checked['title'],'kind':'product' if query else 'advice','query':query,'angle':checked['title'],
                   'scene':'Mise en situation musicale soignée, charte Planète Laser. '+checked['title'],'scheduled_at':due,'requested_at':requested,'price':price,'photo_ids':[],
                   'instruction':'Texte rédigé directement par l’agent.','suggested_reference':reference}
            if visual:brief['visual_instructions']=visual
            if template:brief['template']=template
            if price_mode is not None:brief['price_mode']=price_mode
            if reference_owner_supplied:brief['reference_owner_supplied']=True
            status='queued' if generate_visual else 'review'
            db.execute('INSERT INTO conversations VALUES(?,?,?)',(cid,('Article · ' if kind=='blog' else 'Grok · ')+checked['title'][:60],now()))
            db.execute("INSERT INTO messages(id,conversation_id,role,body,status,created) VALUES(?,?,'user',?,'done',?)",(message_id,cid,checked['title'],now()))
            db.execute("INSERT INTO items(id,week_id,kind,slot,status,content,scheduled_at,blog_requested) VALUES(?,?,?,0,?,?,?,?)",(item_id,'demand:'+cid,kind,status,dumps(checked),due,int(create_blog)))
            db.execute('INSERT INTO demand_items VALUES(?,?,?,0,?,NULL)',(item_id,cid,message_id,dumps(brief)))
            if generate_visual:
                self.store.job(db,'demand_render',item_id)
            result={'item_id':item_id,'revision':1,'status':status,'scheduled_at':due,'requested_at':requested,
                    'blog_requested':create_blog,'review_url':self.link(item_id,cid),'has_visual':False,
                    'catalogue_revalidation':'unavailable_until_product_snapshot' if query else 'not_applicable','requires_owner_approval':True}
            if quality:result['quality']=quality
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Brouillon rédigé directement par l’agent'+(' ; visuel en préparation.' if generate_visual else ' ; visuel et validation requis.'),'grok-agent')
        return result

    def import_final_visual(self,request_id,item_id,revision,image_base64):
        """Install an agent-created final visual, preserving the draft and review gate."""
        if not isinstance(image_base64,str) or len(image_base64)>((8*1024*1024+2)//3)*4:
            raise Conflict('Visuel trop volumineux : 8 Mo maximum.')
        try:raw=base64.b64decode(image_base64,validate=True)
        except (ValueError,binascii.Error):raise Conflict('Visuel base64 invalide.') from None
        if not raw or len(raw)>8*1024*1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise Conflict('Fournissez un visuel PNG valide de 8 Mo maximum.')
        from media import _decode
        try:_decode(raw)
        except Exception:raise Conflict('Visuel PNG invalide ou dimensions non exploitables.') from None
        image_hash=hashlib.sha256(raw).hexdigest()
        payload={'operation':'import_final_visual','item_id':item_id,'revision':revision,'sha256':image_hash}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status'] not in EDITABLE:raise Conflict('Ce brouillon est en cours de traitement ou déjà approuvé.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')",(item_id,)).fetchone():raise Conflict('Une préparation est déjà en cours.')
            content=item['content']
            if item['kind']=='social' and not (content.get('facebook') and content.get('instagram')):raise Conflict('Enregistrez les textes Facebook et Instagram avant le visuel final.')
            if item['kind']=='blog' and not content.get('markdown'):raise Conflict('Enregistrez le texte de l’article avant son visuel final.')
            demand=db.execute('SELECT brief,product FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
            brief=json.loads(demand['brief']) if demand else {}
            resolved=json.loads(demand['product']) if demand and demand['product'] else None
            if brief.get('price_mode')=='catalogue' and not (resolved or item['media'].get('product_snapshot')):
                raise Conflict('Prix catalogue non vérifié : résolvez d’abord la référence produit avant le visuel final.')
            name='agent-final-'+uid()+'.png';directory=self.store.root/'media';directory.mkdir(exist_ok=True)
            (directory/name).write_bytes(raw)
            previous=item['media']; media={'media':name,'hashes':{'media':image_hash},'brand_version':'agent-supplied'}
            if item['kind']=='blog':media.update(blog_media=name);media['hashes']['blog_media']=image_hash
            product=previous.get('product_snapshot') or resolved
            if product:media['product_snapshot']=product
            # Keep the reference available for human comparison but do not claim
            # the external creator used it without evidence from that creator.
            for key in ('source_media','source_media_2','source_media_3'):
                if previous.get(key) and previous.get('hashes',{}).get(key):
                    media[key]=previous[key];media['hashes'][key]=previous['hashes'][key]
            media['provenance']={'item_id':item_id+'-r'+str(revision+1),'image_mode':'agent-supplied-final',
                'reference_used':False,'reference_use_unknown':True,'requires_visual_approval':True,
                'fidelity_requires_visual_review':True,'note':'Visuel final fourni par l’agent ; utilisation des références non attestée.'}
            self.store.snapshot(db,item)
            if image_hash!=previous.get('hashes',{}).get('media'):
                notes=content.get('editorial_notes')
                if isinstance(notes,list):content['editorial_notes']=[note for note in notes if note!=EXTERNAL_VISUAL_WARNING]
            db.execute("UPDATE items SET status='review',revision=revision+1,content=?,media=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(content),dumps(media),item_id))
            db.execute("UPDATE companion_articles SET state='revoked' WHERE parent_id=? AND article_id NOT IN (SELECT item_id FROM published)",(item_id,))
            catalogue_status = ('available' if product.get('price_mode') == 'catalogue' else 'stock_only') if product and not product.get('external') else ('unavailable_until_product_snapshot' if product or brief.get('query') else 'not_applicable')
            result={'item_id':item_id,'revision':revision+1,'status':'review','sha256':image_hash,'review_url':self.link(item_id),'catalogue_revalidation':catalogue_status,'requires_owner_approval':True}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Visuel final fourni par l’agent ; nouvelle validation requise.','grok-agent')
        return result
    def token_status(self):
        with self.store.db() as db:
            values=dict(db.execute("SELECT key,value FROM settings WHERE key IN ('agent_token_hash','agent_token_created','agent_last_used')"))
        return {'connected':bool(values.get('agent_token_hash')),'created_at':values.get('agent_token_created'),'last_used_at':values.get('agent_last_used')}
    def list_agent_keys(self):
        """Return metadata only; stored tokens are hashes and never returned."""
        with self.store.db() as db:
            return [dict(row) for row in db.execute('SELECT id,label,scope,created,last_used FROM agent_keys ORDER BY created DESC')]
    def create_agent_key(self,actor,label,scope='full'):
        if not isinstance(label,str) or not label.strip() or len(label)>80 or re.search(r'[\x00-\x1f\x7f]',label):
            raise Conflict('Indiquez un nom d’agent de 1 à 80 caractères.')
        if scope!='full':raise Conflict('Ce type d’accès n’est pas disponible.')
        identifier=uid();token='pl_agent_'+secrets.token_urlsafe(36);created=now()
        with self.store.db() as db:
            if db.execute('SELECT COUNT(*) FROM agent_keys').fetchone()[0]>=20:raise Conflict('Le nombre maximal de clés est atteint.')
            db.execute('INSERT INTO agent_keys VALUES(?,?,?,?,?,NULL)',(identifier,label.strip(),hashlib.sha256(token.encode()).hexdigest(),scope,created))
            self.store.event(db,'Une clé agent indépendante a été créée.',actor)
        return {'id':identifier,'label':label.strip(),'scope':scope,'created':created,'token':token}
    def revoke_agent_key(self,actor,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f-]{36}',identifier):raise Conflict('Clé introuvable.')
        with self.store.db() as db:
            if not db.execute('SELECT 1 FROM agent_keys WHERE id=?',(identifier,)).fetchone():raise Conflict('Clé introuvable.')
            db.execute('DELETE FROM agent_uploads WHERE key_id=?',(identifier,))
            db.execute('DELETE FROM agent_keys WHERE id=?',(identifier,))
            self.store.event(db,'Une clé agent indépendante a été révoquée.',actor)
    def rotate(self,actor):
        token='pl_agent_'+secrets.token_urlsafe(36)
        with self.store.db() as db:
            db.execute('DELETE FROM agent_uploads WHERE key_id IS NULL')
            for key,value in [('agent_token_hash',hashlib.sha256(token.encode()).hexdigest()),('agent_token_created',now())]:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,value))
            db.execute("DELETE FROM settings WHERE key='agent_last_used'")
            self.store.event(db,'Clé de préparation Grok Bot créée ; ancienne clé révoquée.',actor)
        return token
    def revoke(self,actor):
        with self.store.db() as db:
            db.execute('DELETE FROM agent_uploads WHERE key_id IS NULL')
            db.execute("DELETE FROM settings WHERE key IN ('agent_token_hash','agent_token_created','agent_last_used')")
            self.store.event(db,'Accès Grok Bot révoqué.',actor)
    def authenticate(self,token):
        return bool(self.authenticate_identity(token))
    def authenticate_identity(self,token):
        if not token or len(token)>200:return False
        digest=hashlib.sha256(token.encode()).hexdigest()
        with self.store.db() as db:
            row=db.execute("SELECT value FROM settings WHERE key='agent_token_hash'").fetchone()
            valid=bool(row and hmac.compare_digest(digest,row[0]))
            if valid:
                db.execute("INSERT OR REPLACE INTO settings VALUES('agent_last_used',?)",(now(),))
                return {'key_id':'legacy','scope':'full'}
            row=db.execute('SELECT id,scope,token_hash FROM agent_keys WHERE token_hash=?',(digest,)).fetchone()
            if row and hmac.compare_digest(digest,row['token_hash']):
                db.execute('UPDATE agent_keys SET last_used=? WHERE id=?',(now(),row['id']))
                return {'key_id':row['id'],'scope':row['scope']}
        return False
    def replay(self,db,request_id,payload):
        key_id=independent_key_id()
        if key_id and not db.execute('SELECT 1 FROM agent_keys WHERE id=?',(key_id,)).fetchone():raise Conflict('Cette clé agent a été révoquée.')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',request_id):raise Conflict('request_id doit être un UUID ou un identifiant unique de 16 à 80 caractères.')
        fingerprint=hashlib.sha256(dumps(payload).encode()).hexdigest()
        old=db.execute('SELECT * FROM agent_requests WHERE id=?',(request_id,)).fetchone()
        if old:
            if old['fingerprint']!=fingerprint:raise Conflict('Ce request_id correspond déjà à une autre demande.')
            return fingerprint,json.loads(old['result'])
        if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':raise Conflict('Le studio est suspendu.')
        if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=20:raise Conflict('La file de préparation est pleine. Attendez les résultats en cours.')
        return fingerprint,None
    def remember(self,db,request_id,fingerprint,result):
        db.execute('INSERT INTO agent_requests VALUES(?,?,?,?)',(request_id,fingerprint,dumps(result),now()))
    def recent_openers(self,exclude=None,db=None):
        """Opening formulas of the latest social posts, to stop every post starting the same way."""
        if db is None:
            with self.store.db() as conn:return self.recent_openers(exclude,conn)
        rows=db.execute("SELECT id,content FROM items WHERE kind='social' AND status!='rejected' AND content!='{}' ORDER BY scheduled_at DESC LIMIT 15").fetchall()
        openers=[]
        for row in rows:
            if row['id']==exclude:continue
            content=json.loads(row['content'])
            if content.get('instagram'):openers.append(opener_pattern(content['instagram'],content.get('title','')))
        return openers
    def quality_gate(self,checked,exclude=None,db=None,enforce=True):
        """Refuse captions with blocking issues; keep the rest visible to the owner at review."""
        quality=social_quality(checked,self.recent_openers(exclude,db))
        if enforce and quality['blocking']:
            raise Conflict('Brouillon refusé par le contrôle qualité. À corriger : '+' '.join(f'{n}) {issue}' for n,issue in enumerate(quality['blocking'],1))+' Réécris les deux légendes selon le guide (check_post_quality pour vérifier), puis renvoie.')
        notes=[n for n in checked.get('editorial_notes',[]) if not n.startswith('Qualité : ')]
        checked['editorial_notes']=notes+quality_notes(quality)
        return quality
    def check_quality(self,fields):
        if not isinstance(fields,dict):raise Conflict('Indiquez les champs facebook, instagram et title.')
        content={k:fields.get(k) if isinstance(fields.get(k),str) else '' for k in ('title','facebook','instagram')}
        quality=social_quality(content,self.recent_openers())
        return {**quality,'accepted':not quality['blocking'],'guide':SOCIAL_GUIDE}
    def link(self,item_id,conversation_id=None):
        base=os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/'
        return base+'?'+('conversation='+conversation_id+'&' if conversation_id else '')+'item='+item_id+('#discussion' if conversation_id else '#semaine')
    def content(self,item_id):
        with self.store.db() as db:
            item=self.store.item(item_id,db)
            demand=db.execute('SELECT conversation_id,brief FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
            postiz_posts=[]
            for row in db.execute('SELECT channel,result FROM deliveries WHERE item_id=?',(item_id,)):
                result=json.loads(row['result']);entries=result if isinstance(result,list) else [result]
                postiz_posts.extend({'id':e.get('postId',e.get('id')),'channel':row['channel']} for e in entries if isinstance(e,dict) and (e.get('postId') or e.get('id')))
        brief=json.loads(demand['brief']) if demand else None
        product=item['media'].get('product_snapshot')
        has_product=bool(product or (brief and (brief.get('query') or brief.get('product_id') or brief.get('kind')=='product')))
        if not has_product:
            catalogue='not_applicable'; catalogue_warning=None
        elif not product or product.get('external'):
            catalogue='unavailable_until_product_snapshot'
            catalogue_warning='Prix et disponibilité non revérifiés automatiquement : associez un produit exact du catalogue ou vérifiez-les avant publication.'
        elif product.get('price_mode')=='catalogue':
            catalogue='available'; catalogue_warning=None
        else:
            catalogue='stock_only'
            catalogue_warning='Le prix affiché ne sera pas revérifié automatiquement auprès du catalogue.'
        return {'postiz_posts':postiz_posts,'calendar_url':os.environ['PUBLIC_URL'].rstrip('/')+'/launches',**{k:item[k] for k in ('id','kind','revision','status','scheduled_at','content','error','blog_requested','companion_article','derived_from_post')},'review_token':self.review_token(item),'brief':brief,'review_url':self.link(item_id,demand['conversation_id'] if demand else None),'has_visual':bool(item['media'].get('media')),'template':item['content'].get('template'),'carousel_slides':item['content'].get('carousel_slides') or [],'carousel_slide_count':len(item['media'].get('carousel_media') or []),'has_background':bool(item['media'].get('background_media')),'requires_owner_approval':self.requires_approval(item),'catalogue_revalidation':catalogue,'catalogue_warning':catalogue_warning,'quality':social_quality(item['content'],self.recent_openers(item_id)) if item['kind']=='social' and item['content'].get('instagram') else None}
    def requires_approval(self,item):
        if item['status'] in ('approved','publishing','submitted','scheduled','published','managed'):return False
        if item.get('derived_from_post'):
            from companion import require_authorization
            try:
                with self.store.db() as db:require_authorization(self.store,db,item['id'])
                return False
            except Conflict:pass
        return True
    def context(self):
        rules=self.store.get_rules()
        summary=list_contents(self.store,limit=40)
        with self.store.db() as db:
            weeks=[dict(r) for r in db.execute('SELECT id,week,status,revision,plan FROM weeks ORDER BY week DESC LIMIT 4')]
            for week in weeks:week['plan']=json.loads(week['plan'])
            pending_requests=[dict(r) for r in db.execute("SELECT id,query,note,price_mode,price,priority,created FROM requests WHERE status='pending' ORDER BY priority DESC,created DESC LIMIT 50")]
            pub_rows=db.execute('''SELECT p.item_id,p.slug,p.body,i.revision FROM published p LEFT JOIN items i ON i.id=p.item_id ORDER BY p.slug''').fetchall()
        public_articles=[]
        for r in pub_rows:
            body=json.loads(r['body'])
            public_articles.append({
                'item_id':r['item_id'],'revision':r['revision'],'slug':body.get('slug'),
                'title':body.get('title'),'category':body.get('category'),
                'excerpt':body.get('excerpt',''),'seo_title':body.get('seoTitle'),
                'url':'https://planetelaser.fr/blog/'+str(body.get('slug','')),
                'updatedAt':body.get('updatedAt'),
                'word_count':len(str(body.get('content','')).split()),
            })
        instructions=INSTRUCTIONS
        if rules.get('custom_instructions'):
            instructions+='\n\nConsignes personnalisées du propriétaire :\n'+rules['custom_instructions']
        return {
            'instructions':instructions,'time_paris':datetime.now(PARIS).isoformat(),'paused':self.store.paused(),
            'weeks':weeks,'items':summary['items'],'contents_counts':summary['counts'],
            'pending_requests':pending_requests,'public_articles':public_articles,
            'editorial_rules':rules,'visual_templates':list(VISUAL_TEMPLATES),
            'writing_guide':SOCIAL_GUIDE,'recent_openers':self.recent_openers(),
            'review_home':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/',
            'weekly_scheduler':'Vendredi 09:00 Europe/Paris : plan de la semaine suivante, modifiable et validable via approve_week_plan.'
        }
    def prepare(self,request_id,brief,kind,product_query='',scheduled_at=None,price=None,reference_image_url=None,reference_source_url=None,create_blog=False,schedule_deadline=None,visual_instructions=None,price_mode=None,reference_owner_supplied=False):
        text=bounded_text(brief,None if kind=='blog' else 6000);query=bounded_text(product_query,600)
        visual=bounded_text(visual_instructions,6000) if visual_instructions is not None else ''
        if not text or kind not in ('social','blog'):raise Conflict('Un brief et un type social ou blog sont requis.')
        if price is not None and (type(price) not in (int,float) or not 0<price<100000 or not query):raise Conflict('Un prix TTC confirmé exige une référence produit et un montant positif.')
        if price_mode not in (None,'hide','catalogue') or (price_mode=='catalogue' and (not query or price is not None)) or (price_mode=='hide' and price is not None):raise Conflict('Choisissez le prix catalogue pour un produit précis, un prix confirmé ou aucun prix.')
        if type(create_blog) is not bool or (create_blog and kind!='social'):raise Conflict('L’article associé est une option booléenne réservée aux posts sociaux.')
        reference=None
        if reference_image_url or reference_source_url:
            for url in (reference_image_url,reference_source_url):
                if not isinstance(url,str) or len(url)>2000 or urlsplit(url).scheme!='https' or not urlsplit(url).hostname or urlsplit(url).username:raise Conflict('Une photo suggérée exige son URL HTTPS et la fiche source HTTPS.')
            if not query:raise Conflict('Indiquez le produit exact représenté sur la photo.')
            reference={'url':reference_image_url,'source_url':reference_source_url}
        if type(reference_owner_supplied) is not bool or (reference_owner_supplied and not reference):raise Conflict('La photo du propriétaire exige une référence fournie explicitement.')
        payload={'operation':'prepare','brief':text,'kind':kind,'query':query,'scheduled_at':scheduled_at,'price':price,'reference':reference}
        if create_blog:payload['create_blog']=True
        if schedule_deadline:payload['schedule_deadline']=schedule_deadline
        if visual:payload['visual_instructions']=visual
        if price_mode is not None:payload['price_mode']=price_mode
        if reference_owner_supplied:payload['reference_owner_supplied']=True
        # Fast path avoids calendar dependency on a retried successful request.
        with self.store.db() as db:
            _,old=self.replay(db,request_id,payload)
            if old:return old
        requested=checked_date(scheduled_at or (datetime.now(timezone.utc)+timedelta(hours=3)).replace(second=0,microsecond=0).isoformat())
        occupied=self.calendar() if kind=='social' else []
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            due=available_slot(requested,occupied+reservations(db)) if kind=='social' else requested
            if schedule_deadline and datetime.fromisoformat(due)>datetime.fromisoformat(schedule_deadline):
                raise Conflict('Le calendrier s’est rempli : aucun créneau dans la période de la campagne. Les brouillons existants sont conservés ; choisissez une période plus large.')
            cid=uid();item_id=uid();message_id=uid()
            data={'title':text[:150],'kind':'product' if query else 'advice','query':query,'angle':text,'scene':'Mise en situation musicale soignée, charte Planète Laser. '+text,'scheduled_at':due,'requested_at':requested,'price':price,'photo_ids':[],'instruction':text,'suggested_reference':reference,'source':'agent'}
            if visual:data['visual_instructions']=visual
            if price_mode is not None:data['price_mode']=price_mode
            if reference_owner_supplied:data['reference_owner_supplied']=True
            db.execute('INSERT INTO conversations VALUES(?,?,?)',(cid,('Article · ' if kind=='blog' else 'Grok · ')+text[:60],now()))
            db.execute("INSERT INTO messages(id,conversation_id,role,body,status,created) VALUES(?,?,'user',?,'done',?)",(message_id,cid,text,now()))
            db.execute("INSERT INTO items(id,week_id,kind,slot,status,scheduled_at) VALUES(?,?,?,0,'queued',?)",(item_id,'demand:'+cid,kind,due))
            db.execute('UPDATE items SET blog_requested=? WHERE id=?',(int(create_blog),item_id))
            db.execute('INSERT INTO demand_items VALUES(?,?,?,0,?,NULL)',(item_id,cid,message_id,dumps(data)))
            self.store.job(db,'demand',item_id)
            result={'item_id':item_id,'status':'queued','scheduled_at':due,'requested_at':requested,'blog_requested':create_blog,'review_url':self.link(item_id,cid),'requires_owner_approval':True}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,('Article' if kind=='blog' else 'Post')+' demandé par Grok Bot ; validation finale obligatoire.','grok-agent')
        return result
    def review_token(self,item):
        # Preference is not part of the legacy delivery hash: adding it there
        # would invalidate already approved posts during database migration.
        return digest({'content_hash':self.store.content_hash(item),'blog_requested':item['blog_requested']})
    def visual(self,item_id):
        item=self.store.item(item_id)
        key='blog_media' if item['kind']=='blog' else 'media';filename=item['media'].get(key)
        if not filename or not re.fullmatch(r'[A-Za-z0-9_.-]+',filename):raise Conflict('Visuel pas encore disponible.')
        raw=(self.store.root/'media'/filename).read_bytes()
        if item['media'].get('hashes',{}).get(key)!=hashlib.sha256(raw).hexdigest():raise Conflict('Le visuel a changé. Préparez un nouvel aperçu.')
        from media import _decode
        image=_decode(raw).convert('RGB');image.thumbnail((900,900))
        buf=io.BytesIO();image.save(buf,'JPEG',quality=85)
        token=self.review_token(item)
        with self.store.db() as db:
            if token!=self.review_token(self.store.item(item_id,db)):raise Conflict('Le contenu a changé pendant l’aperçu.')
            db.execute('INSERT OR REPLACE INTO agent_previews VALUES(?,?,?)',(item_id,token,now()))
        return MCPImage(data=buf.getvalue(),format='jpeg')
    def schedule(self,request_id,item_id,revision,scheduled_at=None,create_blog=None):
        if create_blog is not None and type(create_blog) is not bool:raise Conflict('Option article invalide.')
        if scheduled_at is None and create_blog is None:raise Conflict('Indiquez une date ou l’option article.')
        payload={'operation':'schedule','item_id':item_id,'revision':revision,'scheduled_at':scheduled_at,'create_blog':create_blog}
        with self.store.db() as db:
            _,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db)
        requested=checked_date(scheduled_at or item['scheduled_at'])
        occupied=self.calendar() if item['kind']=='social' else []
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status']!='review':raise Conflict('Attendez un brouillon prêt à relire. Les posts déjà validés restent gérés dans Postiz.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if create_blog and item['kind']!='social':raise Conflict('Un article ne peut pas demander un article associé.')
            due=available_slot(requested,occupied+reservations(db,item_id)) if item['kind']=='social' else requested
            wanted=item['blog_requested'] if create_blog is None else create_blog
            self.store.snapshot(db,item)
            db.execute('UPDATE items SET scheduled_at=?,blog_requested=?,revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL WHERE id=?',(due,int(wanted),item_id))
            result={'item_id':item_id,'revision':revision+1,'scheduled_at':due,'requested_at':requested,'blog_requested':wanted,'requires_owner_approval':True}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Date ou article associé préparé par Grok Bot ; nouvel aperçu et accord requis.','grok-agent')
        return result
    def approve(self,request_id,item_id,revision,review_token,owner_confirmation,media_reviewed):
        confirmation=bounded_text(owner_confirmation,2000).strip()
        if not confirmation or media_reviewed is not True:raise Conflict('Présentez les textes, le visuel, la date et l’option blog puis transmettez l’accord explicite du propriétaire.')
        payload={'operation':'approve','item_id':item_id,'revision':revision,'review_token':review_token,'owner_confirmation':confirmation,'media_reviewed':media_reviewed}
        with self.store.db() as db:
            _,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db)
        occupied=self.calendar() if item['kind']=='social' else []
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if review_token!=self.review_token(item):raise Conflict('L’aperçu a changé. Présentez la nouvelle version et demandez un nouvel accord.')
            preview=db.execute('SELECT review_token FROM agent_previews WHERE item_id=?',(item_id,)).fetchone()
            if not preview or preview[0]!=review_token:raise Conflict('Récupérez le visuel de cette version avec get_visual et montrez-le avant de demander l’accord.')
            if item['kind']=='social' and available_slot(item['scheduled_at'],occupied+reservations(db,item_id))!=item['scheduled_at']:raise Conflict('Le créneau est occupé. Proposez une nouvelle date avec schedule_content et demandez un nouvel accord.')
            self.store.approve_item(item_id,revision,'owner-via-grok',True,item['blog_requested'],db=db)
            approved=self.store.item(item_id,db)
            result={'item_id':item_id,'revision':revision,'status':'approved','scheduled_at':approved['scheduled_at'],'companion_article':approved['companion_article'],'requires_owner_approval':False}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Accord du propriétaire transmis par Grok Bot : '+confirmation,'owner-via-grok')
        return result
    def revise(self,request_id,item_id,revision,instruction,scope='both',template=None):
        if scope not in ('both','text','visual'):raise Conflict('Précisez scope=text, visual ou both.')
        if template is not None and template not in VISUAL_TEMPLATES:raise Conflict('Gabarit visuel inconnu.')
        kind=self.store.item(item_id)['kind']
        instruction=bounded_text(instruction,None if kind=='blog' else 2000)
        if not instruction:raise Conflict('Indiquez la correction à effectuer.')
        payload={'operation':'revise','item_id':item_id,'revision':revision,'instruction':instruction}
        if scope!='both':payload['scope']=scope
        if template is not None:payload['template']=template
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            if scope=='visual':
                result=self._apply_visual_update(db,item_id,revision,'grok-agent',template=template,visual_feedback=instruction)
            else:
                result=self._enqueue_revise_text_or_both(db,item_id,revision,instruction,scope,template,'grok-agent')
            self.remember(db,request_id,fingerprint,result)
        return result

    def _enqueue_revise_text_or_both(self,db,item_id,revision,instruction,scope,template,actor):
        item=self.store.item(item_id,db);self.store.check_revision(item,revision)
        if item['status'] not in EDITABLE:raise Conflict('Seul un brouillon disponible peut être corrigé. Une publication approuvée doit être gérée par le propriétaire.')
        if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
        demand=db.execute('SELECT conversation_id FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
        self.store.snapshot(db,item)
        content=dict(item['content']);content['_feedback']=instruction
        if template is not None:content['template']=template
        media_sql="media='{}'" if scope=='both' else 'media=media'
        db.execute(f"UPDATE items SET content=?,status='queued',revision=revision+1,{media_sql},approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(content),item_id))
        db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
        job_kind='draft_text' if scope=='text' else ('demand' if demand else 'draft')
        self.store.job(db,job_kind,item_id)
        label='Correction texte ciblée demandée ; autres contenus conservés.' if scope=='text' else 'Correction ciblée demandée par Grok Bot ; autres contenus conservés.'
        self.store.event(db,label,actor)
        return {'item_id':item_id,'revision':revision+1,'status':'queued','scope':scope,'review_url':self.link(item_id,demand['conversation_id'] if demand else None),'requires_owner_approval':True}

    def revise_from_owner(self,item_id,revision,instruction,scope='both',template=None,actor='owner'):
        if scope not in ('both','text','visual'):raise Conflict('Portée de révision invalide.')
        if template is not None and template not in VISUAL_TEMPLATES:raise Conflict('Gabarit visuel inconnu.')
        kind=self.store.item(item_id)['kind']
        instruction=bounded_text(instruction,None if kind=='blog' else 2000)
        if not instruction:raise Conflict('Indiquez la correction à effectuer.')
        with self.store.db() as db:
            if scope=='visual':
                return self._apply_visual_update(db,item_id,revision,actor,template=template,visual_feedback=instruction)
            return self._enqueue_revise_text_or_both(db,item_id,revision,instruction,scope,template,actor)

    def edit(self,request_id,item_id,revision,fields,scheduled_at=None):
        from generation import validate_content
        if not isinstance(fields,dict):raise Conflict('Indiquez les champs à modifier.')
        allowed={'title','headline','facebook','instagram','markdown','excerpt','slug','category','alt','sources','seo_title','seo_description','tags','template','carousel_slides','visual_instructions'}
        if set(fields)-allowed:raise Conflict('Champs éditoriaux inconnus.')
        payload={'operation':'edit','item_id':item_id,'revision':revision,'fields':fields,'scheduled_at':scheduled_at}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status'] not in (*EDITABLE,'approved'):raise Conflict('Ce contenu est en cours de traitement ou géré dans Postiz ; utilisez ses postiz_posts pour le modifier.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Utilisez les postiz_posts de get_content pour modifier ce post dans le calendrier.')
            due=checked_date(scheduled_at) if scheduled_at else item['scheduled_at']
            checked=validate_content({**item['content'],**fields},item['kind'])
            quality=None
            if item['kind']=='social':
                # Only rewritten captions are refused; a date or title change keeps legacy drafts editable.
                quality=self.quality_gate(checked,exclude=item_id,db=db,enforce=bool({'facebook','instagram'}&set(fields)))
            updated={**item['content'],**checked};updated.pop('uncertainty',None)
            if 'visual_instructions' in fields and isinstance(fields['visual_instructions'],str):
                updated['visual_instructions']=bounded_text(fields['visual_instructions'],6000)
            render=visual_edit_requires_render(item,updated)
            self.store.snapshot(db,item)
            db.execute("UPDATE items SET content=?,scheduled_at=?,status=?,revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(updated),due,'rendering' if render else 'review',item_id))
            db.execute("UPDATE companion_articles SET state='revoked' WHERE parent_id=? AND article_id NOT IN (SELECT item_id FROM published)",(item_id,))
            if render:
                demand=db.execute('SELECT product FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
                job_kind='demand_render' if demand and not demand['product'] else 'render'
                db.execute('DELETE FROM jobs WHERE target=?',(item_id,));self.store.job(db,job_kind,item_id)
            result={'item_id':item_id,'revision':revision+1,'status':'rendering' if render else 'review','requires_owner_approval':True,'review_url':self.link(item_id)}
            if EXTERNAL_VISUAL_WARNING in updated.get('editorial_notes',[]):result['visual_warning']=EXTERNAL_VISUAL_WARNING
            if quality:result['quality']=quality
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Texte enregistré directement par Grok Bot, sans réécriture Codex.','grok-agent')
        return result

    def search_catalogue(self,query='',category='',in_stock_only=False,min_price=None,max_price=None,limit=15):
        products=self._generator().products()
        tokens=[t for t in re.findall(r'[\w-]+',normalized(str(query or ''))) if len(t)>0]
        cat_filter=normalized(str(category or '').strip())
        matched=[]
        for p in products:
            if cat_filter and cat_filter not in normalized(p.get('category','')):continue
            if in_stock_only and not p.get('available'):continue
            price=p.get('price')
            if min_price is not None and (price is None or price<min_price):continue
            if max_price is not None and (price is None or price>max_price):continue
            if tokens:
                hay=normalized(f"{p.get('title','')} {p.get('ean','')} {p.get('id','')} {p.get('category','')} {p.get('description','')}")
                if not all(t in hay for t in tokens):continue
            matched.append(p)
        matched.sort(key=lambda p:(not p.get('available'),bool(p.get('image_mask_required')),str(p.get('title','')).casefold()))
        cap=max(1,min(int(limit or 15),50))
        fields=('id','title','ean','price','price_from','stock_status','stock_quantity','available','category','url','thumbnail','image_mask_required')
        return {'total':len(matched),'products':[{k:p.get(k) for k in fields} for p in matched[:cap]]}

    def search_contents(self,query='',filter='all',offset=0,limit=25):
        return list_contents(self.store,q=str(query or ''),filter=filter or 'all',offset=max(0,int(offset or 0)),limit=max(1,min(int(limit or 25),100)))

    def get_published_article(self,slug_or_id):
        key=str(slug_or_id or '').strip()
        if not key:raise Conflict('Indiquez le slug ou l’identifiant de l’article.')
        with self.store.db() as db:
            row=db.execute('SELECT p.item_id,p.slug,p.body,i.revision,i.content FROM published p LEFT JOIN items i ON i.id=p.item_id WHERE p.slug=? OR p.item_id=?',(key,key)).fetchone()
            if not row:raise Conflict('Article publié introuvable.')
            body=json.loads(row['body'])
            content=json.loads(row['content']) if row['content'] else {}
        return {
            'item_id':row['item_id'],'revision':row['revision'],'slug':body.get('slug'),
            'title':body.get('title'),'excerpt':body.get('excerpt'),
            'seo_title':body.get('seoTitle') or content.get('seo_title'),
            'seo_description':body.get('seoDescription') or content.get('seo_description'),
            'category':body.get('category'),'tags':body.get('tags',[]),
            'markdown':body.get('content'),'imageUrl':body.get('imageUrl'),
            'url':'https://planetelaser.fr/blog/'+str(body.get('slug','')),
            'createdAt':body.get('createdAt'),'updatedAt':body.get('updatedAt'),
        }

    def get_editorial_rules(self):
        return self.store.get_rules()

    def add_product_request(self,request_id,query,note='',price_mode='hide',price=None,priority='normal'):
        payload={'operation':'add_product_request','query':query,'note':note,'price_mode':price_mode,'price':price,'priority':priority}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            identifier=self.store.add_request(query,note,price_mode,price,priority,'grok-agent',db=db)
            result={'id':identifier,'status':'pending','query':str(query).strip()}
            self.remember(db,request_id,fingerprint,result)
            return result

    def delete_product_request(self,request_id,product_request_id):
        payload={'operation':'delete_product_request','product_request_id':product_request_id}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            self.store.delete_request(product_request_id,'grok-agent',db=db)
            result={'deleted':True,'product_request_id':product_request_id}
            self.remember(db,request_id,fingerprint,result)
            return result

    def update_week_plan(self,request_id,week_id,revision,subjects=None,article=None):
        if subjects is None and article is None:raise Conflict('Indiquez les sujets ou l’article à modifier dans le plan.')
        payload={'operation':'update_week_plan','week_id':week_id,'revision':revision,'subjects':subjects,'article':article}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week_id,)).fetchone()
            if not row:raise Conflict('Plan introuvable.')
            plan=json.loads(row['plan'])
            if subjects is not None:
                if not isinstance(subjects,list):raise Conflict('Liste de sujets invalide.')
                by_slot={s['slot']:dict(s) for s in plan.get('subjects',[])}
                for patch in subjects:
                    if not isinstance(patch,dict) or patch.get('slot') not in by_slot:raise Conflict('Créneau de semaine invalide.')
                    target=by_slot[patch['slot']]
                    for k in ('kind','title','angle','product_id','scene','scheduled_at'):
                        if k in patch:target[k]=patch[k]
                plan['subjects']=[by_slot[i] for i in sorted(by_slot)]
            if article is not None:
                if not isinstance(article,dict):raise Conflict('Objet article invalide.')
                merged_article=dict(plan.get('article',{}))
                for k in ('title','angle','product_id','social_slot','scheduled_at'):
                    if k in article:merged_article[k]=article[k]
                plan['article']=merged_article
            saved=self.store.save_week(week_id,revision,plan,'grok-agent',db=db)
            result={**saved,'review_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/#semaine'}
            self.remember(db,request_id,fingerprint,result)
            return result

    def revise_week_slot(self,request_id,week_id,slot,revision,instruction='',product_request_id=None):
        payload={'operation':'revise_week_slot','week_id':week_id,'slot':slot,'revision':revision,'instruction':instruction,'product_request_id':product_request_id}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            change_id=self.store.revise_subject(week_id,slot,revision,instruction,product_request_id,'grok-agent',db=db)
            result={'change_id':change_id,'week_id':week_id,'slot':slot,'status':'revising','review_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/#semaine'}
            self.remember(db,request_id,fingerprint,result)
            return result

    def approve_week_plan(self,request_id,week_id,revision):
        payload={'operation':'approve_week_plan','week_id':week_id,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            approved=self.store.approve_week(week_id,revision,'grok-agent',db=db)
            result={**approved,'review_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/#semaine'}
            self.remember(db,request_id,fingerprint,result)
            return result

    def retry_week_plan(self,request_id,week_id,revision):
        payload={'operation':'retry_week_plan','week_id':week_id,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            retried=self.store.retry_week(week_id,revision,'grok-agent',db=db)
            result={**retried,'review_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/#semaine'}
            self.remember(db,request_id,fingerprint,result)
            return result

    def _apply_visual_update(self,db,item_id,revision,actor,*,visual_instructions=None,template=None,product_query=None,
                             price_mode=None,price=None,reference_image_url=None,reference_source_url=None,
                             reference_owner_supplied=False,carousel_slides=None,recomposite_only=False,visual_feedback=None):
        from generation import validate_content
        from media import recomposite_item_media
        if template is not None and template not in VISUAL_TEMPLATES:
            raise Conflict('Gabarit visuel inconnu.')
        item=self.store.item(item_id,db);self.store.check_revision(item,revision)
        if item['status'] not in (*EDITABLE,'approved'):
            raise Conflict('Ce brouillon ne peut pas être modifié actuellement.')
        if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():
            raise Conflict('Ce contenu a déjà été transmis à Postiz.')
        if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')",(item_id,)).fetchone():
            raise Conflict('Une préparation est déjà en cours.')
        content=dict(item['content'])
        if template is not None:content['template']=template
        if carousel_slides is not None:
            if item['kind']!='social':raise Conflict('Les carrousels sont réservés aux posts sociaux.')
            checked_slides=validate_content({
                'title':content.get('title') or 'Post','headline':content.get('headline') or 'Post',
                'alt':content.get('alt') or 'Visuel','facebook':content.get('facebook') or 'Texte',
                'instagram':content.get('instagram') or 'Texte','carousel_slides':carousel_slides
            },'social')
            if 'carousel_slides' in checked_slides:content['carousel_slides']=checked_slides['carousel_slides']
            else:content.pop('carousel_slides',None)
        if visual_instructions is not None:
            content['visual_instructions']=bounded_text(visual_instructions,6000)
        if visual_feedback is not None:
            content['_visual_feedback']=bounded_text(visual_feedback,2000)
        demand=db.execute('SELECT conversation_id,brief,product FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
        product_changed=False
        if demand:
            brief=json.loads(demand['brief'])
            if template is not None:brief['template']=template
            if visual_instructions is not None:brief['visual_instructions']=content['visual_instructions']
            if product_query is not None:
                q=bounded_text(product_query,600)
                if q!=brief.get('query',''):product_changed=True
                brief['query']=q
                brief['kind']='product' if q else 'advice'
            if price_mode is not None:
                if price_mode not in ('hide','catalogue'):raise Conflict('Mode de prix invalide.')
                brief['price_mode']=price_mode;brief['price']=None;product_changed=True
            if price is not None:
                if type(price) not in (int,float) or not 0<price<100000 or not brief.get('query'):
                    raise Conflict('Un prix TTC confirmé exige une référence produit et un montant positif.')
                brief['price']=price;brief['price_mode']='custom';product_changed=True
            if reference_image_url or reference_source_url:
                for url in (reference_image_url,reference_source_url):
                    if not isinstance(url,str) or len(url)>2000 or urlsplit(url).scheme!='https' or not urlsplit(url).hostname or urlsplit(url).username:
                        raise Conflict('Une photo suggérée exige son URL HTTPS et la fiche source HTTPS.')
                if not brief.get('query'):raise Conflict('Indiquez le produit exact représenté sur la photo.')
                brief['suggested_reference']={'url':reference_image_url,'source_url':reference_source_url}
                brief['reference_owner_supplied']=bool(reference_owner_supplied)
                product_changed=True
            db.execute('UPDATE demand_items SET brief=?,product=? WHERE item_id=?',(dumps(brief),None if product_changed else demand['product'],item_id))
        elif product_query is not None or price is not None or price_mode is not None or reference_image_url:
            raise Conflict('Le changement de produit ou de référence externe est réservé aux brouillons à la demande.')

        self.store.snapshot(db,item)
        new_rev=revision+1
        can_recomposite=bool(recomposite_only and not product_changed and not visual_feedback)
        if can_recomposite:
            product=None
            if demand and demand['product']:product=json.loads(demand['product'])
            elif item['media'].get('product_snapshot'):product=item['media']['product_snapshot']
            try:
                assets=recomposite_item_media(self.store,{**item,'revision':new_rev,'content':content},product)
            except Exception as exc:
                raise Conflict(str(exc)) from None
            db.execute("UPDATE items SET content=?,media=?,status='review',revision=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(content),dumps(assets),new_rev,item_id))
            self.store.event(db,'Visuel recomposé instantanément.',actor)
            return {'item_id':item_id,'revision':new_rev,'status':'review','recomposited':True,'template':content.get('template'),'carousel_slide_count':len(assets.get('carousel_media') or []),'review_url':self.link(item_id,demand['conversation_id'] if demand else None),'requires_owner_approval':True}

        db.execute("UPDATE items SET content=?,status='queued',revision=?,media='{}',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(content),new_rev,item_id))
        db.execute("UPDATE companion_articles SET state='revoked' WHERE parent_id=? AND article_id NOT IN (SELECT item_id FROM published)",(item_id,))
        db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
        job_kind='demand_render' if (demand and (product_changed or not demand['product'])) else 'render'
        self.store.job(db,job_kind,item_id)
        self.store.event(db,'Nouveau visuel en préparation (textes conservés).',actor)
        return {'item_id':item_id,'revision':new_rev,'status':'queued','recomposited':False,'template':content.get('template'),'review_url':self.link(item_id,demand['conversation_id'] if demand else None),'requires_owner_approval':True}

    def generate_visual(self,request_id,item_id,revision,visual_instructions=None,template=None,product_query=None,
                        price_mode=None,price=None,reference_image_url=None,reference_source_url=None,
                        reference_owner_supplied=False,carousel_slides=None,recomposite_only=False):
        payload={
            'operation':'generate_visual','item_id':item_id,'revision':revision,
            'visual_instructions':visual_instructions,'template':template,'product_query':product_query,
            'price_mode':price_mode,'price':price,'reference_image_url':reference_image_url,
            'reference_source_url':reference_source_url,'reference_owner_supplied':reference_owner_supplied,
            'carousel_slides':carousel_slides,'recomposite_only':recomposite_only,
        }
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            result=self._apply_visual_update(
                db,item_id,revision,'grok-agent',
                visual_instructions=visual_instructions,template=template,product_query=product_query,
                price_mode=price_mode,price=price,reference_image_url=reference_image_url,
                reference_source_url=reference_source_url,reference_owner_supplied=reference_owner_supplied,
                carousel_slides=carousel_slides,recomposite_only=recomposite_only,
            )
            self.remember(db,request_id,fingerprint,result)
            return result

    def visual_from_owner(self,item_id,revision,data,actor='owner'):
        if not isinstance(data,dict):raise Conflict('Paramètres visuels invalides.')
        with self.store.db() as db:
            return self._apply_visual_update(
                db,item_id,revision,actor,
                visual_instructions=data.get('visual_instructions'),
                template=data.get('template'),
                carousel_slides=data.get('carousel_slides'),
                recomposite_only=bool(data.get('recomposite_only',False)),
            )

    def upload_image_from_owner(self,item_id,revision,purpose,raw_bytes,filename='image',actor='owner'):
        from PIL import Image
        from media import _decode
        if purpose not in ('final','reference'):raise Conflict('Choisissez reference ou final.')
        try:
            with Image.open(io.BytesIO(raw_bytes)) as img:fmt=img.format
            if fmt not in ('PNG','JPEG','WEBP'):raise Conflict('Formats acceptés : PNG, JPEG ou WebP.')
            decoded=_decode(raw_bytes)
        except Conflict:raise
        except Exception:raise Conflict('Image invalide ou dimensions non exploitables.') from None
        if purpose=='final':
            buf=io.BytesIO();decoded.convert('RGB').save(buf,format='PNG')
            return self.import_final_visual('owner-upload-'+uid(),item_id,revision,base64.b64encode(buf.getvalue()).decode())
        with self.store.db() as db:
            demand=db.execute('SELECT conversation_id FROM demand_items WHERE item_id=?',(item_id,)).fetchone()
        if demand:
            return self.attach_reference_image('owner-ref-'+uid(),item_id,revision,base64.b64encode(raw_bytes).decode(),filename)
        with self.store.db() as db:
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if item['status'] not in (*EDITABLE,'approved'):raise Conflict('Ce brouillon ne peut pas être modifié actuellement.')
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')",(item_id,)).fetchone():raise Conflict('Une préparation est déjà en cours.')
            ext={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[fmt]
            stored='owner-ref-'+uid()+'.'+ext
            directory=self.store.root/'media';directory.mkdir(exist_ok=True)
            (directory/stored).write_bytes(raw_bytes)
            sha=hashlib.sha256(raw_bytes).hexdigest()
            self.store.snapshot(db,item)
            content=dict(item['content']);content['_owner_reference_file']=stored;content['_owner_reference_sha256']=sha
            db.execute("UPDATE items SET content=?,status='queued',revision=revision+1,media='{}',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(dumps(content),item_id))
            db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
            self.store.job(db,'render',item_id)
            self.store.event(db,'Photo de référence importée ; nouveau visuel en préparation.',actor)
            return {'item_id':item_id,'revision':revision+1,'status':'queued','sha256':sha}

    def reject_content(self,request_id,item_id,revision,note='À revoir'):
        clean_note=str(note or 'À revoir').strip()[:1000] or 'À revoir'
        payload={'operation':'reject_content','item_id':item_id,'revision':revision,'note':clean_note}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():
                raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if item['status'] not in ('review','approved','failed','blocked'):
                raise Conflict('Ce contenu ne peut pas être refusé actuellement.')
            self.store.snapshot(db,item)
            content=dict(item['content']);content['_feedback']=clean_note
            db.execute("UPDATE items SET content=?,status='rejected',revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=? WHERE id=?",(dumps(content),clean_note,item_id))
            result={'item_id':item_id,'revision':revision+1,'status':'rejected'}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Contenu renvoyé en correction par Grok Bot.','grok-agent')
            return result

    def retry_content(self,request_id,item_id,revision):
        payload={'operation':'retry_content','item_id':item_id,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            item=self.store.item(item_id,db);self.store.check_revision(item,revision)
            if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'",(item_id,)).fetchone():
                raise Conflict('Ce contenu a déjà été transmis à Postiz.')
            if item['status'] not in ('failed','blocked','rejected'):
                raise Conflict('Ce contenu ne nécessite pas de relance.')
            self.store.snapshot(db,item)
            db.execute("UPDATE items SET status='queued',revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL,media='{}' WHERE id=?",(item_id,))
            db.execute('DELETE FROM jobs WHERE target=?',(item_id,))
            job_kind='demand' if db.execute('SELECT 1 FROM demand_items WHERE item_id=?',(item_id,)).fetchone() else 'draft'
            self.store.job(db,job_kind,item_id)
            result={'item_id':item_id,'revision':revision+1,'status':'queued'}
            self.remember(db,request_id,fingerprint,result)
            self.store.event(db,'Nouvelle préparation lancée par Grok Bot.','grok-agent')
            return result

    def delete_draft(self,request_id,item_id,revision):
        payload={'operation':'delete_draft','item_id':item_id,'revision':revision}
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            self.store.delete_draft(item_id,revision,'grok-agent',db=db)
            result={'deleted':True,'item_id':item_id}
            self.remember(db,request_id,fingerprint,result)
            return result

    def update_published_article(self,request_id,item_id_or_slug,revision,markdown=None,title=None,excerpt=None,
                                 seo_title=None,seo_description=None,category=None,tags=None):
        key=str(item_id_or_slug or '').strip()
        if not key:raise Conflict('Indiquez l’identifiant ou le slug de l’article publié.')
        payload={
            'operation':'update_published_article','target':key,'revision':revision,
            'markdown':markdown,'title':title,'excerpt':excerpt,'seo_title':seo_title,
            'seo_description':seo_description,'category':category,'tags':tags,
        }
        with self.store.db() as db:
            fingerprint,old=self.replay(db,request_id,payload)
            if old:return old
            row=db.execute('SELECT item_id,slug FROM published WHERE item_id=? OR slug=?',(key,key)).fetchone()
            if not row:raise Conflict('Article publié introuvable.')
            item_id=row['item_id']
            self.store.update_published_article(
                item_id,revision,markdown,'grok-agent',
                title=title,excerpt=excerpt,seo_title=seo_title,
                seo_description=seo_description,category=category,tags=tags,db=db,
            )
            item=self.store.item(item_id,db)
            public=json.loads(db.execute('SELECT body FROM published WHERE item_id=?',(item_id,)).fetchone()[0])
            result={'item_id':item_id,'slug':public['slug'],'revision':item['revision'],'status':'published','url':'https://planetelaser.fr/blog/'+public['slug'],'updated_at':public.get('updatedAt')}
            self.remember(db,request_id,fingerprint,result)
            return result

class BearerGate:
    def __init__(self,app,service):self.app=app;self.service=service
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]));auth=headers.get(b'authorization',b'').decode('latin1')
        origin=headers.get(b'origin',b'').decode('latin1')
        if origin and origin!=os.environ['PUBLIC_URL'].rstrip('/'):
            return await JSONResponse({'error':'Origin refused'},status_code=403)(scope,receive,send)
        identity=self.service.authenticate_identity(auth[7:]) if auth.startswith('Bearer ') else None
        if not identity:
            return await JSONResponse({'error':'Agent credential required'},status_code=401,headers={'WWW-Authenticate':'Bearer'})(scope,receive,send)
        context_token=current_identity.set(identity)
        try:return await self.app(scope,receive,send)
        finally:current_identity.reset(context_token)

def build_mcp(service):
    host=urlsplit(os.environ['PUBLIC_URL']).netloc
    mcp=FastMCP('Planète Laser Studio',instructions=INSTRUCTIONS,stateless_http=True,json_response=True,max_request_body_size=12*1024*1024,transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=[host,'testserver','localhost:*','127.0.0.1:*'],allowed_origins=[os.environ['PUBLIC_URL'].rstrip('/')]))
    read=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
    write=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True,openWorldHint=True)
    @mcp.tool(annotations=read)
    def get_editorial_context()->dict:
        """Read brand rules, weekly plans, drafts and published blog articles. Start here."""
        return service.context()
    @mcp.tool(annotations=read)
    def get_content(item_id:str)->dict:
        """Read generation status, texts, errors and owner review link. Poll at most every 30 seconds."""
        return service.content(item_id)
    @mcp.tool(annotations=read)
    def get_visual(item_id:str)->MCPImage:
        """Inspect a generated preview. This never approves it or makes it public."""
        return service.visual(item_id)
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=False,openWorldHint=False))
    def create_media_upload(item_id:str,revision:int,purpose:Literal['reference','final'])->dict:
        """Issue a 10-minute, single-use upload token scoped to one draft and revision. POST raw image bytes to the returned HTTPS upload_url, with the token in X-Editorial-Upload-Token (never the URL). Max 8 MiB; reference accepts PNG/JPEG/WebP, final requires PNG. A successful POST attaches it; failure or expired/used tokens require a new token. Use only when you can access the actual local file and make the POST yourself. Never claim upload success until the POST confirms it."""
        return service.create_media_upload(item_id,revision,purpose)
    @mcp.tool(annotations=write)
    def create_direct_draft(request_id:str,kind:Literal['social','blog'],fields:dict,product_query:str='',scheduled_at:str|None=None,create_blog:bool=False,generate_visual:bool=False,visual_instructions:str|None=None,template:Literal['classic','minimal','raw','tip_card']|None=None,price_mode:Literal['hide','catalogue']|None=None,price:float|None=None,reference_image_url:str|None=None,reference_source_url:str|None=None,reference_owner_supplied:bool=False)->dict:
        """Create ONE studio draft directly from your finished text, without Codex rewriting. Social captions go through the quality gate: identical Facebook/Instagram texts, URLs in Instagram or spec-sheet captions are refused with the fixes to make (call check_post_quality first). fields may include title, headline, facebook, instagram, markdown, excerpt, slug, category, alt, sources, seo_title, seo_description, tags, template, carousel_slides. Pass generate_visual=true (with optional visual_instructions, template, price_mode, reference_image_url) to also generate the visual right away, or attach/import one afterward. Reuse request_id for a retry."""
        return service.create_direct(request_id,kind,fields,product_query,scheduled_at,create_blog,generate_visual,visual_instructions,template,price_mode,price,reference_image_url,reference_source_url,reference_owner_supplied)
    @mcp.tool(annotations=read)
    def check_post_quality(fields:dict)->dict:
        """Check Facebook + Instagram captions before create_direct_draft or edit_content. fields: title, facebook, instagram. Returns score (aim for 100), blocking issues (the draft would be refused), warnings (shown to the owner at review) and the writing guide. Never creates or changes anything."""
        return service.check_quality(fields)
    @mcp.tool(annotations=write)
    def bind_catalogue_product(request_id:str,item_id:str,revision:int,query:str,price_mode:Literal['hide','catalogue']='catalogue')->dict:
        """Bind an exact, uniquely matched store product to an existing individual draft without generating or rewriting content. Returns the current price and availability; compare those to your text and image. With catalogue price mode, price and availability are rechecked before publication. Invalidates previous approval and increments revision. Reuse request_id on retry."""
        from catalogue_binding import bind_catalogue_product as bind
        return bind(service,request_id,item_id,revision,query,price_mode)
    @mcp.tool(annotations=write)
    def attach_reference_image(request_id:str,item_id:str,revision:int,image_base64:str,filename:str='photo-produit')->dict:
        """Attach the actual bytes of an owner-supplied product photo to an existing demand draft. PNG/JPEG/WebP, base64 without a data-URL prefix, at most 8 MiB decoded. Use only if you actually have the image bytes; a picture merely visible in your chat is not automatically available. It triggers a new visual without rewriting existing text, invalidates prior approval, and returns a new revision. Reuse request_id on retry. Never claim the picture was transmitted if the call did not succeed."""
        return service.attach_reference_image(request_id,item_id,revision,image_base64,filename)
    @mcp.tool(annotations=write)
    def import_final_visual(request_id:str,item_id:str,revision:int,image_base64:str)->dict:
        """Attach your own finished visual to a social or blog draft without regenerating it. Send PNG bytes as base64, no data-URL prefix, at most 8 MiB decoded. Only use bytes you actually possess. Text and schedule are preserved; approval is invalidated and the result must be shown to the owner. Reuse request_id on retry."""
        return service.import_final_visual(request_id,item_id,revision,image_base64)
    @mcp.tool(annotations=write)
    def prepare_content(request_id:str,brief:str,kind:Literal['social','blog'],product_query:str='',scheduled_at:str|None=None,price:float|None=None,reference_image_url:str|None=None,reference_source_url:str|None=None,create_blog:bool=False,visual_instructions:str|None=None,price_mode:Literal['hide','catalogue']|None=None,reference_owner_supplied:bool=False)->dict:
        """Queue ONE additional social subject (FB+IG) or blog article for Codex. Owner approval of the finished preview is mandatory and may be relayed via approve_content. Use a unique request_id, reuse it on network retry. Brief includes verified facts/sources and exact product query. visual_instructions optionally provides detailed scene, composition and visual direction; it is passed to image generation. To use the current verified store price, pass price_mode='catalogue' with an exact product query; pass price for an explicitly confirmed custom amount, or omit both to hide price. Optional reference must depict the exact model/finish with its real source page. Set reference_owner_supplied=true only if the owner explicitly supplied this exact reference as their own photo, never merely to bypass a supplier restriction. Date includes timezone; social spacing is automatic. create_blog requests a companion article published immediately after drafting once the owner approves the social preview. Weekly plan is untouched."""
        return service.prepare(request_id,brief,kind,product_query,scheduled_at,price,reference_image_url,reference_source_url,create_blog,visual_instructions=visual_instructions,price_mode=price_mode,reference_owner_supplied=reference_owner_supplied)
    @mcp.tool(annotations=write)
    def schedule_content(request_id:str,item_id:str,revision:int,scheduled_at:str|None=None,create_blog:bool|None=None)->dict:
        """Set a ready unapproved draft's date and/or companion article option without regenerating content. Social slots are spaced at least 2h. Read current revision. This invalidates the previous preview: show get_content and get_visual again and obtain fresh owner consent."""
        return service.schedule(request_id,item_id,revision,scheduled_at,create_blog)
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=True,openWorldHint=True))
    def approve_content(request_id:str,item_id:str,revision:int,review_token:str,owner_confirmation:str,media_reviewed:bool)->dict:
        """RELAY EXPLICIT OWNER APPROVAL ONLY. First show get_content texts, get_visual image, effective Paris date and blog option; then wait for the owner's explicit agreement to this exact preview. Copy their actual words in owner_confirmation, never invent consent. Pass that preview's revision/review_token and media_reviewed=true. Schedules the social post; an opted-in companion article is written and published as soon as ready, regardless of social date. Never call merely because creation was requested. Returns approval, not proof of delivery; check get_content afterwards. Reuse request_id on retry."""
        return service.approve(request_id,item_id,revision,review_token,owner_confirmation,media_reviewed)
    @mcp.tool(annotations=write)
    def revise_content(request_id:str,item_id:str,revision:int,instruction:str,scope:Literal['both','text','visual']='both',template:Literal['classic','minimal','raw','tip_card']|None=None)->dict:
        """Ask the studio to revise ONE existing unapproved draft. scope='text' rewrites only text and keeps/recomposites media; scope='visual' regenerates only the image while preserving exact text; scope='both' redoes both. Optional template sets the visual layout. Does not approve."""
        return service.revise(request_id,item_id,revision,instruction,scope,template)
    @mcp.tool(annotations=write)
    def generate_visual(request_id:str,item_id:str,revision:int,visual_instructions:str|None=None,template:Literal['classic','minimal','raw','tip_card']|None=None,product_query:str|None=None,price_mode:Literal['hide','catalogue']|None=None,price:float|None=None,reference_image_url:str|None=None,reference_source_url:str|None=None,reference_owner_supplied:bool=False,carousel_slides:list[dict]|None=None,recomposite_only:bool=False)->dict:
        """Generate, regenerate or instantly recomposite ONLY the visual (or 2-5 slide carousel) of an existing draft while preserving all texts. Pass recomposite_only=true to switch template or carousel_slides instantly from the existing scene without calling image generation. Reuse request_id on retry."""
        return service.generate_visual(request_id,item_id,revision,visual_instructions,template,product_query,price_mode,price,reference_image_url,reference_source_url,reference_owner_supplied,carousel_slides,recomposite_only)
    @mcp.tool(annotations=read)
    def search_catalogue(query:str='',category:str='',in_stock_only:bool=False,min_price:float|None=None,max_price:float|None=None,limit:int=15)->dict:
        """Search the live Planète Laser catalogue (real titles, EANs, EUR TTC prices, stock availability, URLs and thumbnails)."""
        return service.search_catalogue(query,category,in_stock_only,min_price,max_price,limit)
    @mcp.tool(annotations=read)
    def search_contents(query:str='',filter:Literal['all','review','attention','scheduled','published','progress','blog']='all',offset:int=0,limit:int=25)->dict:
        """Search studio drafts, weekly items, scheduled posts and published articles with status filters."""
        return service.search_contents(query,filter,offset,limit)
    @mcp.tool(annotations=read)
    def get_published_article(slug_or_id:str)->dict:
        """Read the full Markdown, SEO metadata, tags, revision and URL of one published blog article."""
        return service.get_published_article(slug_or_id)
    @mcp.tool(annotations=read)
    def get_editorial_rules()->dict:
        """Read the owner's editable editorial guidelines, default visual template and store signature."""
        return service.get_editorial_rules()
    @mcp.tool(annotations=write)
    def add_product_request(request_id:str,query:str,note:str='',price_mode:Literal['hide','catalogue','custom']='hide',price:float|None=None,priority:Literal['normal','high']='normal')->dict:
        """Add a product highlight request to the weekly queue."""
        return service.add_product_request(request_id,query,note,price_mode,price,priority)
    @mcp.tool(annotations=write)
    def delete_product_request(request_id:str,product_request_id:str)->dict:
        """Delete a pending product highlight request."""
        return service.delete_product_request(request_id,product_request_id)
    @mcp.tool(annotations=write)
    def prepare_week()->dict:
        """Find or prepare next week's 7 social subjects and 1 blog plan. Never duplicates an existing week. You can adjust it with update_week_plan/revise_week_slot and approve it with approve_week_plan."""
        if service.store.paused():raise Conflict('Le studio est suspendu.')
        identifier=service.store.prepare()
        return {'week_id':identifier,'review_url':os.environ['PUBLIC_URL'].rstrip('/')+'/editorial/#semaine','requires_owner_approval':True}
    @mcp.tool(annotations=write)
    def update_week_plan(request_id:str,week_id:str,revision:int,subjects:list[dict]|None=None,article:dict|None=None)->dict:
        """Update specific slots (by slot index 0..6) and/or the article of a weekly plan in plan_review."""
        return service.update_week_plan(request_id,week_id,revision,subjects,article)
    @mcp.tool(annotations=write)
    def revise_week_slot(request_id:str,week_id:str,slot:int,revision:int,instruction:str='',product_request_id:str|None=None)->dict:
        """Ask the studio to replace or rework ONE slot (0..6) of a weekly plan in plan_review."""
        return service.revise_week_slot(request_id,week_id,slot,revision,instruction,product_request_id)
    @mcp.tool(annotations=write)
    def approve_week_plan(request_id:str,week_id:str,revision:int)->dict:
        """Approve a weekly plan to immediately launch drafting of its 7 social items and 1 blog article. Finished items still require preview/approval before publication."""
        return service.approve_week_plan(request_id,week_id,revision)
    @mcp.tool(annotations=write)
    def retry_week_plan(request_id:str,week_id:str,revision:int)->dict:
        """Retry a failed weekly plan preparation."""
        return service.retry_week_plan(request_id,week_id,revision)
    @mcp.tool(annotations=write)
    def reject_content(request_id:str,item_id:str,revision:int,note:str='À revoir')->dict:
        """Mark an unapproved draft as rejected with feedback."""
        return service.reject_content(request_id,item_id,revision,note)
    @mcp.tool(annotations=write)
    def retry_content(request_id:str,item_id:str,revision:int)->dict:
        """Retry preparation on a failed, blocked or rejected draft."""
        return service.retry_content(request_id,item_id,revision)
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=True,openWorldHint=False))
    def delete_draft(request_id:str,item_id:str,revision:int)->dict:
        """Delete an unapproved, unpublished draft permanently."""
        return service.delete_draft(request_id,item_id,revision)
    @mcp.tool(annotations=write)
    def update_published_article(request_id:str,item_id_or_slug:str,revision:int,markdown:str|None=None,title:str|None=None,excerpt:str|None=None,seo_title:str|None=None,seo_description:str|None=None,category:Literal['guides','actualites','produits']|None=None,tags:list[str]|None=None)->dict:
        """Update an already-published blog article in place (Markdown, SEO title/description, title, excerpt, category, tags) preserving its slug and revision history."""
        return service.update_published_article(request_id,item_id_or_slug,revision,markdown,title,excerpt,seo_title,seo_description,category,tags)
    @mcp.tool(annotations=write)
    def edit_content(request_id:str,item_id:str,revision:int,fields:dict,scheduled_at:str|None=None)->dict:
        """Save Grok's exact text into ONE studio draft (rewritten facebook/instagram captions pass the same quality gate as create_direct_draft) or not-yet-delivered approved item without Codex rewriting it. fields: title, headline, facebook, instagram, markdown, excerpt, slug, category, alt, sources, seo_title, seo_description, tags, template, carousel_slides, visual_instructions. Text-only edits retain visuals. Changing a title, template or carousel_slides regenerates a studio-made visual; a finished visual supplied by the agent stays intact and a warning asks for a consistency check. Invalidates prior approval. For delivered items use postiz_posts from get_content and native Postiz tools."""
        return service.edit(request_id,item_id,revision,fields,scheduled_at)
    def native():
        if service.postiz is None:raise Conflict('Connexion Postiz indisponible.')
        return service.postiz
    @mcp.tool(annotations=read)
    def get_postiz_capabilities()->dict:
        """Read native Postiz routes and exact create/edit payload examples. These tools manage all posts, including those outside the studio and already scheduled. Start here before native operations."""
        return native().capabilities()
    @mcp.tool(annotations=read)
    def read_postiz(path:str,query:dict|None=None)->dict|list:
        """Read Postiz calendar, full editable posts, connected channels, media library, provider settings and analytics. Paths relative to the public API, e.g. /posts, /posts/ID, /integrations, /media. No credentials are returned."""
        return native().read(path,query)
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def preview_postiz_change(method:Literal['POST','PUT','DELETE'],path:str,body:dict|None=None)->dict:
        """Prepare a native Postiz operation WITHOUT executing it. Grok can write posts itself, edit existing text/images/settings, reschedule, return posts to drafts, delete, or import media. Uses current post snapshots and adjusts social spacing. Read capabilities for payloads; preserve existing IDs/media/settings when editing. Show returned texts, media and effective date to owner before a publication-affecting action. Returns preview_token and requires_owner_confirmation."""
        return native().preview(method,path,body)
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=True,openWorldHint=True))
    def apply_postiz_change(request_id:str,preview_token:str,owner_confirmation:str='')->dict:
        """Execute the exact prepared native Postiz operation. If requires_owner_confirmation, relay the owner's actual explicit agreement AFTER showing the preview; never invent it. Draft creation/editing and media import do not need publication consent. Reuse preview_token and request_id on retry; uncertain operations are never automatically repeated. Published social posts cannot be rewritten on the network by Postiz."""
        return native().apply(request_id,preview_token,owner_confirmation)
    @mcp.tool(annotations=read)
    def get_postiz_operation(request_id:str)->dict:
        """Read the durable receipt of a native operation after a timeout. If uncertain, inspect the actual calendar; never create another copy blindly."""
        return native().operation(request_id)
    def strategy():
        if service.strategy is None:raise Conflict('Espace veille et campagnes indisponible.')
        return service.strategy
    @mcp.tool(annotations=read)
    def get_marketing_strategy()->dict:
        """Read sourced watch ideas, real weekly analytics with metric scopes, and campaign plans/items. No creation or publication. Show source dates and data limitations."""
        return strategy().context()
    @mcp.tool(annotations=write)
    def refresh_watch(request_id:str)->dict:
        """Queue fresh public manufacturer/news and useful advice research. Returns job status; poll get_marketing_strategy sparingly. Never prepares posts or approves anything."""
        return strategy().queue('watch',request_id)
    @mcp.tool(annotations=write)
    def refresh_performance_report(request_id:str)->dict:
        """Queue real Facebook/Instagram analytics refresh. No fictional metrics or automatic schedule changes; use get_marketing_strategy to read the report and its limitations."""
        return strategy().queue('performance',request_id)
    @mcp.tool(annotations=write)
    def prepare_watch_idea(request_id:str,idea_id:str,create_blog:bool=False,scheduled_at:str|None=None)->dict:
        """Prepare the owner's selected watch idea as ONE unapproved social draft and optional companion article request. Reuses existing draft for the same idea. Does not publish; exact preview/approval still required."""
        return strategy().prepare_idea(idea_id,request_id,create_blog,scheduled_at)
    @mcp.tool(annotations=write)
    def create_campaign(request_id:str,brief:str,start_date:str,end_date:str,post_count:int=3,create_blog:bool=True)->dict:
        """Queue a coordinated campaign PLAN of 3–7 additional social subjects, with one optional blog companion on the last subject. Dates are YYYY-MM-DD in Paris; no more than 85 days ahead. Review the resulting plan with owner before preparing drafts; weekly plans unchanged."""
        return strategy().create_campaign(request_id,brief,start_date,end_date,post_count,create_blog)
    @mcp.tool(annotations=write)
    def prepare_campaign(request_id:str,campaign_id:str,revision:int)->dict:
        """After owner selects this campaign plan, queue its drafts with 2-hour social spacing. Safe to retry same request_id. Does NOT approve or publish: present each final content/date/visual for explicit owner approval. Follow item review links in get_marketing_strategy."""
        return strategy().prepare_campaign(campaign_id,revision,request_id)
    @mcp.tool(annotations=write)
    def retry_campaign(request_id:str,campaign_id:str,revision:int)->dict:
        """Retry a failed campaign's current stage, preserving already-created drafts. Does not approve or publish. Expired campaign dates require a new campaign period."""
        return strategy().retry_campaign(campaign_id,revision,request_id)
    return mcp

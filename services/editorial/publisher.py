"""Only this module delivers approved immutable revisions to public destinations."""
import hashlib
import json
import os
import re
from datetime import datetime,timezone,timedelta
from pathlib import Path
import requests
from store import Conflict, now, dumps, uid

class Publisher:
    def __init__(self,store,generator):self.store=store;self.generator=generator
    def api(self,method,path,**kwargs):
        r=requests.request(method,os.environ['POSTIZ_INTERNAL_URL'].rstrip('/')+'/api/public/v1'+path,headers={'Authorization':os.environ['POSTIZ_API_KEY']},timeout=40,**kwargs)
        if not r.ok:raise Conflict('Postiz a refusé l’opération (HTTP '+str(r.status_code)+'). Vérifiez le canal et le contenu.')
        return r.json()
    def check(self,item):
        if not item['approval_hash'] or item['approval_hash']!=self.store.content_hash(item):raise Conflict('La version ne correspond plus à celle approuvée.')
        with self.store.db() as db:
            from companion import check_publication
            check_publication(self.store,db,item)
            demand=db.execute('SELECT 1 FROM demand_items WHERE item_id=?',(item['id'],)).fetchone()
        if demand and item['kind']=='social':
            from spacing import calendar_times,reservations,available_slot
            occupied=calendar_times(self)
            with self.store.db() as db:
                if available_slot(item['scheduled_at'],occupied+reservations(db,item['id']))!=item['scheduled_at']:
                    raise Conflict('Le calendrier a changé : un autre sujet est à moins de deux heures. Choisissez un nouvel horaire et validez à nouveau.')
        for key,expected in item['media'].get('hashes',{}).items():
            path=self.store.root/'media'/item['media'][key]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise Conflict('Un média a changé après validation.')
        product=item['media'].get('product_snapshot')
        if product and not product.get('external'):
            current=next((p for p in self.generator.products(force=True) if p['id']==product['id']),None)
            if current is None:raise Conflict('Le produit n’est plus dans le catalogue.')
            if current.get('stock_status')!=product.get('stock_status') or current.get('available')!=product.get('available'):raise Conflict('La disponibilité a changé depuis la préparation. Nouvelle validation nécessaire.')
            if product.get('price_mode')=='catalogue' and current.get('price')!=product.get('price'):raise Conflict('Le prix a changé. Nouvelle préparation et validation nécessaires.')
    def deliver(self,id):
        if self.store.paused():return
        item=self.store.item(id)
        if item['status']!='approved':return
        due=datetime.fromisoformat(item['scheduled_at'])
        # Social posts enter Postiz's calendar as soon as the owner approves.
        # The blog remains private until its due time.
        if item['kind']=='blog' and due>datetime.now(timezone.utc):return
        if due<datetime.now(timezone.utc)-timedelta(minutes=30):raise Conflict('Créneau dépassé de plus de trente minutes. Choisissez une nouvelle date et validez à nouveau.')
        self.check(item)
        with self.store.db() as db:
            current=self.store.item(id,db)
            if current['status']!='approved' or current['approval_hash']!=item['approval_hash']:return
            if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':return
            db.execute("UPDATE items SET status='publishing' WHERE id=?",(id,))
        if item['kind']=='blog':
            c=item['content'];base=os.environ['PUBLIC_URL'].rstrip('/')
            body={'slug':c['slug'],'title':c['title'],'excerpt':c['excerpt'],'content':c['markdown'],'category':c['category'],'tags':[],'imageUrl':base+'/editorial/public/media/'+item['media']['blog_media'],'imageAlt':c.get('alt',c['title']),'published':True,'createdAt':now(),'updatedAt':now()}
            with self.store.db() as db:
                # Recheck the parent consent in the same transaction as publication.
                from companion import check_publication
                current=self.store.item(id,db)
                if current['status']!='publishing' or current['approval_hash']!=item['approval_hash']:return
                check_publication(self.store,db,current)
                # Only approved content is projected; no research notes or internal state.
                db.execute('INSERT INTO published VALUES(?,?,?)',(body['slug'],id,dumps(body)))
                db.execute("UPDATE items SET status='published' WHERE id=?",(id,))
                self.store.event(db,'Article approuvé publié sur le flux du blog.')
            return
        channels=json.loads(os.environ['POSTIZ_CHANNELS'])
        integrations=self.api('GET','/integrations')
        for channel in ('facebook','instagram'):
            target=channels[channel]
            if not any(i['id']==target and i['identifier']==channel and not i.get('disabled') for i in integrations):raise Conflict('Le canal '+channel+' n’est pas connecté.')
        # Media upload does not publish a post. The file is copied into Postiz storage.
        with open(self.store.root/'media'/item['media']['media'],'rb') as file:
            media=self.api('POST','/upload',files={'file':(item['media']['media'],file,'image/png')})
        for channel in ('facebook','instagram'):
            delivery_id=uid()
            with self.store.db() as db:
                if db.execute('SELECT 1 FROM deliveries WHERE item_id=? AND revision=? AND channel=?',(id,item['revision'],channel)).fetchone():continue
                if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':raise Conflict('Publication suspendue. Vérifiez les livraisons déjà engagées avant reprise.')
                db.execute("INSERT INTO deliveries VALUES(?,?,?,?,'sending','{}',?)",(delivery_id,id,item['revision'],channel,now()))
            payload={'type':'schedule' if due>datetime.now(timezone.utc) else 'now','shortLink':False,'date':item['scheduled_at'],'tags':[],'posts':[{'integration':{'id':channels[channel]},'value':[{'content':item['content'][channel],'image':[{'id':media['id'],'path':media['path'],'alt':item['content'].get('alt','')}]}],'settings':{'__type':channel,'post_type':'post'}}]}
            try:
                result=self.api('POST','/posts',json=payload)
                entries=result if isinstance(result,list) else [result]
                if not entries or any(not isinstance(entry,dict) or not (entry.get('postId') or entry.get('id')) for entry in entries):
                    raise Conflict('Postiz n’a pas confirmé les identifiants des publications.')
            except Exception:
                # POST has no guaranteed idempotency key: an ambiguous result is NEVER retried.
                with self.store.db() as db:
                    db.execute("UPDATE deliveries SET status='uncertain',updated=? WHERE id=?",(now(),delivery_id))
                raise Conflict('Résultat d’envoi incertain pour '+channel+'. Vérifiez Postiz avant toute nouvelle tentative.')
            with self.store.db() as db:db.execute("UPDATE deliveries SET status='submitted',result=?,updated=? WHERE id=?",(dumps(result),now(),delivery_id))
        with self.store.db() as db:
            db.execute("UPDATE items SET status='scheduled' WHERE id=?",(id,));self.store.event(db,'Contenu approuvé programmé dans le calendrier Postiz à la date validée.')
    def reconcile(self):
        with self.store.db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM deliveries WHERE status='submitted'")]
        if not rows:return
        dates=[self.store.item(r['item_id'])['scheduled_at'] for r in rows]
        start=(datetime.fromisoformat(min(dates))-timedelta(days=2)).isoformat()
        end=(max(datetime.now(timezone.utc),max(datetime.fromisoformat(d) for d in dates))+timedelta(days=2)).isoformat()
        data=self.api('GET','/posts',params={'startDate':start,'endDate':end})
        posts={p['id']:p for p in data.get('posts',[])}
        for row in rows:
            result=json.loads(row['result']);result=result if isinstance(result,list) else [result]
            ids=[x.get('postId') or x.get('id') for x in result if isinstance(x,dict)]
            states=[posts.get(id,{}).get('state') for id in ids]
            status='published' if states and all(s=='PUBLISHED' for s in states) else 'failed' if 'ERROR' in states else 'submitted'
            with self.store.db() as db:
                db.execute('UPDATE deliveries SET status=?,updated=? WHERE id=?',(status,now(),row['id']))
                allrows=list(db.execute('SELECT status FROM deliveries WHERE item_id=? AND revision=?',(row['item_id'],row['revision'])))
                if len(allrows)==2 and all(r[0]=='published' for r in allrows):db.execute("UPDATE items SET status='published' WHERE id=?",(row['item_id'],))
                elif any(r[0]=='failed' for r in allrows):db.execute("UPDATE items SET status='blocked',error='Un réseau a refusé la publication. Consultez Postiz ; aucune relance automatique.' WHERE id=?",(row['item_id'],))

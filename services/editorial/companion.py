"""Owner-authorized article derived from one approved social revision."""
import json
from datetime import datetime, timezone
from store import Conflict, dumps, now, uid


def authorize(store,db,parent,actor,enabled):
    old=db.execute('SELECT * FROM companion_articles WHERE parent_id=?',(parent['id'],)).fetchone()
    if old and store.item(old['article_id'],db)['status']=='published':return old['article_id']
    if not enabled:
        if old:
            db.execute("UPDATE companion_articles SET state='revoked' WHERE parent_id=?",(parent['id'],))
            db.execute("UPDATE items SET status='blocked',approval_hash=NULL,error='Autorisation automatique retirée sur le post associé.' WHERE id=?",(old['article_id'],))
            db.execute("DELETE FROM jobs WHERE target=? AND status='queued'",(old['article_id'],))
        return None
    if parent['kind']!='social':raise Conflict('Cette option est réservée aux posts Facebook/Instagram.')
    source=parent['content'];product=parent['media'].get('product_snapshot')
    demand=db.execute('SELECT conversation_id,brief FROM demand_items WHERE item_id=?',(parent['id'],)).fetchone()
    cid=demand['conversation_id'] if demand else uid()
    if not demand:db.execute('INSERT INTO conversations VALUES(?,?,?)',(cid,'Article associé · '+source['title'][:60],now()))
    article_id=old['article_id'] if old else uid()
    brief={'title':source['title'],'kind':'product' if product else 'advice','query':'','product_id':product['id'] if product else None,'angle':'Développez en un article de blog utile le post approuvé ci-dessous. Conservez le sujet et les faits vérifiés ; approfondissez avec des conseils et des sources fabricant. Ne présentez pas un test personnel ni des faits commerciaux nouveaux. Ne rédigez aucun prix : le logiciel ajoute le prix validé si applicable.\n'+dumps({k:source.get(k) for k in ('title','facebook','instagram','sources')}),'scene':source.get('scene','Un décor musical chaleureux, charte Planète Laser'),'scheduled_at':parent['scheduled_at'],'photo_ids':json.loads(demand['brief']).get('photo_ids',[]) if demand else [],'price':None,'instruction':'','format':'blog'}
    # Persist a frozen product/brief from the approved post, not a fresh product match.
    if old:
        child=store.item(article_id,db)
        if child['status'] in ('queued','generating','rendering','publishing'):raise Conflict('L’article associé est déjà en préparation. Attendez sa fin avant de relancer cette option.')
        store.snapshot(db,child);revision=child['revision']+1
        db.execute("UPDATE items SET revision=?,status='queued',content='{}',media='{}',scheduled_at=?,approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=NULL WHERE id=?",(revision,parent['scheduled_at'],article_id))
        db.execute('UPDATE demand_items SET brief=?,product=? WHERE item_id=?',(dumps(brief),dumps(product) if product else None,article_id))
        db.execute('DELETE FROM jobs WHERE target=?',(article_id,))
    else:
        revision=1;message_id=uid()
        db.execute("INSERT INTO messages(id,conversation_id,role,body,status,created) VALUES(?,?,'user',?,'done',?)",(message_id,cid,'Article autorisé automatiquement depuis le post : '+source['title'],now()))
        slot=db.execute('SELECT count(*) FROM demand_items WHERE conversation_id=?',(cid,)).fetchone()[0]
        db.execute("INSERT INTO items(id,week_id,kind,slot,status,scheduled_at) VALUES(?,?,'blog',?,'queued',?)",(article_id,'demand:'+cid,slot,parent['scheduled_at']))
        db.execute('INSERT INTO demand_items VALUES(?,?,?,0,?,?)',(article_id,cid,message_id,dumps(brief),dumps(product) if product else None))
    db.execute("INSERT OR REPLACE INTO companion_articles(parent_id,article_id,parent_revision,parent_hash,actor,created,article_revision,state,auto_hash,source_snapshot) VALUES(?,?,?,?,?,?,?,'active',NULL,?)",(parent['id'],article_id,parent['revision'],parent['approval_hash'],actor,now(),revision,dumps(parent)))
    store.job(db,'companion',article_id)
    store.event(db,'Article associé autorisé : rédaction puis publication automatique sans deuxième validation.',actor)
    return article_id


def require_authorization(store,db,article_id):
    grant=db.execute('SELECT * FROM companion_articles WHERE article_id=?',(article_id,)).fetchone()
    if not grant or grant['state']!='active':raise Conflict('L’autorisation de publication de cet article a été retirée.')
    parent=store.item(grant['parent_id'],db);child=store.item(article_id,db)
    if parent['revision']!=grant['parent_revision'] or parent['approval_hash']!=grant['parent_hash'] or store.content_hash(parent)!=grant['parent_hash']:
        raise Conflict('Le post associé a changé ou sa validation a été retirée. Article conservé sans publication automatique.')
    if child['revision']!=grant['article_revision']:raise Conflict('L’article a été modifié après la demande automatique. Relisez cette version avant publication.')
    return grant


def check_publication(store,db,item):
    row=db.execute('SELECT auto_hash FROM companion_articles WHERE article_id=?',(item['id'],)).fetchone()
    if row and row['auto_hash'] and row['auto_hash']==item['approval_hash']:
        require_authorization(store,db,item['id'])


class Companion:
    def __init__(self,store,generator):self.store=store;self.generator=generator
    def run(self,article_id):
        with self.store.db() as db:
            require_authorization(self.store,db,article_id)
            item=self.store.item(article_id,db)
        if item['status'] in ('approved','published'):return
        if item['status']=='rendering':self.generator.render(article_id)
        elif item['status']!='review':self.generator.draft(article_id)
        with self.store.db() as db:
            grant=require_authorization(self.store,db,article_id)
            item=self.store.item(article_id,db)
            if item['status']!='review' or not item['media'].get('blog_media') or not item['media'].get('hashes'):raise Conflict('L’article ou ses images ne sont pas prêts.')
            # The owner already authorized this exact derivation. Seal its final
            # generated bytes for the normal publisher; never grant agent approval.
            due=datetime.now(timezone.utc).isoformat()
            item['scheduled_at']=due;approval=self.store.content_hash(item)
            db.execute("UPDATE items SET scheduled_at=?,status='approved',approval_hash=?,approved_by=?,approved_at=?,error=NULL WHERE id=?",(due,approval,grant['actor'],now(),article_id))
            db.execute('UPDATE companion_articles SET auto_hash=? WHERE article_id=?',(approval,article_id))
            self.store.snapshot(db,self.store.item(article_id,db))
            self.store.event(db,'Article associé rédigé : publication autorisée par la validation du post.',grant['actor'])

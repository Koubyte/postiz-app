"""Bind an agent-authored draft to one verified catalogue product, without generation."""
import json

from conversation import EDITABLE
from generation import Generator, bounded_text, product_price_text
from store import Conflict, dumps


def bind_catalogue_product(service, request_id, item_id, revision, query, price_mode='catalogue'):
    query = bounded_text(query, 600)
    if not query or price_mode not in ('hide', 'catalogue'):
        raise Conflict('Indiquez un produit précis et un mode de prix valide.')
    payload = {'operation': 'bind_catalogue_product', 'item_id': item_id,
               'revision': revision, 'query': query, 'price_mode': price_mode}
    store = service.store
    with store.db() as db:
        _, old = service.replay(db, request_id, payload)
        if old:
            return old
        item = store.item(item_id, db)
        store.check_revision(item, revision)
        if item['status'] not in EDITABLE:
            raise Conflict('Ce brouillon ne peut pas être modifié actuellement.')
        row = db.execute('SELECT brief,product FROM demand_items WHERE item_id=?', (item_id,)).fetchone()
        if not row:
            raise Conflict('Ce contenu ne possède pas de brief individuel.')
        if db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'", (item_id,)).fetchone():
            raise Conflict('Ce contenu a déjà été transmis à Postiz.')
        if db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')", (item_id,)).fetchone():
            raise Conflict('Une préparation est déjà en cours.')
        if row['product']:
            raise Conflict('Un produit est déjà associé à ce brouillon.')

    generator = service.postiz.publisher.generator if service.postiz else Generator(store)
    product = generator.match(query, generator.products(force=True))
    if not product:
        raise Conflict('Produit absent ou ambigu dans le catalogue ; précisez la référence exacte.')
    product = {**product, 'price_mode': price_mode}
    if price_mode == 'catalogue':
        product_price_text(product)

    with store.db() as db:
        fingerprint, old = service.replay(db, request_id, payload)
        if old:
            return old
        item = store.item(item_id, db)
        store.check_revision(item, revision)
        row = db.execute('SELECT brief,product FROM demand_items WHERE item_id=?', (item_id,)).fetchone()
        if (item['status'] not in EDITABLE or not row or row['product']
            or db.execute("SELECT 1 FROM deliveries WHERE item_id=? AND status!='failed'", (item_id,)).fetchone()
            or db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')", (item_id,)).fetchone()):
            raise Conflict('Le brouillon a changé pendant la recherche du produit.')
        brief = json.loads(row['brief'])
        brief.update(query=query, kind='product', product_id=product['id'], price_mode=price_mode)
        media = dict(item['media'])
        media['product_snapshot'] = product
        store.snapshot(db, item)
        db.execute('UPDATE demand_items SET brief=?,product=? WHERE item_id=?', (dumps(brief), dumps(product), item_id))
        db.execute("UPDATE items SET media=?,revision=revision+1,approval_hash=NULL,approved_by=NULL,approved_at=NULL WHERE id=?", (dumps(media), item_id))
        db.execute("UPDATE companion_articles SET state='revoked' WHERE parent_id=? AND article_id NOT IN (SELECT item_id FROM published)", (item_id,))
        result = {'item_id': item_id, 'revision': revision+1, 'status': item['status'],
                  'product': {k: product.get(k) for k in ('id', 'title', 'price', 'price_from', 'stock_status', 'available')},
                  'price_mode': price_mode, 'catalogue_revalidation': 'available' if price_mode == 'catalogue' else 'stock_only',
                  'note': 'Vérifiez que le prix et la disponibilité dans vos textes et votre visuel correspondent au catalogue.',
                  'requires_owner_approval': True}
        service.remember(db, request_id, fingerprint, result)
        store.event(db, 'Produit catalogue associé au brouillon sans réécriture ; validation requise.', 'grok-agent')
        return result

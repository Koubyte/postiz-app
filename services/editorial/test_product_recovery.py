"""Product recovery preserves owner copy, reference and price without publishing."""
import base64
import hashlib
import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from generation import GenerationError, product_price_text
from store import dumps, uid


def app_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITORIAL_DATA', str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER', 'false')
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    spec = importlib.util.spec_from_file_location('editorial_product_recovery', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.agent_service.calendar = lambda: []
    return module


def test_edit_failed_product_recovers_reference_price_and_exact_copy(tmp_path, monkeypatch):
    app = app_fixture(tmp_path, monkeypatch)
    date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = app.agent_service.prepare(uid(), 'Post ZEFIR', 'social', product_query='ZEFIR 12A', scheduled_at=date, price=499)
    identifier = created['item_id']
    with app.store.db() as db:
        demand = db.execute('SELECT conversation_id,brief FROM demand_items WHERE item_id=?', (identifier,)).fetchone()
    original = io.BytesIO()
    Image.new('RGB', (400, 300), 'orange').save(original, 'PNG')
    photo = app.conversation.photo(demand['conversation_id'], original.getvalue(), 'owner.png')
    visual_instructions = 'Conserver le produit exact. ' * 100 + 'FIN INSTRUCTIONS COMPLÈTES'
    brief = json.loads(demand['brief'])
    brief.update(photo_ids=[photo['id']], visual_instructions=visual_instructions)
    with app.store.db() as db:
        db.execute('UPDATE demand_items SET brief=? WHERE item_id=?', (dumps(brief), identifier))
        db.execute("UPDATE items SET status='failed',content='{}',media='{}' WHERE id=?", (identifier,))
    fields = {'title': 'ZEFIR 12A', 'headline': 'Ta sono prête à jouer', 'facebook': 'Texte exact Facebook',
              'instagram': 'Texte exact Instagram', 'alt': 'Enceinte en scène'}
    app.agent_service.edit(uid(), identifier, 1, fields)
    with app.store.db() as db:
        assert db.execute('SELECT kind FROM jobs WHERE target=?', (identifier,)).fetchone()[0] == 'demand_render'
    product = {'id': 'zefir', 'title': 'ZEFIR 12A', 'thumbnail': 'https://example.com/supplier.png', 'image_mask_required': True}
    monkeypatch.setattr(app.generator, 'products', lambda: [product])
    monkeypatch.setattr(app.generator, 'match', lambda query, catalogue: product)
    from test_scenes import directions
    monkeypatch.setattr(app.generator, 'ask', lambda _: directions())
    scene = io.BytesIO()
    Image.linear_gradient('L').resize((1024, 1536)).convert('RGB').save(scene, 'PNG')
    def bridge(path, payload, **kwargs):
        assert visual_instructions in payload['prompt']
        reference = base64.b64decode(payload['reference_image']['b64_json'])
        red, green, blue = Image.open(io.BytesIO(reference)).getpixel((100, 100))[:3]
        assert red > 245 and 155 < green < 175 and blue < 10
        return {'reference_image_sha256': hashlib.sha256(reference).hexdigest(),
                'data': [{'b64_json': base64.b64encode(scene.getvalue()).decode()}]}
    monkeypatch.setattr(app.generator, 'bridge', bridge)
    app.render_demand(identifier)
    result = app.store.item(identifier)
    assert result['status'] == 'review' and result['approval_hash'] is None
    assert result['content']['facebook'] == fields['facebook']
    assert result['content']['instagram'] == fields['instagram']
    assert result['content']['price_text'] == '499,00 € TTC'
    assert result['media']['provenance']['price_text'] == '499,00 € TTC'
    assert result['media']['provenance']['reference_used'] is True
    assert result['media']['product_snapshot']['id'] == 'zefir'
    with app.store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0] == 0


def test_product_render_without_resolved_reference_fails_closed(tmp_path, monkeypatch):
    app = app_fixture(tmp_path, monkeypatch)
    date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = app.agent_service.prepare(uid(), 'Post produit', 'social', product_query='ZEFIR 12A', scheduled_at=date)
    identifier = created['item_id']
    monkeypatch.setattr(app.generator, 'bridge', lambda *a, **k: pytest.fail('No image generation without product'))
    with pytest.raises(GenerationError, match='produit demandé'):
        app.generator.render(identifier)
    assert not app.store.item(identifier)['media']


@pytest.mark.parametrize('price,price_from,expected', [(499, False, '499,00 € TTC'), (None, False, None), (499, True, None)])
def test_requested_catalogue_price_requires_a_single_valid_store_price(tmp_path, monkeypatch, price, price_from, expected):
    app = app_fixture(tmp_path, monkeypatch)
    date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    item = app.agent_service.prepare(uid(), 'Post vente', 'social', product_query='ZEFIR 12A',
                                     scheduled_at=date, price_mode='catalogue')['item_id']
    product = {'id': 'zefir', 'title': 'ZEFIR 12A', 'price': price, 'price_from': price_from}
    monkeypatch.setattr(app.generator, 'products', lambda: [product])
    monkeypatch.setattr(app.generator, 'match', lambda query, catalogue: product)
    if expected:
        assert product_price_text(app.conversation.resolve_product(item)) == expected
    else:
        with pytest.raises(GenerationError):app.conversation.resolve_product(item)
        with app.store.db() as db:
            assert db.execute('SELECT product FROM demand_items WHERE item_id=?', (item,)).fetchone()[0] is None


@pytest.mark.parametrize('owner_supplied', [True, False])
def test_supplier_restriction_does_not_block_owner_reference(tmp_path, monkeypatch, owner_supplied):
    app = app_fixture(tmp_path, monkeypatch)
    date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = app.agent_service.prepare(uid(), 'Post produit', 'social', product_query='ZEFIR 12A',
        scheduled_at=date, reference_image_url='https://example.com/owner.png',
        reference_source_url='https://example.com/source', reference_owner_supplied=owner_supplied)
    product = {'id':'zefir','title':'ZEFIR 12A','thumbnail':'https://example.com/supplier.png',
               'image_mask_required':True}
    monkeypatch.setattr(app.generator, 'products', lambda:[product])
    monkeypatch.setattr(app.generator, 'match', lambda query, catalogue:product)
    image=io.BytesIO(); Image.new('RGB',(100,100),'orange').save(image,'PNG')
    monkeypatch.setattr('net.public_bytes',lambda *args:image.getvalue())
    if not owner_supplied:
        with pytest.raises(GenerationError, match='restriction photo'):
            app.conversation.resolve_product(created['item_id'])
        return
    resolved=app.conversation.resolve_product(created['item_id'])
    assert resolved['supplier_image_mask_required'] is True
    assert resolved['image_mask_required'] is False
    assert resolved['reference_images'][0]['url']=='https://example.com/owner.png'

"""Real shop photos and a rotating staging keep the visuals varied and anchored in the shop."""
import base64
import hashlib
import io
import json

import pytest
from PIL import Image

import generation
from agent import AgentService
from generation import Generator, GenerationError
from scenes import add_scene, checked_staging, delete_scene, list_scenes, next_template, plan_staging, update_scene
from store import Conflict, dumps, uid
from test_scenes import directions
from test_workflow import create_item, store  # noqa: F401  (fixture)


def photo(color='sienna', size=(1200, 900)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='PNG')
    return buffer.getvalue()


def test_library_normalises_deduplicates_edits_and_deletes(store):
    sofa = add_scene(store, photo(), 'Canapés chesterfield', 'Deux canapés en cuir face au mur de guitares', ['guitares', 'Claviers'])
    assert sofa['filename'].endswith('.jpg') and sofa['tags'] == ['guitares', 'claviers'] and sofa['active']
    assert (store.root / 'media' / sofa['filename']).read_bytes()[:3] == b'\xff\xd8\xff'
    assert add_scene(store, photo(), 'Doublon')['duplicate']
    assert len(list_scenes(store)) == 1
    with pytest.raises(Conflict):
        add_scene(store, photo(size=(400, 300)), 'Trop petite')
    paused = update_scene(store, sofa['id'], {'active': False, 'label': 'Coin canapés'})
    assert not paused['active'] and paused['label'] == 'Coin canapés'
    assert list_scenes(store, include_inactive=False) == []
    delete_scene(store, sofa['id'])
    assert not (store.root / 'media' / sofa['filename']).exists() and list_scenes(store) == []


def test_explicit_choices_are_checked(store):
    with pytest.raises(Conflict, match='photo du magasin'):
        checked_staging(store, 'store')
    scene = add_scene(store, photo(), 'Scène du magasin')
    assert checked_staging(store, 'auto', 'auto') == (None, None)
    assert checked_staging(store, 'in_use', scene['id']) == ('in_use', scene['id'])
    with pytest.raises(Conflict):
        checked_staging(store, 'lifestyle', scene['id'])
    with pytest.raises(Conflict):
        checked_staging(store, 'cinema')


def test_rotation_changes_staging_place_and_matches_tags(store):
    guitars = add_scene(store, photo('sienna'), 'Mur de guitares', '', ['guitare'])
    sofa = add_scene(store, photo('navy'), 'Canapés', '', ['tous'])
    drums = add_scene(store, photo('olive'), 'Coin batterie', '', ['batterie'])
    item = {'id': 'x', 'content': {'title': 'Fender Player II Stratocaster'}}
    product = {'title': 'Guitare électrique Fender Player II'}
    first = plan_staging(store, item, {}, product, [])
    assert first['staging'] == 'store' and first['store_scene']['id'] in (guitars['id'], sofa['id'])
    history = [{'staging': first['staging'], 'store_scene_id': first['store_scene']['id']}]
    second = plan_staging(store, item, {}, product, history)
    assert second['staging'] != first['staging']
    assert second['store_scene']['id'] != first['store_scene']['id'] and second['store_scene']['id'] != drums['id']
    forced = plan_staging(store, {'id': 'y', 'content': {'staging': 'lifestyle'}}, {}, product, [])
    assert forced == {'staging': 'lifestyle', 'store_scene': None}


def test_without_shop_photos_the_store_staging_is_never_picked(store):
    plan = plan_staging(store, {'id': 'x', 'content': {}}, {}, {'title': 'Piano'}, [])
    assert plan['staging'] != 'store' and plan['store_scene'] is None


def test_templates_alternate_when_none_is_chosen(store):
    first = next_template(store, True)
    identifier = create_item(store)
    with store.db() as db:
        content = store.item(identifier, db)['content']
        db.execute('UPDATE items SET content=? WHERE id=?', (dumps({**content, 'template': first}), identifier))
    assert next_template(store, True) != first
    assert next_template(store, False) in ('classic', 'minimal', 'raw', 'tip_card')


def test_shop_photo_travels_as_a_location_reference(store, monkeypatch):
    scene = add_scene(store, photo('navy'), 'Canapés chesterfield', 'Canapés en cuir sur un tapis rouge', ['tous'])
    product_ref = photo('orange', (400, 300))
    identifier = create_item(store)
    with store.db() as db:
        row = store.item(identifier, db)
        product = {'id': 'guitar', 'title': 'Guitare test', 'thumbnail': 'https://example.com/g.png'}
        db.execute('UPDATE weeks SET plan=? WHERE id=?', (dumps({'subjects': [{'kind': 'product', 'product_id': 'guitar'}], 'products': [product]}), row['week_id']))
        db.execute("UPDATE items SET content=?,status='rendering' WHERE id=?", (dumps({**row['content'], 'product_id': 'guitar', 'staging': 'store'}), identifier))
    monkeypatch.setattr(generation, 'public_bytes', lambda url, *args: product_ref)
    background = io.BytesIO()
    Image.linear_gradient('L').resize((1024, 1536)).convert('RGB').save(background, format='PNG')
    sent = {}

    def bridge(path, payload, **kwargs):
        sent.update(payload)
        refs = [base64.b64decode(r['b64_json']) for r in payload['reference_images']]
        return {'reference_images_sha256': [hashlib.sha256(r).hexdigest() for r in refs],
                'data': [{'b64_json': base64.b64encode(background.getvalue()).decode()}]}
    gen = Generator(store)
    monkeypatch.setattr(gen, 'ask', lambda _: directions())
    monkeypatch.setattr(gen, 'bridge', bridge)
    gen.render(identifier)
    roles = [r.get('role', 'product') for r in sent['reference_images']]
    assert roles == ['product', 'scene'] and sent['reference_images'][1]['mime_type'] == 'image/jpeg'
    assert 'MISE EN SCÈNE · dans le magasin' in sent['prompt'] and 'Canapés chesterfield' in sent['prompt']
    assert 'Pas de fausse photo de notre magasin' not in sent['prompt']
    item = store.item(identifier)
    direction = item['media']['visual_direction']
    assert direction['staging'] == 'store' and direction['store_scene_id'] == scene['id'] and direction['store_scene_attached']
    assert direction['setting'] == 'store' and item['content']['template'] in ('classic', 'minimal', 'raw')
    assert list_scenes(store)[0]['recent_uses'] == 1

    def scene_not_acknowledged(path, payload, **kwargs):
        result = bridge(path, payload, **kwargs)
        result['reference_images_sha256'] = result['reference_images_sha256'][:1]
        return result
    monkeypatch.setattr(gen, 'bridge', scene_not_acknowledged)
    with store.db() as db:
        db.execute("UPDATE items SET status='rendering' WHERE id=?", (identifier,))
    with pytest.raises(GenerationError):
        gen.render(identifier)


def test_grok_can_add_list_and_pause_shop_photos(store, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    service = AgentService(store, lambda: [])
    request_id = uid()
    added = service.add_store_photo(request_id, 'Comptoir', 'Le comptoir avec les pédales', ['accessoires'],
                                    image_base64=base64.b64encode(photo()).decode())
    assert service.add_store_photo(request_id, 'Comptoir', 'Le comptoir avec les pédales', ['accessoires'],
                                   image_base64=base64.b64encode(photo()).decode()) == added
    listed = service.store_scenes()
    assert [s['label'] for s in listed['scenes']] == ['Comptoir'] and 'in_use' in listed['stagings']
    assert 'url' not in listed['scenes'][0] and 'filename' not in listed['scenes'][0]
    assert service.context()['scenes'][0]['id'] == added['id']
    assert not service.update_store_scene(uid(), added['id'], active=False)['active']
    with pytest.raises(Conflict):
        service.add_store_photo(uid(), 'Rien', image_base64=None, image_url=None)


def test_catalogue_category_matches_tagged_places(store):
    armchair = add_scene(store, photo('sienna'), 'Fauteuil cuir', '', ['guitares', 'basses'])
    stage = add_scene(store, photo('navy'), 'Vitrine scène', '', ['claviers', 'pianos'])
    guitar = {'title': 'Fender Player II Stratocaster RW Birch Green',
              'url': 'https://planetelaser.fr/instruments/guitares-basses/fender-player-ii-strat-rw-birch-green'}
    piano = {'title': 'Casio PX-S1100 Blanc', 'url': 'https://planetelaser.fr/instruments/pianos-claviers/casio-px-s1100-blanc'}
    item = {'id': 'x', 'content': {}}
    assert plan_staging(store, item, {}, guitar, [])['store_scene']['id'] == armchair['id']
    assert plan_staging(store, item, {}, piano, [])['store_scene']['id'] == stage['id']

"""Integration tests for Studio IA v2 owner API endpoints, CSRF/auth checks, and SEO/visual updates."""
import hashlib
import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import sys
sys.path.insert(0, str(Path(__file__).parent))
import media
from store import dumps
from test_workflow import content, create_item


def _future(hours=10):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _png_bytes(size=(800, 600), color=(30, 80, 120)) -> bytes:
    img = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, size[0] - 100, size[1] - 100), fill=(210, 80, 60))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _load_app(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITORIAL_DATA', str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER', 'false')
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    spec = importlib.util.spec_from_file_location('test_owner_v2_app', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owner_api_v2_auth_rules_catalogue_activity_and_requests(tmp_path, monkeypatch):
    module = _load_app(tmp_path, monkeypatch)
    headers = {'Origin': 'https://postiz.example.com', 'X-Editorial-Action': '1'}

    with TestClient(module.app, base_url='https://postiz.example.com') as client:
        # 401 unauthenticated without cookie
        assert client.get('/editorial/api/rules').status_code == 401
        assert client.post('/editorial/api/rules', headers=headers, json={'custom_instructions': 'x'}).status_code == 401

        async def owner(_):
            return 'owner'
        monkeypatch.setattr(module, 'actor', owner)

        # 403 missing CSRF headers
        assert client.post('/editorial/api/rules', json={'custom_instructions': 'test'}).status_code == 403
        assert client.post('/editorial/api/rules', headers={'Origin': 'https://evil.example.com', 'X-Editorial-Action': '1'}, json={'custom_instructions': 'test'}).status_code == 403

        # Rules roundtrip + injection into agent-connection instructions
        saved = client.post('/editorial/api/rules', headers=headers, json={
            'custom_instructions': 'Mentionner l’atelier luthier de Forbach.',
            'default_template': 'tip_card',
            'signature_note': 'Planète Laser · 57600 Forbach',
            'weekly_blog_link': True,
        })
        assert saved.status_code == 200
        assert saved.json()['default_template'] == 'tip_card'
        assert client.get('/editorial/api/rules').json()['signature_note'] == 'Planète Laser · 57600 Forbach'

        conn = client.get('/editorial/api/agent-connection').json()
        assert conn['rules']['weekly_blog_link'] is True
        assert 'Mentionner l’atelier luthier de Forbach.' in conn['instructions']

        # Catalogue search endpoint
        monkeypatch.setattr(module.agent_service._generator(), 'products', lambda force=False: [
            {'id': 'y1', 'title': 'Yamaha P-145', 'ean': '4957812', 'price': 449.0, 'price_from': 449.0,
             'stock_status': 'in_stock', 'stock_quantity': 2, 'available': True, 'category': 'Pianos',
             'description': 'Piano numérique', 'url': 'https://planetelaser.fr/p/p145', 'thumbnail': '', 'image_mask_required': False},
        ])
        cat = client.get('/editorial/api/catalogue?q=Yamaha&in_stock=true').json()
        assert cat['total'] == 1 and cat['products'][0]['id'] == 'y1'

        # Product request create + delete + Grok activity feed
        req_id = client.post('/editorial/api/requests', headers=headers, json={'query': 'Yamaha P-145'}).json()['id']
        assert client.post(f'/editorial/api/requests/{req_id}/delete', headers=headers, json={}).status_code == 200
        assert client.post(f'/editorial/api/requests/{req_id}/delete', headers=headers, json={}).status_code == 409

        with module.store.db() as db:
            module.store.event(db, 'Brouillon créé par Grok', 'grok-agent')
        act = client.get('/editorial/api/agent-activity').json()
        assert act['events'][0]['message'] == 'Brouillon créé par Grok'
        assert set(act['stats']) == {'review', 'queued', 'published', 'week_status'}


def test_owner_api_v2_items_save_visual_upload_ai_revise_delete_and_published(tmp_path, monkeypatch):
    module = _load_app(tmp_path, monkeypatch)
    headers = {'Origin': 'https://postiz.example.com', 'X-Editorial-Action': '1'}

    async def owner(_):
        return 'owner'
    monkeypatch.setattr(module, 'actor', owner)

    with TestClient(module.app, base_url='https://postiz.example.com') as client:
        # Seed a blog draft and test save + clearing optional SEO metadata
        blog_id = create_item(module.store, 'blog', status='review')
        r1 = client.post(f'/editorial/api/items/{blog_id}/save', headers=headers, json={
            'revision': 1,
            'scheduled_at': _future(12),
            'content': {
                **content('blog'),
                'seo_title': 'Guide micro <= 60 car.',
                'seo_description': 'Description SEO Google complète pour musiciens.',
                'tags': ['micro', 'studio'],
            },
        })
        assert r1.status_code == 200
        detail = client.get(f'/editorial/api/contents/{blog_id}').json()
        assert detail['content']['seo_title'] == 'Guide micro <= 60 car.'
        assert detail['content']['tags'] == ['micro', 'studio']

        # Clear optional SEO fields cleanly
        r2 = client.post(f'/editorial/api/items/{blog_id}/save', headers=headers, json={
            'revision': 2,
            'scheduled_at': _future(14),
            'content': {**detail['content'], 'seo_title': '', 'tags': []},
        })
        assert r2.status_code == 200
        cleared = client.get(f'/editorial/api/contents/{blog_id}').json()
        assert 'seo_title' not in cleared['content'] and 'tags' not in cleared['content']

        # Social item with background for visual recomposite, ai-revise, upload-image, delete
        social_id = create_item(module.store, 'social', status='review')
        media_dir = module.store.root / 'media'
        assets = media.render_assets(
            item_id=social_id, product=None, background=_png_bytes((900, 900)),
            content={'headline': 'Essai live', 'kind': 'conseil'}, output_dir=media_dir, template='classic',
        )
        assets['hashes'] = {
            k: hashlib.sha256((media_dir / assets[k]).read_bytes()).hexdigest()
            for k in ('media', 'blog_media', 'background_media')
        }
        with module.store.db() as db:
            db.execute('UPDATE items SET media=?, revision=1 WHERE id=?', (dumps(assets), social_id))

        # Visual recomposite + carousel
        vis = client.post(f'/editorial/api/items/{social_id}/visual', headers=headers, json={
            'revision': 1,
            'template': 'minimal',
            'carousel_slides': [{'headline': 'Page 1', 'body': ''}, {'headline': 'Page 2', 'body': 'Astuce'}],
            'recomposite_only': True,
        })
        assert vis.status_code == 200
        assert vis.json()['result']['carousel_slide_count'] == 2
        assert len(vis.json()['item']['carousel_media_urls']) == 2
        assert client.post(f'/editorial/api/items/{social_id}/visual', headers=headers, json={'revision': 1, 'template': 'raw', 'recomposite_only': True}).status_code == 409

        # Upload final image
        up_final = client.post(
            f'/editorial/api/items/{social_id}/upload-image',
            headers={**headers, 'X-Item-Revision': '2', 'X-Image-Purpose': 'final', 'X-File-Name': 'custom.png'},
            content=_png_bytes((900, 900), (10, 20, 30)),
        )
        assert up_final.status_code == 200 and up_final.json()['item']['revision'] == 3

        # Upload reference image on weekly item queues render
        up_ref = client.post(
            f'/editorial/api/items/{social_id}/upload-image',
            headers={**headers, 'X-Item-Revision': '3', 'X-Image-Purpose': 'reference', 'X-File-Name': 'ref.png'},
            content=_png_bytes((900, 900), (80, 90, 100)),
        )
        assert up_ref.status_code == 200 and up_ref.json()['result']['status'] == 'queued'

        # AI revise scope='text'
        with module.store.db() as db:
            db.execute("UPDATE items SET status='review' WHERE id=?", (social_id,))
        ai_rev = client.post(f'/editorial/api/items/{social_id}/ai-revise', headers=headers, json={
            'revision': 4, 'instruction': 'Plus direct', 'scope': 'text',
        })
        assert ai_rev.status_code == 200 and ai_rev.json()['result']['scope'] == 'text'

        # Delete draft + verify 409 on stale revision / nonexistent
        with module.store.db() as db:
            db.execute("UPDATE items SET status='review' WHERE id=?", (social_id,))
        assert client.post(f'/editorial/api/items/{social_id}/delete', headers=headers, json={'revision': 99}).status_code == 409
        assert client.post(f'/editorial/api/items/{social_id}/delete', headers=headers, json={'revision': 5}).status_code == 200
        assert client.get(f'/editorial/api/contents/{social_id}').status_code == 409

        # Published article update endpoint with extended SEO fields + public feed check
        pub_body = {
            'slug': 'article-live', 'title': 'Titre avant', 'excerpt': 'Résumé avant',
            'content': '## Guide\n\nCorps initial.', 'category': 'guides', 'tags': ['son'],
            'imageUrl': 'https://postiz.example.com/editorial/public/media/cover.png',
            'createdAt': '2030-10-01T10:00:00Z', 'updatedAt': '2030-10-01T10:00:00Z',
        }
        with module.store.db() as db:
            db.execute("UPDATE items SET status='published', revision=3 WHERE id=?", (blog_id,))
            db.execute('INSERT INTO published VALUES(?,?,?)', ('article-live', blog_id, dumps(pub_body)))
        upd = client.post(f'/editorial/api/items/{blog_id}/update-published', headers=headers, json={
            'revision': 3,
            'title': 'Titre après SEO',
            'seo_title': 'Titre Google optimisé',
            'seo_description': 'Meta description optimisée.',
            'tags': ['son', 'forbach'],
            'category': 'actualites',
            'markdown': '## Guide\n\nContenu enrichi.',
        })
        assert upd.status_code == 200
        assert upd.json()['item']['content']['seo_title'] == 'Titre Google optimisé'
        public_list = client.get('/editorial/public/articles').json()['articles']
        live_art = next(a for a in public_list if a['slug'] == 'article-live')
        assert live_art['title'] == 'Titre après SEO'
        assert live_art['seoTitle'] == 'Titre Google optimisé'
        assert live_art['tags'] == ['son', 'forbach']

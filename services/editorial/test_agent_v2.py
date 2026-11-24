"""Tests for v2 Grok Bot autonomy, compact context, rules, weekly control, and direct/hybrid drafts."""
import hashlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import media
from agent import AgentService
from store import Conflict, Store, dumps, uid
from test_workflow import content, create_item


def _future(hours=6):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _png_bytes(size=(800, 600), color=(45, 95, 70)) -> bytes:
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, size[0] - 80, size[1] - 80), fill=(180, 60, 75))
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def _seed_plan_review_week(store: Store, week_str='2030-11-04'):
    week_id = store.prepare(week_str)
    products = [
        {'id': 'p1', 'title': 'Guitare Yamaha C40'},
        {'id': 'p2', 'title': 'Micro Shure SM58'},
        {'id': 'p3', 'title': 'Piano Casio CDP-S110'},
    ]
    subjects = []
    for slot in range(7):
        subjects.append({
            'slot': slot,
            'kind': 'product' if slot < 3 else 'advice',
            'title': f'Sujet {slot + 1}',
            'angle': f'Angle éditorial {slot + 1}',
            'product_id': products[slot]['id'] if slot < 3 else None,
            'scene': f'Scène magasin {slot + 1}',
            'scheduled_at': _future(24 * (slot + 1)),
        })
    plan = {
        'products': products,
        'subjects': subjects,
        'article': {
            'title': 'Bien débuter en home studio',
            'angle': 'Guide pratique complet pour musiciens',
            'product_id': 'p2',
            'social_slot': 1,
            'scheduled_at': _future(48),
        },
        'sources': [],
        'unresolved_requests': [],
    }
    with store.db() as db:
        db.execute("UPDATE weeks SET status='plan_review', plan=?, revision=1 WHERE id=?", (dumps(plan), week_id))
    return week_id, plan


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    return AgentService(Store(tmp_path), lambda: [])


def test_context_is_compact_and_includes_rules_and_requests(service):
    service.store.save_rules(
        {
            'custom_instructions': 'Toujours inviter à tester au magasin de Forbach.',
            'default_template': 'minimal',
            'signature_note': 'Planète Laser · Forbach',
            'weekly_blog_link': True,
        },
        'owner',
    )
    req_id = service.store.add_request('Yamaha P-145', 'Pour débutants', 'catalogue', None, 'high', 'owner')
    item_id = create_item(service.store, 'blog')

    ctx = service.context()
    assert 'Toujours inviter à tester au magasin de Forbach.' in ctx['instructions']
    assert ctx['editorial_rules']['default_template'] == 'minimal'
    assert ctx['editorial_rules']['weekly_blog_link'] is True
    assert set(ctx['visual_templates']) == {'classic', 'minimal', 'raw', 'tip_card'}
    assert any(r['id'] == req_id and r['query'] == 'Yamaha P-145' for r in ctx['pending_requests'])

    summary_item = next(i for i in ctx['items'] if i['id'] == item_id)
    assert summary_item['title'] == 'Choisir un micro'
    for forbidden in ('content', 'markdown', 'facebook', 'instagram', 'approval_hash', 'search_text'):
        assert forbidden not in summary_item


def test_catalogue_search_contents_published_and_rules(service, monkeypatch):
    sample_products = [
        {'id': 'p1', 'title': 'Guitare Yamaha C40', 'ean': '4957812', 'price': 149.0, 'price_from': 149.0,
         'stock_status': 'in_stock', 'stock_quantity': 4, 'available': True, 'category': 'Guitares',
         'description': 'Guitare classique débutant', 'url': 'https://planetelaser.fr/p/c40', 'thumbnail': '', 'image_mask_required': False},
        {'id': 'p2', 'title': 'Micro Shure SM58', 'ean': '042406', 'price': 109.0, 'price_from': 109.0,
         'stock_status': 'out_of_stock', 'stock_quantity': 0, 'available': False, 'category': 'Micros',
         'description': 'Micro scène légendaire', 'url': 'https://planetelaser.fr/p/sm58', 'thumbnail': '', 'image_mask_required': False},
    ]
    monkeypatch.setattr(service._generator(), 'products', lambda force=False: sample_products)

    res = service.search_catalogue(query='yamaha', in_stock_only=True, min_price=100, max_price=200)
    assert res['total'] == 1
    assert res['products'][0]['id'] == 'p1'

    res_all = service.search_catalogue(category='micros', in_stock_only=False)
    assert res_all['total'] == 1 and res_all['products'][0]['id'] == 'p2'

    # Published article inspection by slug or item_id
    blog_id = create_item(service.store, 'blog', status='published')
    pub_body = {
        'slug': 'choisir-micro-studio',
        'title': 'Choisir son micro studio',
        'excerpt': 'Intro',
        'content': '## Guide\n\nContenu détaillé.',
        'category': 'guides',
        'tags': ['micro', 'studio'],
        'seoTitle': 'Micro studio | Planète Laser',
        'seoDescription': 'Comparatif pratique.',
        'imageUrl': 'https://postiz.example.com/editorial/public/media/cover.png',
        'updatedAt': '2030-10-01T10:00:00Z',
    }
    with service.store.db() as db:
        db.execute('INSERT INTO published VALUES(?,?,?)', ('choisir-micro-studio', blog_id, dumps(pub_body)))

    by_slug = service.get_published_article('choisir-micro-studio')
    by_id = service.get_published_article(blog_id)
    assert by_slug == by_id
    assert by_slug['seo_title'] == 'Micro studio | Planète Laser'
    assert by_slug['tags'] == ['micro', 'studio']

    found = service.search_contents(query='micro', filter='published')
    assert found['total'] == 1 and found['items'][0]['id'] == blog_id
    assert service.get_editorial_rules()['default_template'] == 'minimal'


def test_week_plan_full_autonomy_lifecycle(service):
    # Product request add / replay / delete
    req_key = uid()
    req = service.add_product_request(req_key, 'Enceinte JBL EON', note='Pour soirée', price_mode='hide', priority='high')
    assert req == service.add_product_request(req_key, 'Enceinte JBL EON', note='Pour soirée', price_mode='hide', priority='high')
    service.delete_product_request(uid(), req['id'])
    with pytest.raises(Conflict):
        service.delete_product_request(uid(), req['id'])

    week_id, _ = _seed_plan_review_week(service.store)
    up_key = uid()
    updated = service.update_week_plan(
        up_key, week_id, 1,
        subjects=[{'slot': 0, 'title': 'Guitare C40 révisée', 'angle': 'Angle neuf'}],
        article={'title': 'Article studio mis à jour'},
    )
    assert updated['revision'] == 2
    assert updated == service.update_week_plan(
        up_key, week_id, 1,
        subjects=[{'slot': 0, 'title': 'Guitare C40 révisée', 'angle': 'Angle neuf'}],
        article={'title': 'Article studio mis à jour'},
    )

    # Approve week without waiting on UI click (replay safe)
    app_key = uid()
    approved = service.approve_week_plan(app_key, week_id, 2)
    assert approved['status'] == 'generating'
    assert approved == service.approve_week_plan(app_key, week_id, 2)
    with service.store.db() as db:
        jobs = db.execute("SELECT kind, target FROM jobs WHERE kind='draft'").fetchall()
        assert len(jobs) == 8  # 7 social + 1 blog, none published automatically

    # Separate week for revise_week_slot & retry_week_plan
    week2, _ = _seed_plan_review_week(service.store, '2030-11-11')
    rev_res = service.revise_week_slot(uid(), week2, 2, 1, instruction='Axer sur les répétitions')
    assert rev_res['status'] == 'revising'
    with service.store.db() as db:
        db.execute("UPDATE weeks SET status='failed', revision=2 WHERE id=?", (week2,))
    retry_res = service.retry_week_plan(uid(), week2, 2)
    assert retry_res['status'] == 'preparing'


def test_direct_draft_visual_generation_and_text_vs_visual_revise(service):
    # Direct social draft with generate_visual=True queues demand_render
    direct = service.create_direct(
        uid(), 'social',
        {
            'title': 'Post direct minimal',
            'headline': 'Son cristallin en concert',
            'facebook': 'Découvrez comment régler votre micro sur scène.',
            'instagram': 'Astuce scène du jour ! Enregistrez ce post.',
            'alt': 'Micro sur scène',
            'template': 'minimal',
            'sources': [{'title': 'Fiche technique', 'url': 'https://planetelaser.fr'}],
        },
        scheduled_at=_future(8),
        generate_visual=True,
        template='minimal',
        visual_instructions='Ambiance club sombre avec halo vert',
    )
    item_id = direct['item_id']
    assert direct['status'] == 'queued'
    with service.store.db() as db:
        job = db.execute('SELECT kind FROM jobs WHERE target=?', (item_id,)).fetchone()
        assert job['kind'] == 'demand_render'
        db.execute('DELETE FROM jobs WHERE target=?', (item_id,))

    # Seed generated background + media hashes and run generate_visual(recomposite_only=True)
    media_dir = service.store.root / 'media'
    assets = media.render_assets(
        item_id=item_id,
        product=None,
        background=_png_bytes((900, 900)),
        content={'headline': 'Son cristallin en concert', 'kind': 'advice'},
        output_dir=media_dir,
        template='minimal',
    )
    assets['hashes'] = {
        k: hashlib.sha256((media_dir / assets[k]).read_bytes()).hexdigest()
        for k in ('media', 'blog_media', 'background_media')
    }
    with service.store.db() as db:
        db.execute("UPDATE items SET media=?, status='review', revision=1 WHERE id=?", (dumps(assets), item_id))

    slides = [
        {'headline': '1 · Positionnement', 'body': ''},
        {'headline': '2 · Gain d’entrée', 'body': 'Laissez 12 dB de marge.'},
        {'headline': '3 · Filtre passe-haut', 'body': 'Coupez sous 100 Hz.'},
    ]
    recomp = service.generate_visual(
        uid(), item_id, 1, template='raw', carousel_slides=slides, recomposite_only=True
    )
    assert recomp['status'] == 'review'
    assert recomp['recomposited'] is True
    assert recomp['carousel_slide_count'] == 3
    detail = service.content(item_id)
    assert detail['template'] == 'raw'
    assert detail['carousel_slide_count'] == 3
    assert detail['has_background'] is True

    # revise(scope='text') preserves media and queues draft_text
    rev_text = service.revise(uid(), item_id, 2, 'Raccourcis la fin du texte Facebook', scope='text')
    assert rev_text['status'] == 'queued' and rev_text['scope'] == 'text'
    with service.store.db() as db:
        assert db.execute('SELECT kind FROM jobs WHERE target=?', (item_id,)).fetchone()['kind'] == 'draft_text'
        assert json.loads(db.execute('SELECT media FROM items WHERE id=?', (item_id,)).fetchone()[0])['carousel_media']

    # revise(scope='visual') clears media and queues render without wiping texts
    with service.store.db() as db:
        db.execute('DELETE FROM jobs WHERE target=?', (item_id,))
        db.execute("UPDATE items SET status='review' WHERE id=?", (item_id,))
    rev_vis = service.revise(uid(), item_id, 3, 'Plus contrasté', scope='visual')
    assert rev_vis['status'] == 'queued' and rev_vis['recomposited'] is False
    with service.store.db() as db:
        assert db.execute('SELECT kind FROM jobs WHERE target=?', (item_id,)).fetchone()['kind'] == 'demand_render'


def test_reject_retry_delete_published_seo_and_social_guard(service):
    item_id = create_item(service.store, 'social', status='review')
    rejected = service.reject_content(uid(), item_id, 1, note='Accroche à retravailler')
    assert rejected['status'] == 'rejected'
    retried = service.retry_content(uid(), item_id, 2)
    assert retried['status'] == 'queued'

    # delete_draft succeeds on review/queued non-delivered drafts (wait: status 'review' / 'rejected')
    with service.store.db() as db:
        db.execute("UPDATE items SET status='review', revision=4 WHERE id=?", (item_id,))
    deleted = service.delete_draft(uid(), item_id, 4)
    assert deleted['deleted'] is True
    with pytest.raises(Conflict):
        service.store.item(item_id)

    # delete_draft refuses approved item
    approved_id = create_item(service.store, 'social', status='approved')
    with pytest.raises(Conflict):
        service.delete_draft(uid(), approved_id, 1)

    # Published article update by slug works cleanly and preserves preview/approval guard elsewhere
    blog_id = create_item(service.store, 'blog', status='published')
    pub_body = {
        'slug': 'mon-article-seo', 'title': 'Ancien titre', 'excerpt': 'Ancien résumé',
        'content': '## Intro\n\nParagraphe initial.', 'category': 'guides',
        'tags': ['guitare'], 'imageUrl': 'https://postiz.example.com/editorial/public/media/cover.png',
        'createdAt': '2030-10-01T10:00:00Z', 'updatedAt': '2030-10-01T10:00:00Z',
    }
    with service.store.db() as db:
        db.execute('INSERT INTO published VALUES(?,?,?)', ('mon-article-seo', blog_id, dumps(pub_body)))

    up = service.update_published_article(
        uid(), 'mon-article-seo', 1,
        title='Nouveau titre SEO',
        seo_title='Titre Google parfait <= 60 car.',
        seo_description='Meta description complète pour attirer les musiciens en Moselle-Est.',
        tags=['guitare', 'forbach'],
        markdown='## Intro\n\nTexte mis à jour avec [lien interne](/blog/autre-article).',
    )
    assert up['revision'] == 2
    refreshed = service.get_published_article('mon-article-seo')
    assert refreshed['title'] == 'Nouveau titre SEO'
    assert refreshed['seo_title'] == 'Titre Google parfait <= 60 car.'
    assert refreshed['tags'] == ['guitare', 'forbach']

    # Social approval guard stays strict: cannot approve without visual preview and owner confirmation
    s2 = service.create_direct(
        uid(), 'social',
        {'title': 'Post sécurité', 'headline': 'Sécurité', 'facebook': 'Texte FB complet', 'instagram': 'Texte IG'},
        scheduled_at=_future(12),
    )
    with service.store.db() as db:
        db.execute("UPDATE items SET status='review' WHERE id=?", (s2['item_id'],))
    detail = service.content(s2['item_id'])
    with pytest.raises(Conflict):
        service.approve(uid(), s2['item_id'], detail['revision'], detail['review_token'], 'Oui vas-y', False)
    with pytest.raises(Conflict):
        service.approve(uid(), s2['item_id'], detail['revision'], detail['review_token'], 'Oui vas-y', True)

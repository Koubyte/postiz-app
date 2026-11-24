"""Tests for v2 visual templates, multi-slide carousels, recomposition, and Postiz/blog delivery."""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import media
from publisher import Publisher
from store import Conflict, Store, dumps
from test_workflow import content, create_item, fake_api, make_due


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def _bg_bytes() -> bytes:
    image = Image.new('RGB', (900, 900))
    draw = ImageDraw.Draw(image)
    for y in range(900):
        draw.line((0, y, 900, y), fill=(25 + y // 12, 35 + y // 15, 45 + y // 18))
    draw.rectangle((320, 260, 620, 640), fill=(40, 80, 150))
    return _png_bytes(image)


def _ref_bytes() -> bytes:
    image = Image.new('RGB', (300, 500), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 50, 230, 440), fill=(170, 45, 55))
    return _png_bytes(image)


def _sample_product():
    return {
        'id': 'p1',
        'title': 'Yamaha P-145',
        'thumbnail': 'https://example.com/p145.png',
        'ean': '4957812690000',
        'price_mode': 'catalogue',
        'price': 449.0,
    }


def test_four_templates_produce_distinct_valid_outputs(tmp_path):
    outputs = {}
    for tpl in ('classic', 'minimal', 'raw', 'tip_card'):
        out_dir = tmp_path / tpl
        res = media.render_assets(
            item_id=f'item-{tpl}',
            product=_sample_product(),
            background=_bg_bytes(),
            content={'headline': 'Accord parfait en répétition', 'kind': 'product', 'price_text': '449 €'},
            output_dir=out_dir,
            product_reference=_ref_bytes(),
            reference_used=True,
            template=tpl,
        )
        social = Image.open(out_dir / res['media'])
        blog = Image.open(out_dir / res['blog_media'])
        assert social.size == (1080, 1350)
        assert blog.size == (1600, 900)
        assert (out_dir / res['background_media']).is_file()
        assert res['provenance']['template'] == tpl
        outputs[tpl] = social.convert('RGB').tobytes()

    assert len(set(outputs.values())) == 4


@pytest.mark.parametrize('slide_count', [2, 3, 5])
def test_carousel_two_to_five_slides(tmp_path, slide_count):
    slides = [{'headline': f'Étape {i + 1}', 'body': f'Détail pratique {i + 1}.'} for i in range(slide_count)]
    res = media.render_carousel(
        item_id='car-ok',
        slides=slides,
        background=_bg_bytes(),
        content={'headline': 'Guide micro', 'kind': 'conseil'},
        product=None,
        output_dir=tmp_path,
        template='minimal',
    )
    assert len(res['carousel_media']) == slide_count
    assert res['media'] == res['carousel_media'][0]
    assert (tmp_path / res['blog_media']).is_file()
    for fname in res['carousel_media']:
        assert Image.open(tmp_path / fname).size == (1080, 1350)


@pytest.mark.parametrize('bad_slides', [
    [],
    [{'headline': 'Une seule page', 'body': 'Trop court'}],
    [{'headline': f'Page {i}', 'body': ''} for i in range(6)],
])
def test_carousel_rejects_invalid_slide_counts(tmp_path, bad_slides):
    with pytest.raises(media.MediaBlocked):
        media.render_carousel(
            item_id='car-bad',
            slides=bad_slides,
            background=_bg_bytes(),
            content={'headline': 'Test', 'kind': 'advice'},
            product=None,
            output_dir=tmp_path,
        )


def test_recomposite_item_media_without_ai_and_synthetic_tip_card(tmp_path):
    store = Store(tmp_path)
    media_dir = store.root / 'media'
    initial = media.render_assets(
        item_id='recomp-1',
        product=_sample_product(),
        background=_bg_bytes(),
        content={'headline': 'Tester le son', 'kind': 'product'},
        output_dir=media_dir,
        product_reference=_ref_bytes(),
        reference_used=True,
        template='classic',
    )
    initial['hashes'] = {
        k: hashlib.sha256((media_dir / initial[k]).read_bytes()).hexdigest()
        for k in ('media', 'blog_media', 'source_media', 'background_media')
    }
    initial['product_snapshot'] = _sample_product()

    slides = [
        {'headline': '3 réglages clés', 'body': ''},
        {'headline': '1. Gain modéré', 'body': 'Évite la saturation dès la prise.'},
        {'headline': '2. Distance 20 cm', 'body': 'Gardez du relief naturel.'},
    ]
    item = {
        'id': 'recomp-1',
        'revision': 2,
        'content': {'headline': '3 réglages clés', 'kind': 'product', 'template': 'raw', 'carousel_slides': slides},
        'media': initial,
    }
    updated = media.recomposite_item_media(store, item, _sample_product())
    assert len(updated['carousel_media']) == 3
    assert updated['provenance']['template'] == 'raw'
    assert all(f'carousel_{i}' in updated['hashes'] for i in range(3))

    # Tampered background fails integrity check cleanly.
    (media_dir / initial['background_media']).write_bytes(b'corrupted')
    with pytest.raises(media.MediaBlocked, match='modifiée'):
        media.recomposite_item_media(store, item, _sample_product())

    # Synthetic background allows non-product tip_card without prior background_media.
    synth = media.make_synthetic_card_background()
    assert Image.open(io.BytesIO(synth)).size == (1080, 1350)
    advice_item = {
        'id': 'advice-1',
        'revision': 1,
        'content': {'headline': 'Astuce corde', 'kind': 'conseil', 'template': 'tip_card'},
        'media': {},
    }
    tip_assets = media.recomposite_item_media(store, advice_item, None)
    assert tip_assets['provenance']['template'] == 'tip_card'
    assert Image.open(media_dir / tip_assets['media']).size == (1080, 1350)


def test_publisher_check_carousel_and_deliver_multi_image_and_blog_seo(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    store = Store(tmp_path)
    pub = Publisher(store, generator=type('Gen', (), {'products': lambda self, force=False: []})())

    # 1. Social multi-image carousel upload + hash tamper detection
    item_id = create_item(store, 'social')
    media_dir = store.root / 'media'
    car_assets = media.render_carousel(
        item_id=item_id,
        slides=[{'headline': 'Slide 1', 'body': ''}, {'headline': 'Slide 2', 'body': 'Astuce'}],
        background=_bg_bytes(),
        content={'headline': 'Slide 1', 'kind': 'conseil'},
        product=None,
        output_dir=media_dir,
    )
    hashes = {
        'media': hashlib.sha256((media_dir / car_assets['media']).read_bytes()).hexdigest(),
        'blog_media': hashlib.sha256((media_dir / car_assets['blog_media']).read_bytes()).hexdigest(),
        'background_media': hashlib.sha256((media_dir / car_assets['background_media']).read_bytes()).hexdigest(),
        'carousel_0': hashlib.sha256((media_dir / car_assets['carousel_media'][0]).read_bytes()).hexdigest(),
        'carousel_1': hashlib.sha256((media_dir / car_assets['carousel_media'][1]).read_bytes()).hexdigest(),
    }
    car_assets['hashes'] = hashes
    with store.db() as db:
        db.execute('UPDATE items SET media=? WHERE id=?', (dumps(car_assets), item_id))
    store.approve_item(item_id, 1, 'owner', True)

    calls = fake_api(monkeypatch, pub)
    make_due(monkeypatch, store.item(item_id))
    pub.deliver(item_id)
    upload_calls = [c for c in calls if c[1] == '/upload']
    post_calls = [c for c in calls if c[1] == '/posts']
    assert len(upload_calls) == 2
    assert len(post_calls) == 2
    for _, _, kw in post_calls:
        assert len(kw['json']['posts'][0]['value'][0]['image']) == 2

    # Hash check catches modified carousel file
    tamper_snap = store.item(item_id)
    with store.db() as db:
        db.execute(
            "INSERT INTO items(id,week_id,kind,slot,status,content,media,scheduled_at) VALUES(?,?,?,?,?,?,?,?)",
            ('car-tamper', tamper_snap['week_id'], 'social', 1, 'review', dumps(content('social')), dumps(car_assets), tamper_snap['scheduled_at']),
        )
    store.approve_item('car-tamper', 1, 'owner', True)
    (media_dir / car_assets['carousel_media'][1]).write_bytes(b'altered-slide')
    with pytest.raises(Conflict, match='changé'):
        pub.check(store.item('car-tamper'))

    # 2. Blog delivery preserves SEO metadata only when provided
    blog_id = create_item(store, 'blog')
    blog_content = {**content('blog'), 'seo_title': 'Guide micro studio | Planète Laser', 'seo_description': 'Comparez les micros studio à Forbach.', 'tags': ['micro', 'studio']}
    store.save_item(blog_id, 1, blog_content, store.item(blog_id)['scheduled_at'], 'owner')
    store.approve_item(blog_id, 2, 'owner', True)
    make_due(monkeypatch, store.item(blog_id))
    pub.deliver(blog_id)
    with store.db() as db:
        pub_body = json.loads(db.execute('SELECT body FROM published WHERE item_id=?', (blog_id,)).fetchone()[0])
    assert pub_body['seoTitle'] == 'Guide micro studio | Planète Laser'
    assert pub_body['seoDescription'] == 'Comparez les micros studio à Forbach.'
    assert pub_body['tags'] == ['micro', 'studio']

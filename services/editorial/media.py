"""Apply the Planète Laser charter to a complete reference-guided scene.

The generator receives the exact product reference before this renderer runs.
No product is segmented, pasted or reconstructed here. Approval includes the
source photo and generated scene because reference input cannot guarantee fidelity.
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat

ASSETS = Path(__file__).with_name('media-assets')
BRAND_VERSION = 'pl-social-v1'
TEMPLATES = ('classic', 'minimal', 'raw', 'tip_card')
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class MediaBlocked(ValueError):
    """Content needs a replacement source or a human visual decision."""


def _decode(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise MediaBlocked('Image absente ou trop volumineuse.')
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_IMAGE_PIXELS or min(opened.size) < 80:
                raise MediaBlocked('Dimensions de la photo source non exploitables.')
            opened.load()
            return ImageOps.exif_transpose(opened).convert('RGBA')
    except MediaBlocked:
        raise
    except Exception as exc:
        raise MediaBlocked('Image source invalide.') from exc


def _font(family: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f'{family}-semibold.ttf'), size=size)


def _wrap(draw, text, font, width):
    words = str(text).strip().split()
    lines, line = [], ''
    for word in words:
        if draw.textlength(word, font=font) > width:
            return None
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=font) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _title(draw, text, xy, width, max_lines, size, min_size, color='#F7F8F8'):
    for point in range(size, min_size-1, -2):
        font = _font('outfit', point)
        lines = _wrap(draw, text, font, width)
        if lines and len(lines) <= max_lines:
            draw.multiline_text(xy, '\n'.join(lines), font=font, fill=color, spacing=8, stroke_width=0)
            return len(lines) * (point+8)
    raise MediaBlocked('Titre trop long pour le gabarit ; raccourcir le titre du visuel.')


def _scene(scene: Image.Image, size: tuple[int,int]) -> Image.Image:
    """Crop/resize the whole generated scene; never paste a product over it."""
    return ImageOps.fit(scene.convert('RGB'), size, method=Image.Resampling.LANCZOS).convert('RGBA')


def _category_label(kind: str) -> str:
    labels = {'product': 'LE MATÉRIEL PREND VIE', 'produit': 'LE MATÉRIEL PREND VIE',
              'advice': 'LE BON GESTE', 'conseil': 'LE BON GESTE',
              'news': 'À DÉCOUVRIR', 'actualité': 'À DÉCOUVRIR'}
    return labels.get(str(kind or 'product').lower(), 'PLANÈTE LASER · FORBACH')


def _wrap_paragraphs(draw, text: str, font, width: int, max_lines: int) -> list[str] | None:
    lines: list[str] = []
    for raw_line in str(text or '').splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        wrapped = _wrap(draw, raw_line, font, width)
        if wrapped is None:
            return None
        lines.extend(wrapped)
        if len(lines) > max_lines:
            return None
    return lines


def _bottom_gradient(height: int, start_ratio: float = 0.52, max_alpha: int = 238) -> Image.Image:
    overlay = Image.new('RGBA', (1080, height), (5, 7, 6, 0))
    alpha = Image.new('L', (1, height), 0)
    start_y = int(height * start_ratio)
    span = max(1, height - start_y)
    px = alpha.load()
    for y in range(start_y, height):
        t = (y - start_y) / span
        px[0, y] = int(max_alpha * (t ** 1.35))
    overlay.putalpha(alpha.resize((1080, height)))
    return overlay


def _logo_pill(master: Image.Image, xy: tuple[int, int], max_size: tuple[int, int], alpha: int = 160) -> None:
    logo = Image.open(ASSETS / 'logo-rect.png').convert('RGBA')
    logo.thumbnail(max_size, Image.Resampling.LANCZOS)
    px, py = xy
    pill = Image.new('RGBA', master.size, (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pill)
    pdraw.rounded_rectangle((px - 14, py - 10, px + logo.width + 14, py + logo.height + 10), radius=14, fill=(3, 3, 3, alpha))
    master.alpha_composite(pill)
    master.alpha_composite(logo, (px, py))


def _draw_price_pill(draw: ImageDraw.ImageDraw, price: str, bottom_y: int = 1294) -> float:
    cleaned = str(price).strip()
    font = _font('inter', 36)
    width = draw.textlength(cleaned, font=font)
    if width > 420 or '\n' in cleaned:
        raise MediaBlocked('Prix trop long pour la pastille réservée.')
    draw.rounded_rectangle((1020 - width - 32, bottom_y - 64, 1020, bottom_y), radius=12, fill='#00FF9D')
    draw.text((1020 - width - 16, bottom_y - 52), cleaned, font=font, fill='#030303')
    return width + 80


def _compose_social_master(background_image: Image.Image, product: dict | None, content: dict, template: str) -> Image.Image:
    chosen = template if template in TEMPLATES else 'classic'
    if chosen == 'raw':
        master = _scene(background_image, (1080, 1350))
        logo = Image.open(ASSETS / 'logo-rect.png').convert('RGBA')
        logo.thumbnail((190, 84), Image.Resampling.LANCZOS)
        _logo_pill(master, (1080 - 48 - logo.width, 1350 - 44 - logo.height), (190, 84), alpha=145)
        return master

    headline = content.get('headline') or content.get('title')
    if not headline:
        raise MediaBlocked('Accroche du visuel absente.')
    model_title = product.get('title', '') if product else ''
    price = content.get('price_text')
    label = _category_label(content.get('kind', 'product'))

    if chosen == 'minimal':
        master = _scene(background_image, (1080, 1350))
        master.alpha_composite(_bottom_gradient(1350, start_ratio=0.50, max_alpha=240))
        _logo_pill(master, (64, 54), (220, 96), alpha=155)
        draw = ImageDraw.Draw(master)
        draw.rectangle((64, 988, 146, 995), fill='#00FF9D')
        draw.text((166, 974), label, font=_font('inter', 28), fill='#00FF9D')
        _title(draw, headline, (64, 1030), 952, 2, 62, 48)
        reserved = _draw_price_pill(draw, price, 1296) if price else 0
        if model_title:
            _title(draw, model_title, (64, 1220), min(900 - reserved, 850), 2, 34, 30, color='#D7DFDB')
        return master

    if chosen == 'tip_card':
        master = Image.new('RGBA', (1080, 1350), '#0A0D0C')
        top_strip = _scene(background_image, (1080, 390))
        master.alpha_composite(top_strip, (0, 0))
        fade = Image.new('RGBA', (1080, 390), (10, 13, 12, 0))
        alpha = Image.new('L', (1, 390), 0)
        apx = alpha.load()
        for y in range(390):
            apx[0, y] = int(255 * ((y / 389) ** 1.6))
        fade.putalpha(alpha.resize((1080, 390)))
        master.alpha_composite(fade, (0, 0))
        draw = ImageDraw.Draw(master)
        draw.rectangle((0, 0, 1080, 10), fill='#00FF9D')
        draw.rounded_rectangle((36, 36, 1044, 1314), radius=20, outline='#1F2925', width=2)
        draw.rectangle((72, 420, 160, 427), fill='#00FF9D')
        draw.text((180, 405), label, font=_font('inter', 28), fill='#00FF9D')
        used_h = _title(draw, headline, (72, 464), 936, 3, 62, 46)
        body_text = content.get('card_body') or content.get('excerpt') or model_title or ''
        if body_text:
            body_y = 464 + used_h + 26
            for pt in (38, 34, 30):
                bfont = _font('inter', pt)
                blines = _wrap_paragraphs(draw, body_text, bfont, 936, 8)
                if blines:
                    draw.multiline_text((72, body_y), '\n'.join(blines), font=bfont, fill='#D2DDD7', spacing=14)
                    break
        logo = Image.open(ASSETS / 'logo-rect.png').convert('RGBA')
        logo.thumbnail((196, 86), Image.Resampling.LANCZOS)
        master.alpha_composite(logo, (72, 1196))
        if price:
            _draw_price_pill(draw, price, 1272)
        else:
            footer_txt = 'PLANÈTE LASER · FORBACH'
            ffont = _font('inter', 24)
            fw = draw.textlength(footer_txt, font=ffont)
            draw.text((1008 - fw, 1228), footer_txt, font=ffont, fill='#8FA097')
        return master

    # Classic pl-social-v1 layout (byte-identical to original output).
    social = _scene(background_image,(1080,970))
    master = Image.new('RGBA',(1080,1350),'#0F0F0F')
    master.alpha_composite(social,(0,0))
    draw = ImageDraw.Draw(master)
    draw.rectangle((64,1004,156,1012),fill='#00FF9D')
    draw.text((178,990),label,font=_font('inter',32),fill='#00FF9D')
    _title(draw,headline,(64,1050),952,2,66,52)
    # Product reference is separate and never silently shortened or replaced.
    reserved_price_width = draw.textlength(str(price),font=_font('inter',36))+80 if price else 0
    if model_title:
        _title(draw,model_title,(64,1216),min(900-reserved_price_width,850),2,36,32,color='#C4CBC8')
    if price:
        price = str(price).strip()
        font = _font('inter',36)
        width = draw.textlength(price,font=font)
        if width > 420 or '\n' in price:
            raise MediaBlocked('Prix trop long pour la pastille réservée.')
        draw.rounded_rectangle((1020-width-32,1230,1020,1294),radius=12,fill='#00FF9D')
        draw.text((1020-width-16,1242),price,font=font,fill='#030303')
    logo = Image.open(ASSETS/'logo-rect.png').convert('RGBA')
    logo.thumbnail((250,110),Image.Resampling.LANCZOS)
    master.alpha_composite(logo,(64,58))
    return master


def _prepare_inputs(*, product: dict | None, background: bytes, content: dict, product_reference: bytes | None, reference_used: bool, product_references: list[bytes] | None):
    background_image = _decode(background)
    # Reject a white/blank generated packshot background; the scene must carry context.
    sample = background_image.convert('RGB').resize((80,80))
    stats = ImageStat.Stat(sample)
    if min(stats.mean) > 240 or max(stats.stddev) < 3:
        raise MediaBlocked('Le décor est blanc ou vide ; générer une vraie scène musicale.')
    if str(content.get('kind','')).lower() in ('store','magasin','team','équipe') and not content.get('real_scene_source'):
        raise MediaBlocked('Une publication magasin exige une photographie réelle documentée.')
    sources = []
    reference_bytes = []
    source_urls = []
    reference_labels = []
    source_url = None
    if product:
        if product.get('image_mask_required') not in (None, False, 0, '', 'false'):
            raise MediaBlocked('Image fournisseur protégée : utiliser une autre photo autorisée.')
        reference_bytes = product_references if product_references is not None else [product_reference]
        if (reference_used is not True or not isinstance(reference_bytes, list)
                or not 1 <= len(reference_bytes) <= 3
                or any(not isinstance(data, bytes) or not data for data in reference_bytes)):
            raise MediaBlocked('Une à trois photos du produit exact doivent être fournies au générateur avant la mise en scène.')
        if product_references is not None and product_reference is not None and product_reference != reference_bytes[0]:
            raise MediaBlocked('Les références du produit sont incohérentes.')
        sources = [_decode(data) for data in reference_bytes]
        reference_metadata = product.get('reference_images')
        if not isinstance(reference_metadata, list):reference_metadata = []
        fallback_url = product.get('reference_url') or product.get('thumbnail') or product.get('image_url')
        for index in range(len(sources)):
            metadata = reference_metadata[index] if index < len(reference_metadata) and isinstance(reference_metadata[index], dict) else {}
            source_urls.append(metadata.get('url') or (fallback_url if index == 0 else None))
            reference_labels.append(metadata.get('label'))
        source_url = source_urls[0]
    return background_image, sources, reference_bytes, source_urls, reference_labels, source_url


def _finalize_provenance(*, item_id: str, product: dict | None, background: bytes, background_image: Image.Image, content: dict, output_dir: Path, files: dict, sources: list, reference_bytes: list[bytes], source_url: str | None, source_urls: list, reference_labels: list, reference_used: bool, template: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    files_sha256 = {}
    for key, value in files.items():
        if key == 'carousel_media' and isinstance(value, list):
            for idx, fname in enumerate(value):
                files_sha256[f'carousel_{idx}'] = hashlib.sha256((output_dir / fname).read_bytes()).hexdigest()
        elif isinstance(value, str):
            files_sha256[key] = hashlib.sha256((output_dir / value).read_bytes()).hexdigest()
    price = str(content.get('price_text')).strip() if content.get('price_text') else None
    headline = content.get('headline') or content.get('title') or ''
    provenance = {
        'brand_version': BRAND_VERSION, 'template': template, 'item_id': item_id, 'source_url': source_url,
        'source_sha256': hashlib.sha256(reference_bytes[0]).hexdigest() if reference_bytes else None,
        'reference_sha256': [hashlib.sha256(data).hexdigest() for data in reference_bytes],
        'source_urls': source_urls, 'reference_labels': reference_labels,
        'background_sha256': hashlib.sha256(background).hexdigest(),
        'source_product_id': product.get('id') if product else None,
        'ean': product.get('ean') if product else None,
        'image_mode': 'reference-guided-generation' if product else 'scene-generation',
        'reference_used': bool(product) and reference_used is True,
        'product_rgb_repainted': bool(product),
        'product_transforms': [],
        'scene_transforms': ['center-crop', 'uniform-scale'],
        'scene_source_size': list(background_image.size),
        'fidelity_requires_visual_review': bool(product),
        'price_text': price, 'headline': headline, 'alt': content.get('alt', ''),
        'image_rights': product.get('image_rights', 'catalogue — autorisation à vérifier à la validation') if product else None,
        'requires_visual_approval': True,
        'assets_sha256': json.loads((ASSETS / 'manifest.json').read_text()),
        'files_sha256': files_sha256,
    }
    files['provenance_media'] = f"{files['media'].split('-')[0]}-provenance.json"
    (output_dir / files['provenance_media']).write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    return {**files, 'provenance': provenance}


def render_assets(*, item_id: str, product: dict | None, background: bytes, content: dict, output_dir: Path, product_reference: bytes | None = None, reference_used: bool = False, product_references: list[bytes] | None = None, template: str | None = None) -> dict:
    """Render one social master and blog cover plus immutable review evidence.

    Requires explicit evidence that all supplied references were used for generation.
    product_references accepts one to three images and takes precedence over the
    legacy product_reference argument; if both are present their first image must match.
    `background` is the complete generated scene, including the product.
    The caller supplies the same reference bytes it sent to the image generator.
    `price_text` is already verified by the caller; omission hides price entirely.
    Files have random names and never derive a path from item_id or product input.
    """
    output_dir = Path(output_dir)
    chosen = template if template in TEMPLATES else (content.get('template') if content.get('template') in TEMPLATES else 'classic')
    background_image, sources, reference_bytes, source_urls, reference_labels, source_url = _prepare_inputs(
        product=product, background=background, content=content,
        product_reference=product_reference, reference_used=reference_used, product_references=product_references,
    )
    master = _compose_social_master(background_image, product, content, chosen)
    blog = _scene(background_image, (1600, 900))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = uuid.uuid4().hex
    files = {'media': f'{prefix}-social.png', 'blog_media': f'{prefix}-blog.png', 'background_media': f'{prefix}-background.png'}
    master.convert('RGB').save(output_dir / files['media'], optimize=True)
    blog.convert('RGB').save(output_dir / files['blog_media'], optimize=True)
    background_image.save(output_dir / files['background_media'])
    for index, source in enumerate(sources):
        field = 'source_media' if index == 0 else f'source_media_{index+1}'
        files[field] = f'{prefix}-source-{index+1}.png'
        source.save(output_dir / files[field])
    return _finalize_provenance(
        item_id=item_id, product=product, background=background, background_image=background_image,
        content=content, output_dir=output_dir, files=files, sources=sources,
        reference_bytes=reference_bytes, source_url=source_url, source_urls=source_urls,
        reference_labels=reference_labels, reference_used=reference_used, template=chosen,
    )


def render_carousel(*, item_id: str, slides: list[dict], background: bytes, content: dict, product: dict | None, output_dir: Path, template: str = 'minimal', product_reference: bytes | None = None, product_references: list[bytes] | None = None, reference_used: bool = False) -> dict:
    """Render a 2-to-5 slide 1080x1350 carousel with a photo cover and clean typography cards."""
    if not isinstance(slides, list) or not 2 <= len(slides) <= 5:
        raise MediaBlocked('Un carrousel doit contenir entre 2 et 5 pages.')
    clean_slides = []
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get('headline'), str) or not slide['headline'].strip():
            raise MediaBlocked('Chaque page du carrousel doit avoir un titre.')
        clean_slides.append({'headline': slide['headline'].strip(), 'body': str(slide.get('body') or '').strip()})
    output_dir = Path(output_dir)
    chosen = template if template in TEMPLATES else 'minimal'
    background_image, sources, reference_bytes, source_urls, reference_labels, source_url = _prepare_inputs(
        product=product, background=background, content=content,
        product_reference=product_reference, reference_used=reference_used, product_references=product_references,
    )
    total = len(clean_slides)
    prefix = uuid.uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=True)
    carousel_files: list[str] = []

    # Slide 1: hero visual + swipe indicator
    cover_content = {**content, 'headline': clean_slides[0]['headline'] or content.get('headline'), 'card_body': clean_slides[0]['body']}
    slide1 = _compose_social_master(background_image, product, cover_content, chosen)
    s1_draw = ImageDraw.Draw(slide1)
    pill_font = _font('inter', 26)
    indicator = f'1/{total} →'
    iw = s1_draw.textlength(indicator, font=pill_font)
    s1_draw.rounded_rectangle((1080 - 48 - iw - 32, 54, 1080 - 48, 106), radius=26, fill=(10, 13, 12, 225), outline='#00FF9D', width=2)
    s1_draw.text((1080 - 48 - iw - 16, 65), indicator, font=pill_font, fill='#F7F8F8')
    s1_name = f'{prefix}-slide-1.png'
    slide1.convert('RGB').save(output_dir / s1_name, optimize=True)
    carousel_files.append(s1_name)

    # Slides 2..N: crisp editorial cards
    for idx, slide in enumerate(clean_slides[1:], start=2):
        card = Image.new('RGBA', (1080, 1350), '#0A0D0C')
        cdraw = ImageDraw.Draw(card)
        cdraw.rectangle((0, 0, 1080, 10), fill='#00FF9D')
        cdraw.rounded_rectangle((36, 36, 1044, 1314), radius=20, outline='#1F2925', width=2)
        num_badge = f'{idx:02d} / {total:02d}'
        bfont = _font('inter', 28)
        bw = cdraw.textlength(num_badge, font=bfont)
        cdraw.rounded_rectangle((76, 86, 76 + bw + 34, 140), radius=12, fill='#0E241B', outline='#00FF9D', width=2)
        cdraw.text((93, 98), num_badge, font=bfont, fill='#00FF9D')
        kicker = _category_label(content.get('kind', 'advice'))
        cdraw.text((76 + bw + 56, 98), kicker, font=_font('inter', 26), fill='#8FA097')
        title_h = _title(cdraw, slide['headline'], (76, 192), 928, 3, 60, 44)
        body_y = 192 + title_h + 38
        if slide['body']:
            for pt in (40, 36, 32, 28):
                tfont = _font('inter', pt)
                tlines = _wrap_paragraphs(cdraw, slide['body'], tfont, 928, 12)
                if tlines:
                    cdraw.multiline_text((76, body_y), '\n'.join(tlines), font=tfont, fill='#D7E2DC', spacing=16)
                    break
        # Pagination dots
        dot_gap = 26
        dots_w = (total - 1) * dot_gap
        start_x = (1080 - dots_w) / 2
        for dot_i in range(total):
            cx = start_x + dot_i * dot_gap
            r = 8 if dot_i == idx - 1 else 6
            cdraw.ellipse((cx - r, 1244 - r, cx + r, 1244 + r), fill='#00FF9D' if dot_i == idx - 1 else '#2D3833')
        if idx == total:
            logo = Image.open(ASSETS / 'logo-rect.png').convert('RGBA')
            logo.thumbnail((180, 78), Image.Resampling.LANCZOS)
            card.alpha_composite(logo, (76, 1188))
        fname = f'{prefix}-slide-{idx}.png'
        card.convert('RGB').save(output_dir / fname, optimize=True)
        carousel_files.append(fname)

    blog = _scene(background_image, (1600, 900))
    files = {
        'media': s1_name,
        'carousel_media': carousel_files,
        'blog_media': f'{prefix}-blog.png',
        'background_media': f'{prefix}-background.png',
    }
    blog.convert('RGB').save(output_dir / files['blog_media'], optimize=True)
    background_image.save(output_dir / files['background_media'])
    for index, source in enumerate(sources):
        field = 'source_media' if index == 0 else f'source_media_{index+1}'
        files[field] = f'{prefix}-source-{index+1}.png'
        source.save(output_dir / files[field])
    return _finalize_provenance(
        item_id=item_id, product=product, background=background, background_image=background_image,
        content=cover_content, output_dir=output_dir, files=files, sources=sources,
        reference_bytes=reference_bytes, source_url=source_url, source_urls=source_urls,
        reference_labels=reference_labels, reference_used=reference_used, template=chosen,
    )


def make_synthetic_card_background() -> bytes:
    """Create a subtle textured dark green/charcoal gradient for text-first tip_card visuals."""
    img = Image.new('RGB', (1080, 1350), '#0A0D0C')
    draw = ImageDraw.Draw(img)
    for y in range(1350):
        t = y / 1349
        r = int(10 + 10 * (1 - t))
        g = int(13 + 28 * (1 - t))
        b = int(12 + 18 * (1 - t))
        draw.line((0, y, 1080, y), fill=(r, g, b))
    draw.ellipse((620, -140, 1260, 500), fill=(12, 42, 30))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def recomposite_item_media(store, item: dict, product: dict | None) -> dict:
    """Re-apply template and/or carousel layout onto an existing background without calling AI."""
    media_dir = store.root / 'media'
    old_media = item.get('media') or {}
    content = dict(item.get('content') or {})
    template = content.get('template') or 'classic'
    if template not in TEMPLATES:
        template = 'classic'
    bg_name = old_media.get('background_media')
    if bg_name:
        bg_path = media_dir / bg_name
        expected = (old_media.get('hashes') or {}).get('background_media')
        if not bg_path.is_file():
            raise MediaBlocked('Image de scène introuvable ; relancez la génération d’image.')
        background = bg_path.read_bytes()
        if expected and hashlib.sha256(background).hexdigest() != expected:
            raise MediaBlocked('Image de scène modifiée ; relancez la génération d’image.')
    elif template == 'tip_card' and not product:
        background = make_synthetic_card_background()
    else:
        raise MediaBlocked('Aucune image de scène réutilisable ; relancez la génération d’image.')

    ref_bytes: list[bytes] | None = None
    ref_used = False
    if product:
        ref_used = bool((old_media.get('provenance') or {}).get('reference_used'))
        collected = []
        for key in ('source_media', 'source_media_2', 'source_media_3'):
            fname = old_media.get(key)
            if fname and (media_dir / fname).is_file():
                collected.append((media_dir / fname).read_bytes())
        if not collected:
            raise MediaBlocked('Photo de référence produit manquante pour recomposer ce visuel.')
        ref_bytes = collected

    slides = content.get('carousel_slides') or []
    item_tag = f"{item['id']}-r{item['revision']}"
    if isinstance(slides, list) and len(slides) >= 2:
        assets = render_carousel(
            item_id=item_tag, slides=slides, background=background, content=content,
            product=product, output_dir=media_dir, template=template,
            product_references=ref_bytes, reference_used=ref_used,
        )
    else:
        assets = render_assets(
            item_id=item_tag, product=product, background=background, content=content,
            output_dir=media_dir, product_references=ref_bytes, reference_used=ref_used,
            template=template,
        )
    hashes = {}
    for key in ('media', 'blog_media', 'source_media', 'source_media_2', 'source_media_3', 'mask_media', 'background_media'):
        if assets.get(key):
            hashes[key] = hashlib.sha256((media_dir / assets[key]).read_bytes()).hexdigest()
    for idx, fname in enumerate(assets.get('carousel_media') or []):
        hashes[f'carousel_{idx}'] = hashlib.sha256((media_dir / fname).read_bytes()).hexdigest()
    assets['hashes'] = hashes
    if product or old_media.get('product_snapshot'):
        assets['product_snapshot'] = product or old_media.get('product_snapshot')
    assets['brand_version'] = BRAND_VERSION
    if old_media.get('visual_direction'):
        assets['visual_direction'] = old_media['visual_direction']
    return assets

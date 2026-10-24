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


def render_assets(*, item_id: str, product: dict | None, background: bytes, content: dict, output_dir: Path, product_reference: bytes | None = None, reference_used: bool = False, product_references: list[bytes] | None = None) -> dict:
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
    social = _scene(background_image,(1080,970))
    master = Image.new('RGBA',(1080,1350),'#0F0F0F')
    master.alpha_composite(social,(0,0))
    draw = ImageDraw.Draw(master)
    draw.rectangle((64,1004,156,1012),fill='#00FF9D')
    labels = {'product':'LE MATÉRIEL PREND VIE','produit':'LE MATÉRIEL PREND VIE','advice':'LE BON GESTE','conseil':'LE BON GESTE','news':'À DÉCOUVRIR','actualité':'À DÉCOUVRIR'}
    label = labels.get(str(content.get('kind','product')).lower(),'PLANÈTE LASER · FORBACH')
    draw.text((178,990),label,font=_font('inter',32),fill='#00FF9D')
    headline = content.get('headline') or content.get('title')
    if not headline:
        raise MediaBlocked('Accroche du visuel absente.')
    _title(draw,headline,(64,1050),952,2,66,52)
    # Product reference is separate and never silently shortened or replaced.
    model_title = product.get('title','') if product else ''
    price = content.get('price_text')
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
    blog = _scene(background_image,(1600,900))
    output_dir.mkdir(parents=True,exist_ok=True)
    prefix = uuid.uuid4().hex
    files = {'media':f'{prefix}-social.png','blog_media':f'{prefix}-blog.png','background_media':f'{prefix}-background.png'}
    master.convert('RGB').save(output_dir/files['media'],optimize=True)
    blog.convert('RGB').save(output_dir/files['blog_media'],optimize=True)
    background_image.save(output_dir/files['background_media'])
    for index, source in enumerate(sources):
        field = 'source_media' if index == 0 else f'source_media_{index+1}'
        files[field] = f'{prefix}-source-{index+1}.png'
        source.save(output_dir/files[field])
    provenance = {
        'brand_version':BRAND_VERSION,'item_id':item_id,'source_url':source_url,
        'source_sha256':hashlib.sha256(reference_bytes[0]).hexdigest() if reference_bytes else None,
        'reference_sha256':[hashlib.sha256(data).hexdigest() for data in reference_bytes],
        'source_urls':source_urls,'reference_labels':reference_labels,
        'background_sha256':hashlib.sha256(background).hexdigest(),
        'source_product_id':product.get('id') if product else None,
        'ean':product.get('ean') if product else None,
        'image_mode':'reference-guided-generation' if product else 'scene-generation',
        'reference_used':bool(product) and reference_used is True,
        'product_rgb_repainted':bool(product),
        'product_transforms':[],
        'scene_transforms':['center-crop','uniform-scale'],
        'scene_source_size':list(background_image.size),
        'fidelity_requires_visual_review':bool(product),
        'price_text':price or None,'headline':headline,'alt':content.get('alt',''),
        'image_rights':product.get('image_rights','catalogue — autorisation à vérifier à la validation') if product else None,
        'requires_visual_approval':True,
        'assets_sha256':json.loads((ASSETS/'manifest.json').read_text()),
        'files_sha256':{key:hashlib.sha256((output_dir/name).read_bytes()).hexdigest() for key,name in files.items()},
    }
    files['provenance_media'] = f'{prefix}-provenance.json'
    (output_dir/files['provenance_media']).write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    return {**files,'provenance':provenance}

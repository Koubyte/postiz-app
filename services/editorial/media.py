"""Deterministic Planète Laser assets; product RGB is never generated or retouched.

Backgrounds are generated separately. Approval must include the saved source,
mask and final composition: a segmentation mask cannot prove product identity.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

ASSETS = Path(__file__).with_name('media-assets')
BRAND_VERSION = 'pl-social-v1'
MAX_IMAGE_BYTES = 20 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000


class MediaBlocked(ValueError):
    """Content needs a replacement source or a human visual decision."""


def public_bytes(url: str, limit: int = MAX_IMAGE_BYTES) -> bytes:
    # Shared downloader pins public DNS addresses and revalidates redirects.
    from net import public_bytes as download
    return download(url, limit=limit)


def _decode(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise MediaBlocked('Image absente ou trop volumineuse.')
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > 24_000_000 or min(opened.size) < 80:
                raise MediaBlocked('Dimensions de la photo source non exploitables.')
            opened.load()
            return ImageOps.exif_transpose(opened).convert('RGBA')
    except MediaBlocked:
        raise
    except Exception as exc:
        raise MediaBlocked('Image source invalide.') from exc


def _white_mask(image: Image.Image) -> Image.Image:
    """Remove only near-white pixels connected to the edge, never enclosed whites.

    Conservative fallback for clean packshots; human mask review is mandatory.
    No source colors are changed. Work on a bounded thumbnail to limit memory.
    """
    small = image.convert('RGB')
    small.thumbnail((1200, 1200))
    w, h = small.size
    pix = small.load()
    def white(x, y):
        r, g, b = pix[x, y]
        return min(r, g, b) >= 245 and max(r, g, b) - min(r, g, b) <= 8
    edge = [(x, 0) for x in range(w)] + [(x, h-1) for x in range(w)]
    edge += [(0, y) for y in range(h)] + [(w-1, y) for y in range(h)]
    if sum(white(x, y) for x, y in edge) / len(edge) < .95:
        raise MediaBlocked('Détourage ambigu : fournir une photo détourée ou un packshot clair.')
    seen = bytearray(w*h)
    queue = deque()
    for x, y in edge:
        index = y*w+x
        if not seen[index] and white(x, y):
            seen[index] = 1
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for xx, yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if 0 <= xx < w and 0 <= yy < h:
                index = yy*w+xx
                if not seen[index] and white(xx, yy):
                    seen[index] = 1
                    queue.append((xx, yy))
    mask = Image.frombytes('L', (w,h), bytes(0 if value else 255 for value in seen))
    return mask.resize(image.size, Image.Resampling.NEAREST)


def _cutout(source: Image.Image) -> tuple[Image.Image, str]:
    alpha = source.getchannel('A')
    if alpha.getextrema()[0] < 250:
        mask, method = alpha, 'source-alpha'
    else:
        model = Path(os.environ.get('U2NET_HOME', '/models')) / 'u2netp.onnx'
        if model.is_file():
            # Never let rembg download a model in response to untrusted content.
            try:
                from rembg import new_session, remove
                mask = remove(source, session=new_session('u2net_custom', model_path=str(model.resolve()), providers=['CPUExecutionProvider']), only_mask=True).convert('L')
                method = 'rembg-u2netp'
            except Exception as exc:
                raise MediaBlocked('Le moteur de détourage a échoué ; remplacer la photo.') from exc
        else:
            mask, method = _white_mask(source), 'edge-connected-white'
    strong = mask.point(lambda value: 255 if value >= 200 else 0)
    bbox = strong.getbbox()
    fraction = ImageStat.Stat(strong).mean[0] / 255
    if not bbox or not .015 <= fraction <= .90:
        raise MediaBlocked('Masque produit vide, trop petit ou presque plein.')
    x0,y0,x1,y1 = bbox
    if min(x1-x0,y1-y0) < 24:
        raise MediaBlocked('Produit trop petit pour une composition fidèle.')
    if x0 == 0 or y0 == 0 or x1 == source.width or y1 == source.height:
        raise MediaBlocked('Le produit touche le bord : photo potentiellement tronquée.')
    product = source.copy()
    product.putalpha(mask)
    return product, method


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


def _scene(background: Image.Image, size: tuple[int,int], product: Image.Image | None):
    canvas = ImageOps.fit(background.convert('RGB'), size, method=Image.Resampling.LANCZOS).convert('RGBA')
    placement = None
    if product is not None:
        box = product.getchannel('A').getbbox()
        layer = product.crop(box)
        scale = min(size[0]*.70/layer.width, size[1]*.72/layer.height)
        layer = layer.resize((max(1,round(layer.width*scale)),max(1,round(layer.height*scale))), Image.Resampling.LANCZOS)
        x = (size[0]-layer.width)//2
        y = int(size[1]*.88)-layer.height
        shadow = Image.new('RGBA', size)
        shade = ImageDraw.Draw(shadow)
        shade.ellipse((x+layer.width*.08,y+layer.height-18,x+layer.width*.92,y+layer.height+25),fill=(0,0,0,110))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
        canvas.alpha_composite(layer,(x,y))
        placement = {'source_crop':list(box),'scale':scale,'xy':[x,y],'size':list(layer.size)}
    return canvas, placement


def render_assets(*, item_id: str, product: dict | None, background: bytes, content: dict, output_dir: Path) -> dict:
    """Render one social master and blog cover plus immutable review evidence.

    Raises MediaBlocked instead of inventing or silently omitting a product.
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
    product_image = source = None
    source_bytes = None
    source_url = None
    method = None
    if product:
        if product.get('image_mask_required') not in (None, False, 0, '', 'false'):
            raise MediaBlocked('Image fournisseur protégée : utiliser une autre photo autorisée.')
        source_url = product.get('thumbnail') or product.get('image_url')
        if not source_url:
            raise MediaBlocked('Aucune photo du produit exact disponible.')
        source_bytes = public_bytes(source_url, MAX_IMAGE_BYTES)
        source = _decode(source_bytes)
        product_image, method = _cutout(source)
    social, social_placement = _scene(background_image,(1080,970),product_image)
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
    blog, blog_placement = _scene(background_image,(1600,900),product_image)
    output_dir.mkdir(parents=True,exist_ok=True)
    prefix = uuid.uuid4().hex
    files = {'media':f'{prefix}-social.png','blog_media':f'{prefix}-blog.png','background_media':f'{prefix}-background.png'}
    master.convert('RGB').save(output_dir/files['media'],optimize=True)
    blog.convert('RGB').save(output_dir/files['blog_media'],optimize=True)
    background_image.save(output_dir/files['background_media'])
    if source is not None:
        files['source_media'] = f'{prefix}-source.png'
        files['mask_media'] = f'{prefix}-mask.png'
        source.save(output_dir/files['source_media'])
        product_image.getchannel('A').save(output_dir/files['mask_media'])
    provenance = {
        'brand_version':BRAND_VERSION,'item_id':item_id,'source_url':source_url,
        'source_sha256':hashlib.sha256(source_bytes).hexdigest() if source_bytes else None,
        'background_sha256':hashlib.sha256(background).hexdigest(),
        'source_product_id':product.get('id') if product else None,
        'ean':product.get('ean') if product else None,
        'mask_method':method,'product_rgb_repainted':False,
        'product_transforms':['alpha-mask','uniform-scale','translation'] if product else [],
        'placements':{'social':social_placement,'blog':blog_placement},
        'price_text':price or None,'headline':headline,'alt':content.get('alt',''),
        'image_rights':product.get('image_rights','catalogue — autorisation à vérifier à la validation') if product else None,
        'requires_visual_approval':True,
        'assets_sha256':json.loads((ASSETS/'manifest.json').read_text()),
        'files_sha256':{key:hashlib.sha256((output_dir/name).read_bytes()).hexdigest() for key,name in files.items()},
    }
    files['provenance_media'] = f'{prefix}-provenance.json'
    (output_dir/files['provenance_media']).write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    return {**files,'provenance':provenance}

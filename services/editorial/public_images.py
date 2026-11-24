"""Public, revocable WebP derivatives; approved source files remain untouched."""
from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps

DERIVATIVE_SUFFIX = '.v2.webp'
SUPPORTED_DERIVATIVE_SUFFIXES = ('.v1.webp', DERIVATIVE_SUFFIX)
_lock = threading.Lock()


def optimized_article(article: dict, public_url: str) -> dict:
    """Expose a versioned URL for images hosted by this editorial service."""
    image_url = article.get('imageUrl')
    base = public_url.rstrip('/') + '/editorial/public/media/'
    if not public_url or not isinstance(image_url, str) or not image_url.startswith(base):
        return article
    name = image_url[len(base):]
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or Path(name).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        return article
    return {**article, 'imageUrl': image_url + DERIVATIVE_SUFFIX}


def public_image_path(root: Path, name: str, articles: list[dict]) -> Path | None:
    """Resolve only published assets, generating a WebP derivative on first use."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        return None
    published = set()
    for article in articles:
        image_url = article.get('imageUrl')
        if isinstance(image_url, str):
            published.add(urlsplit(image_url).path.rsplit('/', 1)[-1])
    if name in published:
        source = root / 'media' / name
        return source if source.is_file() else None
    suffix = next((suffix for suffix in SUPPORTED_DERIVATIVE_SUFFIXES if name.endswith(suffix)), None)
    if suffix is None:
        return None
    original = name[:-len(suffix)]
    if original not in published or Path(original).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        return None
    source = root / 'media' / original
    if not source.is_file():
        return None
    directory = root / 'public-image-cache'
    target = directory / name
    with _lock:
        # Render again if a source is ever replaced, without touching the original.
        if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return target
        directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix='.webp', delete=False) as output:
                temporary = Path(output.name)
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image)
                    has_alpha = 'A' in image.getbands() or 'transparency' in image.info
                    image = image.convert('RGBA' if has_alpha else 'RGB')
                    image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    image.save(output, format='WEBP', quality=80, method=4)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return target

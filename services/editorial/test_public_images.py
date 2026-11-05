import hashlib
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def test_published_blog_images_are_webp_cached_and_revocable(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA', str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER', 'false')
    spec = importlib.util.spec_from_file_location('public_images_test_app', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    media = tmp_path / 'media'
    media.mkdir(exist_ok=True)
    source = media / 'approved-blog.png'
    Image.new('RGB', (1600, 900), (32, 128, 80)).save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    Image.new('RGB', (200, 200), 'red').save(media / 'draft.png')
    published = [{'slug': 'guide', 'imageUrl': 'https://postiz.example.com/editorial/public/media/approved-blog.png'}]
    monkeypatch.setattr(module.store, 'public_articles', lambda: published)

    with TestClient(module.app) as client:
        feed = client.get('/editorial/public/articles')
        assert feed.headers['cache-control'] == 'no-store'
        assert feed.json()['articles'][0]['imageUrl'].endswith('/approved-blog.png.v1.webp')
        assert published[0]['imageUrl'].endswith('/approved-blog.png')

        image = client.get('/editorial/public/media/approved-blog.png.v1.webp')
        assert image.status_code == 200
        assert image.headers['content-type'] == 'image/webp'
        assert image.headers['cache-control'] == 'public, max-age=3600'
        with Image.open(tmp_path / 'public-image-cache' / 'approved-blog.png.v1.webp') as converted:
            assert converted.format == 'WEBP'
            assert converted.size == (1200, 675)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        assert client.get('/editorial/public/media/approved-blog.png').status_code == 200

        for path in ('/editorial/public/media/draft.png', '/editorial/public/media/draft.png.v1.webp'):
            response = client.get(path)
            assert response.status_code == 404
            assert response.headers['cache-control'] == 'no-store'
        private = client.get('/editorial/media/approved-blog.png')
        assert private.status_code == 401
        assert private.headers['cache-control'] == 'no-store'

        published.clear()
        revoked = client.get('/editorial/public/media/approved-blog.png.v1.webp')
        assert revoked.status_code == 404
        assert revoked.headers['cache-control'] == 'no-store'


def test_external_and_existing_webp_urls_are_left_alone():
    from public_images import optimized_article
    for url in ('https://elsewhere.example/image.png', 'https://postiz.example.com/editorial/public/media/already.webp'):
        article = {'imageUrl': url}
        assert optimized_article(article, 'https://postiz.example.com') == article


def test_webp_derivative_preserves_alpha(tmp_path):
    from public_images import public_image_path
    media = tmp_path / 'media'
    media.mkdir()
    Image.new('RGBA', (160, 90), (50, 100, 200, 0)).save(media / 'transparent.png')
    articles = [{'imageUrl': 'https://postiz.example.com/editorial/public/media/transparent.png'}]
    path = public_image_path(tmp_path, 'transparent.png.v1.webp', articles)
    with Image.open(path) as image:
        assert image.mode == 'RGBA'
        assert image.getpixel((10, 10))[3] == 0

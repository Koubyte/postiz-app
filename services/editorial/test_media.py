import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import media


def png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def background():
    image = Image.new('RGB',(900,900))
    draw = ImageDraw.Draw(image)
    for y in range(900):
        draw.line((0,y,900,y),fill=(30+y//10,40+y//14,50+y//20))
    draw.rectangle((40,20,300,700),fill=(45,31,22))
    return png(image)


def source(alpha=True):
    image = Image.new('RGBA',(300,500),(255,255,255,0 if alpha else 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60,40,240,460),fill=(150,40,50,255))
    # A real white detail enclosed within the product must remain white.
    draw.rectangle((110,180,190,260),fill=(255,255,255,255))
    return image


def render(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(media,'public_bytes',lambda *args,**kwargs: png(source()))
    params = dict(item_id='../../not-a-filename',product={'id':'p1','title':'Microphone test','thumbnail':'https://example.com/photo.png','ean':'000123'},background=background(),content={'headline':'La voix prend sa place','kind':'product'},output_dir=tmp_path)
    params.update(overrides)
    return media.render_assets(**params)


def test_export_sizes_traceability_and_price_hidden(tmp_path,monkeypatch):
    result=render(tmp_path,monkeypatch)
    assert Image.open(tmp_path/result['media']).size == (1080,1350)
    assert Image.open(tmp_path/result['blog_media']).size == (1600,900)
    assert result['provenance']['price_text'] is None
    assert result['provenance']['ean'] == '000123'
    assert result['provenance']['requires_visual_approval'] is True
    assert result['provenance']['source_sha256']
    assert Path(result['media']).name == result['media']
    assert Image.open(tmp_path/result['source_media']).tobytes() == source().tobytes()


def test_cutout_preserves_every_source_rgb_and_enclosed_white():
    original = source(alpha=False)
    masked,method = media._cutout(original)
    assert method == 'edge-connected-white'
    assert masked.convert('RGB').tobytes() == original.convert('RGB').tobytes()
    assert masked.getpixel((150,220)) == (255,255,255,255)
    assert masked.getpixel((0,0))[3] == 0


def test_composition_preserves_product_center_without_repainting(tmp_path,monkeypatch):
    result=render(tmp_path,monkeypatch)
    placement=result['provenance']['placements']['blog']
    x,y=placement['xy'];w,h=placement['size']
    image=Image.open(tmp_path/result['blog_media'])
    assert image.getpixel((x+w//2,y+h//2)) == (255,255,255)
    assert image.getpixel((x+w//2,y+int(h*.15))) == (150,40,50)


def test_bad_masks_and_supplier_protection_block(tmp_path,monkeypatch):
    for image in (Image.new('RGB',(200,200),'white'),Image.new('RGB',(200,200),'red')):
        with pytest.raises(media.MediaBlocked):
            media._cutout(image.convert('RGBA'))
    with pytest.raises(media.MediaBlocked,match='protégée'):
        render(tmp_path,monkeypatch,product={'thumbnail':'https://example.com/p.png','image_mask_required':True})
    assert not list(tmp_path.iterdir())


def test_price_only_affects_reserved_social_region(tmp_path,monkeypatch):
    a=render(tmp_path/'a',monkeypatch)
    b=render(tmp_path/'b',monkeypatch,content={'headline':'La voix prend sa place','kind':'product','price_text':'129 €'})
    img_a=Image.open(tmp_path/'a'/a['media']); img_b=Image.open(tmp_path/'b'/b['media'])
    assert img_a.crop((0,0,1080,1229)).tobytes()==img_b.crop((0,0,1080,1229)).tobytes()
    assert img_a.tobytes()!=img_b.tobytes()
    assert Image.open(tmp_path/'a'/a['blog_media']).tobytes()==Image.open(tmp_path/'b'/b['blog_media']).tobytes()


def test_background_and_overflow_fail_closed(tmp_path,monkeypatch):
    with pytest.raises(media.MediaBlocked,match='blanc ou vide'):
        render(tmp_path,monkeypatch,background=png(Image.new('RGB',(500,500),'white')))
    with pytest.raises(media.MediaBlocked,match='Titre trop long'):
        render(tmp_path,monkeypatch,content={'headline':' '.join(['impossible']*100)})
    with pytest.raises(media.MediaBlocked,match='photographie réelle'):
        render(tmp_path,monkeypatch,product=None,content={'kind':'store','headline':'Notre magasin'})


def test_advice_cover_has_no_logo_or_text(tmp_path,monkeypatch):
    result=render(tmp_path,monkeypatch,product=None,content={'headline':'Choisir son premier micro','kind':'advice'})
    expected,_=media._scene(media._decode(background()),(1600,900),None)
    assert Image.open(tmp_path/result['blog_media']).tobytes()==expected.convert('RGB').tobytes()
    assert result['provenance']['product_transforms']==[]
    assert 'source_media' not in result


def test_optional_segmenter_uses_only_explicit_local_model(tmp_path,monkeypatch):
    from types import SimpleNamespace
    (tmp_path/'u2netp.onnx').write_bytes(b'provided-model')
    monkeypatch.setenv('U2NET_HOME',str(tmp_path))
    calls=[]
    def session(name,**kwargs):
        calls.append((name,kwargs))
        return object()
    mask=source().getchannel('A')
    monkeypatch.setitem(sys.modules,'rembg',SimpleNamespace(new_session=session,remove=lambda image,**kwargs:mask))
    product,method=media._cutout(source(alpha=False))
    assert method=='rembg-u2netp'
    assert calls[0][0]=='u2net_custom'
    assert calls[0][1]['model_path']==str(tmp_path/'u2netp.onnx')
    assert calls[0][1]['providers']==['CPUExecutionProvider']
    assert product.convert('RGB').tobytes()==source(alpha=False).convert('RGB').tobytes()

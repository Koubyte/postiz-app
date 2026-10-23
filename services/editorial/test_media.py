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


def model_fixture(tmp_path,monkeypatch,prediction=None):
    import hashlib
    import numpy as np
    from types import SimpleNamespace
    model=tmp_path/'u2netp.onnx'
    model.write_bytes(b'provided-model')
    monkeypatch.setenv('U2NET_HOME',str(tmp_path))
    monkeypatch.setattr(media,'MODEL_BYTES',model.stat().st_size)
    monkeypatch.setattr(media,'MODEL_SHA256',hashlib.sha256(model.read_bytes()).hexdigest())
    calls=[]
    if prediction is None:
        prediction=np.zeros((1,1,320,320),dtype=np.float32)
        prediction[:,:,30:290,60:260]=1
    class Session:
        def __init__(self,path,**kwargs):calls.append(('session',path,kwargs))
        def get_inputs(self):return [SimpleNamespace(name='input')]
        def run(self,outputs,inputs):
            calls.append(('run',inputs))
            return [prediction]
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(SessionOptions=SimpleNamespace,InferenceSession=Session))
    return model,calls


def test_local_segmenter_normalizes_input_and_preserves_source_rgb(tmp_path,monkeypatch):
    import numpy as np
    model,calls=model_fixture(tmp_path,monkeypatch)
    product,method=media._cutout(source(alpha=False))
    assert method=='onnx-u2netp'
    assert calls[0][1]==str(model)
    assert calls[0][2]['providers']==['CPUExecutionProvider']
    options=calls[0][2]['sess_options']
    assert options.intra_op_num_threads==options.inter_op_num_threads==1
    tensor=calls[1][1]['input']
    assert tensor.shape==(1,3,320,320) and tensor.dtype==np.float32
    assert np.isfinite(tensor).all()
    np.testing.assert_allclose(tensor[0,:,0,0],(np.ones(3)-[.485,.456,.406])/[.229,.224,.225],rtol=1e-6)
    assert product.convert('RGB').tobytes()==source(alpha=False).convert('RGB').tobytes()


@pytest.mark.parametrize('invalid',['uniform','nan'])
def test_segmenter_rejects_uniform_or_nonfinite_masks(tmp_path,monkeypatch,invalid):
    import numpy as np
    prediction=np.full((1,1,320,320),float('nan') if invalid=='nan' else .5,dtype=np.float32)
    model,calls=model_fixture(tmp_path,monkeypatch,prediction)
    with pytest.raises(media.MediaBlocked,match='masque'):
        media._cutout(source(alpha=False))


def test_model_checksum_mismatch_cannot_trigger_inference_or_download(tmp_path,monkeypatch):
    model,calls=model_fixture(tmp_path,monkeypatch)
    model.write_bytes(b'corrupted model')
    monkeypatch.setattr(media,'public_bytes',lambda *a,**k:pytest.fail('No download allowed'))
    with pytest.raises(media.MediaBlocked,match='version vérifiée'):
        media._cutout(source(alpha=False))
    assert calls==[]


def test_missing_model_uses_local_packshot_fallback_without_download(tmp_path,monkeypatch):
    monkeypatch.setenv('U2NET_HOME',str(tmp_path))
    monkeypatch.setattr(media,'public_bytes',lambda *a,**k:pytest.fail('No download allowed'))
    image,method=media._cutout(source(alpha=False))
    assert method=='edge-connected-white'
    assert image.convert('RGB').tobytes()==source(alpha=False).convert('RGB').tobytes()

"""Reference-guided scenes get charter overlays, never a pasted product."""
import hashlib
import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import media


def png(image):
    stream=io.BytesIO();image.save(stream,format='PNG');return stream.getvalue()


def background():
    image=Image.new('RGB',(900,900));draw=ImageDraw.Draw(image)
    for y in range(900):draw.line((0,y,900,y),fill=(30+y//10,40+y//14,50+y//20))
    draw.rectangle((40,20,300,700),fill=(45,31,22))
    # A generated product represented within the scene, different from the source fixture.
    draw.rectangle((340,300,600,650),fill=(28,51,130))
    return png(image)


def source():
    image=Image.new('RGB',(300,500),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((60,40,240,460),fill=(150,40,50))
    draw.rectangle((110,180,190,260),fill='white')
    return image


def render(tmp_path,**overrides):
    params=dict(item_id='../../not-a-filename',product={'id':'p1','title':'Microphone test','thumbnail':'https://example.com/photo.png','ean':'000123'},background=background(),content={'headline':'La voix prend sa place','kind':'product'},output_dir=tmp_path,product_reference=png(source()),reference_used=True)
    params.update(overrides)
    return media.render_assets(**params)


def test_export_sizes_and_reference_provenance(tmp_path):
    result=render(tmp_path)
    assert Image.open(tmp_path/result['media']).size==(1080,1350)
    assert Image.open(tmp_path/result['blog_media']).size==(1600,900)
    provenance=result['provenance']
    assert provenance['price_text'] is None and provenance['ean']=='000123'
    assert provenance['requires_visual_approval'] is True
    assert provenance['fidelity_requires_visual_review'] is True
    assert provenance['image_mode']=='reference-guided-generation'
    assert provenance['reference_used'] is True and provenance['product_rgb_repainted'] is True
    assert provenance['source_sha256']==hashlib.sha256(png(source())).hexdigest()
    assert Path(result['media']).name==result['media']
    assert Image.open(tmp_path/result['source_media']).convert('RGB').tobytes()==source().tobytes()
    assert 'mask_media' not in result and not list(tmp_path.glob('*mask*'))


@pytest.mark.parametrize('overrides',[
    {'reference_used':False}, {'reference_used':'true'}, {'product_reference':None},
    {'product_reference':b''}, {'product_reference':b'not an image'},
    {'product_reference':png(Image.new('RGB',(40,40)))},
])
def test_exact_product_reference_must_have_been_used(tmp_path,overrides):
    with pytest.raises(media.MediaBlocked):render(tmp_path,**overrides)
    assert not list(tmp_path.iterdir())


def test_protected_supplier_reference_is_blocked(tmp_path):
    with pytest.raises(media.MediaBlocked,match='protégée'):
        render(tmp_path,product={'title':'Micro','image_mask_required':True})
    assert not list(tmp_path.iterdir())


def test_product_is_not_pasted_and_blog_has_no_overlays(tmp_path):
    result=render(tmp_path)
    expected=media._scene(media._decode(background()),(1600,900)).convert('RGB')
    actual=Image.open(tmp_path/result['blog_media'])
    assert actual.tobytes()==expected.tobytes()
    # Swapping the reference cannot alter the generated scene or charter pixels.
    other=render(tmp_path/'other',product_reference=png(Image.new('RGB',(300,500),'green')))
    assert Image.open(tmp_path/'other'/other['media']).tobytes()==Image.open(tmp_path/result['media']).tobytes()
    assert other['provenance']['source_sha256']!=result['provenance']['source_sha256']
    assert result['provenance']['product_transforms']==[]


def test_charter_is_deterministic_and_price_stays_in_reserved_region(tmp_path):
    a=render(tmp_path/'a');same=render(tmp_path/'same')
    b=render(tmp_path/'b',content={'headline':'La voix prend sa place','kind':'product','price_text':'129 €'})
    img_a=Image.open(tmp_path/'a'/a['media']);img_b=Image.open(tmp_path/'b'/b['media'])
    assert img_a.tobytes()==Image.open(tmp_path/'same'/same['media']).tobytes()
    assert img_a.crop((0,0,1080,1229)).tobytes()==img_b.crop((0,0,1080,1229)).tobytes()
    assert img_a.tobytes()!=img_b.tobytes()
    assert Image.open(tmp_path/'a'/a['blog_media']).tobytes()==Image.open(tmp_path/'b'/b['blog_media']).tobytes()


def test_scene_and_overflow_fail_closed(tmp_path):
    with pytest.raises(media.MediaBlocked,match='blanc ou vide'):
        render(tmp_path,background=png(Image.new('RGB',(500,500),'white')))
    with pytest.raises(media.MediaBlocked,match='Titre trop long'):
        render(tmp_path,content={'headline':' '.join(['impossible']*100)})
    with pytest.raises(media.MediaBlocked,match='photographie réelle'):
        render(tmp_path,product=None,content={'kind':'store','headline':'Notre magasin'})


def test_advice_needs_no_product_reference(tmp_path):
    result=render(tmp_path,product=None,reference_used=False,product_reference=None,content={'headline':'Choisir son premier micro','kind':'advice'})
    expected=media._scene(media._decode(background()),(1600,900)).convert('RGB')
    assert Image.open(tmp_path/result['blog_media']).tobytes()==expected.tobytes()
    assert result['provenance']['image_mode']=='scene-generation'
    assert result['provenance']['reference_used'] is False
    assert result['provenance']['source_sha256'] is None
    assert 'source_media' not in result


def test_render_does_not_download_or_segment(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('Renderer must not download'))
    monkeypatch.setattr(requests,'request',lambda *a,**k:pytest.fail('Renderer must not download'))
    result=render(tmp_path)
    assert result['provenance']['reference_used']
    assert not hasattr(media,'_cutout') and not hasattr(media,'_model_mask')


def test_multiple_references_are_saved_and_hashed_individually(tmp_path):
    refs=[png(source()),png(Image.new('RGB',(300,500),'ivory')),png(Image.new('RGB',(300,500),'black'))]
    metadata=[{'url':f'https://example.com/piano-{i}.jpg','label':label} for i,label in enumerate(('Noir','Blanc','Noyer'))]
    result=render(tmp_path,product_references=refs,product={'id':'hailun','title':'Hailun piano','reference_images':metadata})
    assert result['provenance']['reference_sha256']==[hashlib.sha256(data).hexdigest() for data in refs]
    assert result['provenance']['source_urls']==[m['url'] for m in metadata]
    assert result['provenance']['reference_labels']==['Noir','Blanc','Noyer']
    assert result['provenance']['source_sha256']==result['provenance']['reference_sha256'][0]
    for index,data in enumerate(refs):
        field='source_media' if index==0 else f'source_media_{index+1}'
        assert isinstance(result[field],str)
        path=tmp_path/result[field]
        assert Image.open(path).convert('RGB').tobytes()==media._decode(data).convert('RGB').tobytes()
        assert result['provenance']['files_sha256'][field]==hashlib.sha256(path.read_bytes()).hexdigest()
    assert all(isinstance(value,str) for key,value in result.items() if key!='provenance')
    expected=media._scene(media._decode(background()),(1600,900)).convert('RGB')
    assert Image.open(tmp_path/result['blog_media']).tobytes()==expected.tobytes()


@pytest.mark.parametrize('refs',[[],[b'bad'],[png(source())]*4,'not-a-list'])
def test_reference_list_is_bounded_and_validated(tmp_path,refs):
    with pytest.raises(media.MediaBlocked):render(tmp_path,product_reference=None,product_references=refs)
    assert not list(tmp_path.iterdir())


def test_conflicting_legacy_and_list_reference_blocks(tmp_path):
    with pytest.raises(media.MediaBlocked,match='incohérentes'):
        render(tmp_path,product_references=[png(Image.new('RGB',(300,500),'green'))])


def test_official_hailun_photo_dimensions_are_accepted():
    # 7008×4672 is an actual manufacturer photo size (32.7MP), within the 40MP cap.
    stream=io.BytesIO()
    original=Image.new('L',(7008,4672),128)
    original.save(stream,format='JPEG');original.close()
    decoded=media._decode(stream.getvalue())
    assert decoded.size==(7008,4672)
    decoded.close()


def test_reference_over_40_megapixels_is_blocked_before_loading(monkeypatch):
    class Oversized:
        width=8000;height=5001
        @property
        def size(self):return self.width,self.height
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def load(self):pytest.fail('Oversized image must not be decoded')
    monkeypatch.setattr(media.Image,'open',lambda *args:Oversized())
    with pytest.raises(media.MediaBlocked,match='Dimensions'):
        media._decode(b'image-header')

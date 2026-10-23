"""Approval, publication isolation and durable idempotency regression tests.

All network and model calls are fakes. No Postiz/social publication is made.
"""
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent))
from generation import Generator, GenerationError, validate_content, validate_plan
from publisher import Publisher
import publisher as publication
from store import Store, Conflict, dumps, planned_date, monday_next, PARIS


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def content(kind='social'):
    value={'title':'Choisir un micro','headline':'Une voix bien enregistrée','alt':'Microphone dans un studio','sources':[{'title':'Notice fabricant','url':'https://example.com/manual'}],'uncertainty':''}
    if kind=='social':
        value.update(facebook='Un conseil concret pour votre microphone.',instagram='Un conseil concret pour votre microphone.')
    else:
        value.update(markdown='## Un conseil\n\n'+'Conseils pratiques utiles et précis. '*110,excerpt='Des conseils pour votre microphone.',slug='choisir-microphone-test',category='guides')
    return value


def create_item(store,kind='social',status='review'):
    identifier='test-'+kind
    week=store.prepare('2030-10-28')
    media_dir=store.root/'media';media_dir.mkdir(exist_ok=True)
    files={'media':'social.png','blog_media':'cover.png','source_media':'source.png'}
    for filename in files.values():(media_dir/filename).write_bytes(b'fixed image '+filename.encode())
    media={**files,'hashes':{key:hashlib.sha256((media_dir/name).read_bytes()).hexdigest() for key,name in files.items()}}
    due=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    with store.db() as db:
        db.execute('INSERT INTO items(id,week_id,kind,slot,status,content,media,scheduled_at) VALUES(?,?,?,?,?,?,?,?)',(identifier,week,kind,0,status,dumps(content(kind)),dumps(media),due))
    return identifier


def make_due(monkeypatch,item):
    fake_now=datetime.fromisoformat(item['scheduled_at'])+timedelta(seconds=1)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return fake_now.astimezone(tz) if tz else fake_now.replace(tzinfo=None)
    monkeypatch.setattr(publication,'datetime',Clock)


def fake_api(monkeypatch,publisher,fail=False):
    monkeypatch.setenv('POSTIZ_CHANNELS',json.dumps({'facebook':'fb','instagram':'ig'}))
    calls=[]
    def api(method,path,**kwargs):
        calls.append((method,path,kwargs))
        if path=='/integrations':return [{'id':'fb','identifier':'facebook'},{'id':'ig','identifier':'instagram'}]
        if path=='/upload':return {'id':'upload','path':'https://example.com/upload.png'}
        if path=='/posts':
            if fail:raise requests.Timeout('Unknown whether server accepted POST')
            return [{'id':'post-'+str(len(calls))}]
        raise AssertionError(path)
    monkeypatch.setattr(publisher,'api',api)
    return calls


def test_approval_requires_review_and_exact_revision(store):
    id=create_item(store)
    with pytest.raises(Conflict):store.approve_item(id,1,'owner',False)
    with pytest.raises(Conflict):store.approve_item(id,2,'owner',True)
    store.approve_item(id,1,'owner',True)
    item=store.item(id)
    assert item['approval_hash']==store.content_hash(item)
    assert item['approved_by']=='owner'
    assert item['status']=='approved'
    with pytest.raises(Conflict):store.approve_item(id,1,'owner',True)


def test_content_or_date_change_revokes_previous_approval(store):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    previous=store.item(id)
    store.save_item(id,1,{'facebook':'Texte corrigé.'},previous['scheduled_at'],'owner')
    changed=store.item(id)
    assert changed['revision']==2 and changed['status']=='review'
    assert changed['approval_hash'] is None and changed['approved_at'] is None
    with pytest.raises(Conflict):store.approve_item(id,1,'owner',True)
    store.approve_item(id,2,'owner',True)
    store.save_item(id,2,{},(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),'owner')
    assert store.item(id)['approval_hash'] is None


def test_visual_change_requires_new_render_and_approval(store):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    store.save_item(id,1,{'headline':'Une nouvelle accroche'},store.item(id)['scheduled_at'],'owner')
    item=store.item(id)
    assert item['status']=='queued' and not item['media'] and not item['approval_hash']
    with pytest.raises(Conflict):store.approve_item(id,2,'owner',True)
    with store.db() as db:assert db.execute("SELECT count(*) FROM jobs WHERE kind='render' AND target=?",(id,)).fetchone()[0]==1


def test_no_delivery_without_approval_and_no_changed_media(store,monkeypatch):
    id=create_item(store);publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    calls=fake_api(monkeypatch,publisher);make_due(monkeypatch,store.item(id))
    publisher.deliver(id)
    assert calls==[]
    store.approve_item(id,1,'owner',True)
    (store.root/'media'/'social.png').write_bytes(b'new unapproved bytes')
    with pytest.raises(Conflict,match='média'):publisher.deliver(id)
    assert calls==[]


def test_ambiguous_post_is_durable_and_never_retried(store,monkeypatch):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]));calls=fake_api(monkeypatch,publisher,fail=True)
    make_due(monkeypatch,store.item(id))
    with pytest.raises(Conflict,match='incertain'):publisher.deliver(id)
    store.recover()
    publisher.deliver(id)
    assert len([call for call in calls if call[1]=='/posts'])==1
    with store.db() as db:
        rows=list(db.execute('SELECT channel,status FROM deliveries'))
    assert [(r[0],r[1]) for r in rows]==[('facebook','uncertain')]
    assert store.item(id)['status']=='blocked'
    with pytest.raises(Conflict):store.save_item(id,1,{'facebook':'Relancer'},store.item(id)['scheduled_at'],'owner')


def test_two_channels_once_and_pause_blocks_all_transmission(store,monkeypatch):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]));calls=fake_api(monkeypatch,publisher)
    make_due(monkeypatch,store.item(id))
    with store.db() as db:db.execute("UPDATE settings SET value='true' WHERE key='paused'")
    publisher.deliver(id);assert calls==[]
    with store.db() as db:db.execute("UPDATE settings SET value='false' WHERE key='paused'")
    publisher.deliver(id);publisher.deliver(id)
    assert len([call for call in calls if call[1]=='/posts'])==2
    assert store.item(id)['status']=='scheduled'


def test_blog_public_projection_only_after_approved_due_publication(store,monkeypatch):
    id=create_item(store,'blog');publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    assert store.public_articles()==[]
    store.approve_item(id,1,'owner',True)
    assert store.public_articles()==[]
    make_due(monkeypatch,store.item(id));publisher.deliver(id)
    articles=store.public_articles()
    assert len(articles)==1 and articles[0]['published'] is True
    assert 'approval_hash' not in articles[0] and 'media' not in articles[0] and 'sources' not in articles[0]
    publisher.deliver(id)
    assert len(store.public_articles())==1


def test_public_http_endpoints_do_not_expose_drafts(store,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(store.root))
    monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('editorial_review_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    create_item(store,'blog')
    with TestClient(module.app) as client:
        assert client.get('/editorial/public/articles').json()=={'articles':[]}
        assert client.get('/editorial/public/media/cover.png').status_code==404
        assert client.get('/editorial/media/cover.png').status_code==401
        assert client.get('/editorial/api/state').status_code==401


def valid_plan():
    products=[{'id':'p'+str(i)} for i in range(3)]
    plan={'subjects':[{'slot':i,'kind':'product' if i<3 else 'advice','title':'Sujet '+str(i),'angle':'Conseil pratique','product_id':'p'+str(i) if i<3 else None,'scene':'Un studio'} for i in range(7)],'article':{'title':'Un guide','angle':'Un plan utile','product_id':None,'social_slot':6}}
    return plan,products


def test_seven_subjects_three_distinct_products_and_paris_timezone():
    plan,products=valid_plan()
    validated=validate_plan(plan,products,'2026-10-19')
    dates=[datetime.fromisoformat(s['scheduled_at']).astimezone(PARIS) for s in validated['subjects']]
    assert len({d.date() for d in dates})==7
    assert all(d.hour==12 for d in dates)
    assert datetime.fromisoformat(validated['subjects'][5]['scheduled_at']).hour==10
    assert datetime.fromisoformat(validated['subjects'][6]['scheduled_at']).hour==11
    assert monday_next(datetime(2026,10,23,9,tzinfo=timezone.utc))=='2026-10-26'
    plan['subjects'][2]['product_id']='p1'
    with pytest.raises(GenerationError):validate_plan(plan,products,'2026-10-19')


def test_explicit_dates_can_share_days_or_leave_the_plan_week():
    plan,products=valid_plan()
    for subject in plan['subjects']:subject['scheduled_at']='2026-10-23T15:30:00+02:00'
    plan['subjects'][6]['scheduled_at']='2026-12-19T15:30:00+01:00'
    plan['article']['scheduled_at']='2026-10-23T16:00:00+02:00'
    validated=validate_plan(plan,products,'2026-10-26')
    assert all(s['scheduled_at']=='2026-10-23T13:30:00+00:00' for s in validated['subjects'][:6])
    assert validated['subjects'][6]['scheduled_at']=='2026-12-19T14:30:00+00:00'
    assert validated['article']['scheduled_at']=='2026-10-23T14:00:00+00:00'


@pytest.mark.parametrize('invalid',['not-a-date','2026-10-23T15:30:00',123])
@pytest.mark.parametrize('kind',['social','blog'])
def test_explicit_dates_still_require_a_valid_timezone(invalid,kind):
    plan,products=valid_plan()
    brief=plan['subjects'][0] if kind=='social' else plan['article']
    brief['scheduled_at']=invalid
    with pytest.raises(GenerationError,match='fuseau horaire'):validate_plan(plan,products,'2026-10-26')


def test_invalid_linked_blog_slot_is_blocked():
    plan,products=valid_plan();plan['article']['social_slot']=19
    with pytest.raises(GenerationError):validate_plan(plan,products,'2026-10-19')


@pytest.mark.parametrize('field',['facebook','instagram','headline','title','alt'])
def test_commercial_text_is_kept_with_a_review_note(field):
    candidate=content();candidate[field]='Un microphone à 99 € pour votre studio.'
    result=validate_content(candidate,'social')
    assert result[field]==candidate[field]
    assert any('prix ou une mention commerciale' in note for note in result['editorial_notes'])


def test_draft_hidden_price_is_not_injected(store,monkeypatch):
    id=create_item(store,status='queued');item=store.item(id)
    plan={'subjects':[{'title':'Sujet','angle':'Conseil','product_id':'p1','scene':'Studio'}],'products':[{'id':'p1','title':'Micro','price':199,'price_mode':'hide'}]}
    with store.db() as db:db.execute('UPDATE weeks SET plan=? WHERE id=?',(dumps(plan),item['week_id']))
    generator=Generator(store)
    monkeypatch.setattr(generator,'ask',lambda prompt:content())
    monkeypatch.setattr(generator,'render',lambda id:None)
    generator.draft(id)
    drafted=store.item(id)['content']
    assert drafted['price_text'] is None
    assert '€' not in drafted['facebook']+drafted['instagram']


@pytest.mark.parametrize('changed', [{'price':201,'available':True},{'price':199,'available':False}])
def test_changed_catalogue_price_or_stock_blocks_approved_delivery(store,monkeypatch,changed):
    id=create_item(store)
    with store.db() as db:
        item=store.item(id,db);media=item['media']
        media['product_snapshot']={'id':'p1','price':199,'available':True,'price_mode':'catalogue','external':False}
        db.execute('UPDATE items SET media=? WHERE id=?',(dumps(media),id))
    store.approve_item(id,1,'owner',True)
    generator=SimpleNamespace(products=lambda **kw:[{'id':'p1',**changed}])
    publisher=Publisher(store,generator);calls=fake_api(monkeypatch,publisher)
    make_due(monkeypatch,store.item(id))
    with pytest.raises(Conflict):publisher.deliver(id)
    assert calls==[]


def test_research_can_never_set_publication_status(store,monkeypatch):
    id=create_item(store,status='queued');item=store.item(id)
    with store.db() as db:
        db.execute('UPDATE weeks SET plan=? WHERE id=?',(dumps({'subjects':[{'title':'Conseil','product_id':None}],'products':[]}),item['week_id']))
    answer={**content(),'status':'approved','approval_hash':'forged','approved_by':'model'}
    generator=Generator(store)
    monkeypatch.setattr(generator,'ask',lambda prompt:answer)
    monkeypatch.setattr(generator,'render',lambda id:None)
    generator.draft(id)
    item=store.item(id)
    assert item['status']=='rendering' and not item['approval_hash']
    assert 'approval_hash' not in item['content'] and 'status' not in item['content']


def create_plan(store):
    week=store.prepare('2030-10-28')
    products=[{'id':str(i),'title':'Produit '+str(i),'ean':'','price_mode':'hide'} for i in range(3)]
    plan=validate_plan({'subjects':[{'slot':i,'kind':'product' if i<3 else 'advice','title':'Sujet '+str(i),'angle':'Angle original','product_id':str(i) if i<3 else None,'scene':'Bois et lumière'} for i in range(7)],'article':{'title':'Blog intact','angle':'Conseil précis','product_id':None,'social_slot':6}},products,'2030-10-28')
    plan.update(products=products,sources=[],brand_version='pl-social-v1',unresolved_requests=[])
    with store.db() as db:db.execute("UPDATE weeks SET plan=?,status='plan_review' WHERE id=?",(dumps(plan),week))
    return week,plan


def test_revise_only_one_subject_preserves_six_and_blog(store,monkeypatch):
    week,plan=create_plan(store)
    change=store.revise_subject(week,4,1,'Un conseil sur la lumière',None,'owner')
    gen=Generator(store)
    monkeypatch.setattr(gen,'ask',lambda _: {'subject':{**plan['subjects'][4],'title':'Nouveau conseil','slot':0,'scheduled_at':'2099-01-01'}})
    gen.revise(change)
    # Retrying an already completed job is harmless.
    gen.revise(change)
    with store.db() as db:
        row=db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone();updated=json.loads(row['plan'])
        assert row['status']=='plan_review' and row['revision']==2
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0
    assert updated['article']==plan['article']
    assert all(updated['subjects'][i]==plan['subjects'][i] for i in range(7) if i!=4)
    assert updated['subjects'][4]['title']=='Nouveau conseil'
    assert updated['subjects'][4]['scheduled_at']==plan['subjects'][4]['scheduled_at']
    assert updated['subjects'][4]['slot']==4


def test_targeted_product_replacement_consumes_only_chosen_request(store,monkeypatch):
    week,plan=create_plan(store)
    with store.db() as db:
        for id in ('chosen','other'):
            db.execute("INSERT INTO requests(id,query,note,price_mode,priority,created) VALUES(?,?,'','hide',1,'today')",(id,id))
    gen=Generator(store)
    product={'id':'new','title':'chosen','ean':'','url':'https://example.com/product'}
    monkeypatch.setattr(gen,'products',lambda: [product])
    monkeypatch.setattr(gen,'ask',lambda _: {'subject':{**plan['subjects'][0],'title':'Produit demandé','product_id':'new'}})
    change=store.revise_subject(week,0,1,'','chosen','owner');gen.revise(change)
    with store.db() as db:
        updated=json.loads(db.execute('SELECT plan FROM weeks WHERE id=?',(week,)).fetchone()[0])
        assert db.execute("SELECT status FROM requests WHERE id='chosen'").fetchone()[0]=='in_plan'
        assert db.execute("SELECT status FROM requests WHERE id='other'").fetchone()[0]=='pending'
    assert updated['subjects'][1:]==plan['subjects'][1:] and updated['article']==plan['article']
    assert updated['subjects'][0]['product_id']=='new'


def test_failed_single_revision_preserves_plan_and_request(store,monkeypatch):
    week,plan=create_plan(store);gen=Generator(store)
    change=store.revise_subject(week,0,1,'Retirer le produit',None,'owner')
    monkeypatch.setattr(gen,'ask',lambda _: {'subject':{**plan['subjects'][0],'kind':'advice','product_id':None}})
    with pytest.raises(GenerationError,match='trois produits'):gen.revise(change)
    with store.db() as db:
        store.fail_revision(db,change,'Minimum de trois produits requis.')
        row=db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone()
        assert row['status']=='plan_review' and row['revision']==1 and json.loads(row['plan'])==plan


def test_targeted_revision_rejects_stale_and_concurrent_changes(store):
    week,plan=create_plan(store)
    with pytest.raises(Conflict):store.revise_subject(week,0,2,'test',None,'owner')
    with pytest.raises(Conflict):store.revise_subject(week,8,1,'test',None,'owner')
    with pytest.raises(Conflict):store.revise_subject(week,0,1,'','unknown','owner')
    store.revise_subject(week,0,1,'test',None,'owner')
    with pytest.raises(Conflict):store.revise_subject(week,1,1,'test',None,'owner')


def test_restart_failed_revision_unlocks_unchanged_plan(store):
    week,plan=create_plan(store)
    change=store.revise_subject(week,3,1,'Conseil différent',None,'owner')
    with store.db() as db:db.execute("UPDATE jobs SET status='running',attempts=2 WHERE target=?",(change,))
    store.recover()
    with store.db() as db:
        row=db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone()
        assert row['status']=='plan_review' and json.loads(row['plan'])==plan


def test_reference_photo_is_sent_to_generator_and_acknowledged(store,monkeypatch):
    import base64,io
    from PIL import Image
    import generation
    reference=io.BytesIO();Image.new('RGB',(400,300),'orange').save(reference,format='PNG')
    scene=io.BytesIO();Image.linear_gradient('L').resize((1024,1536)).convert('RGB').save(scene,format='PNG')
    identifier=create_item(store)
    with store.db() as db:
        row=store.item(identifier,db)
        product={'id':'orange-piano','title':'Piano orange','ean':'1234567890123','thumbnail':'https://example.com/piano.png','image_mask_required':False}
        plan={'subjects':[{'kind':'product','product_id':product['id']}],'products':[product]}
        db.execute('UPDATE weeks SET plan=? WHERE id=?',(dumps(plan),row['week_id']))
        db.execute("UPDATE items SET content=?,status='rendering' WHERE id=?",(dumps({**row['content'],'product_id':product['id'],'scene':'Salon lumineux'}),identifier))
    monkeypatch.setattr(generation,'public_bytes',lambda *args:reference.getvalue())
    calls=[]
    def bridge(path,payload,**kwargs):
        raw=base64.b64decode(payload['reference_image']['b64_json']);calls.append(payload)
        assert payload['reference_image']['mime_type']=='image/png'
        assert Image.open(io.BytesIO(raw)).getpixel((100,100))[:3]==(255,165,0)
        assert 'PHOTO DE RÉFÉRENCE JOINTE' in payload['prompt']
        return {'reference_image_sha256':hashlib.sha256(raw).hexdigest(),'data':[{'b64_json':base64.b64encode(scene.getvalue()).decode()}]}
    from test_scenes import directions
    gen=Generator(store);monkeypatch.setattr(gen,'ask',lambda _:directions());monkeypatch.setattr(gen,'bridge',bridge);gen.render(identifier)
    item=store.item(identifier)
    assert len(calls)==1 and item['status']=='review' and item['approval_hash'] is None
    assert item['media']['provenance']['image_mode']=='reference-guided-generation'
    assert 'mask_media' not in item['media']
    assert item['media']['visual_direction']['setting']=='home'
    assert 'Piano dans une pièce de vie claire' in calls[0]['prompt']
    assert 'Lumière chaleureuse naturelle, bois et matériaux mats' not in calls[0]['prompt']
    assert item['media']['source_media']
    # An older bridge silently ignoring the reference must never create a product visual.
    monkeypatch.setattr(gen,'bridge',lambda *args,**kwargs:{'data':[{'b64_json':base64.b64encode(scene.getvalue()).decode()}]})
    with pytest.raises(GenerationError,match='référence'):gen.render(identifier)


def test_identity_survives_missing_photo_ean_and_variant_uncertainty(store,monkeypatch):
    import generation
    gen=Generator(store)
    monkeypatch.setattr(gen,'ask',lambda _: {'matched':True,'brand':'Example','model':'HD-42','title':'Example HD-42','manufacturer_url':'https://example.com/piano','description':'Piano','identity_uncertainty':'','variant_uncertainty':'Bleu à préciser','requested_variants':[{'requested_name':'bleu','confirmed':False}],'sources':[{'url':'https://example.com/piano'}]})
    monkeypatch.setattr(generation,'public_bytes',lambda *args: (_ for _ in ()).throw(ValueError('403')))
    product=gen.resolve_external('Example HD42 bleu')
    assert product['title']=='Example HD-42' and not product['ean']
    assert product['thumbnail'] is None and product['media_status']=='needs_reference'
    assert product['variant_uncertainty']=='Bleu à préciser'
    monkeypatch.setattr(gen,'ask',lambda _: {'matched':False,'identity_uncertainty':'Deux modèles distincts'})
    with pytest.raises(GenerationError,match='Deux modèles distincts'):gen.resolve_external('Example')


def test_resolver_rejects_unobserved_image_url(store,monkeypatch):
    import generation
    gen=Generator(store)
    answers=iter([{'matched':True,'brand':'Example','model':'42','title':'Example 42','manufacturer_url':'https://example.com/product','description':'Piano','sources':[{'url':'https://example.com/product'}]}, {'image_url':'https://example.com/invented.jpg','image_scope':'requested_variants'}])
    monkeypatch.setattr(gen,'ask',lambda _:next(answers))
    monkeypatch.setattr(generation,'public_bytes',lambda *args:b'<img src="/actual.jpg" alt="Example 42">')
    assert gen.resolve_external('Example 42')['thumbnail'] is None


def test_reviewed_hailun_color_references_require_bay_blue_confirmation():
    from reviewed_products import reviewed_references
    identity={'brand':'Hailun','model':'HD-300'}
    variants=[{'requested_name':'orange','manufacturer_name':'Warm Sun Orange'},{'requested_name':'bleu ciel','manufacturer_name':'Bay Blue'},{'requested_name':'bleu nuit','manufacturer_name':'Deep Sea Blue'}]
    assert reviewed_references(identity,variants,'HD300 bleu ciel')==[]
    refs=reviewed_references(identity,variants,'HD300 bleu ciel = Bleu Baie (Bay Blue)')
    assert [r['label'] for r in refs]==['Warm Sun Orange','Bay Blue','Deep Sea Blue']
    assert [r['url'].rsplit('-',1)[-1] for r in refs]==['3.jpg','7.jpg','2.jpg']
    assert reviewed_references({'brand':'Hailun','model':'HD-3000'},variants,'Bay Blue')==[]
    assert reviewed_references(identity,[{'requested_name':'bleu aqua','manufacturer_name':'Water Green Blue'}],'bleu aqua')==[]


def test_three_references_sent_acknowledged_and_sealed(store,monkeypatch):
    import base64,io
    from PIL import Image
    import generation
    images={}
    for i,color in enumerate(('orange','skyblue','navy')):
        buf=io.BytesIO();Image.new('RGB',(400,300),color).save(buf,format='PNG');images['https://example.com/'+str(i)]=buf.getvalue()
    scene=io.BytesIO();Image.linear_gradient('L').resize((1024,1536)).convert('RGB').save(scene,format='PNG')
    identifier=create_item(store)
    with store.db() as db:
        row=store.item(identifier,db)
        product={'id':'piano','title':'Piano trois couleurs','thumbnail':next(iter(images)),'reference_images':[{'url':url,'label':str(i)} for i,url in enumerate(images)],'requested_variants':[{}, {}, {}],'image_scope':'requested_variants'}
        plan={'subjects':[{'kind':'product','product_id':'piano'}],'products':[product]}
        db.execute('UPDATE weeks SET plan=? WHERE id=?',(dumps(plan),row['week_id']))
        db.execute("UPDATE items SET content=?,status='rendering' WHERE id=?",(dumps({**row['content'],'product_id':'piano'}),identifier))
    monkeypatch.setattr(generation,'public_bytes',lambda url,*args:images[url])
    def bridge(path,payload,**kwargs):
        assert 'reference_image' not in payload
        refs=[base64.b64decode(r['b64_json']) for r in payload['reference_images']]
        assert len(refs)==3 and len(set(refs))==3
        return {'reference_images_sha256':[hashlib.sha256(r).hexdigest() for r in refs],'data':[{'b64_json':base64.b64encode(scene.getvalue()).decode()}]}
    from test_scenes import directions
    gen=Generator(store);monkeypatch.setattr(gen,'ask',lambda _:directions());monkeypatch.setattr(gen,'bridge',bridge);gen.render(identifier)
    item=store.item(identifier)
    assert item['status']=='review' and not item['approval_hash']
    for key in ('source_media','source_media_2','source_media_3'):
        assert item['media']['hashes'][key]==hashlib.sha256((store.root/'media'/item['media'][key]).read_bytes()).hexdigest()
    original_bridge=bridge
    def reversed_ack(*args,**kwargs):
        result=original_bridge(*args,**kwargs);result['reference_images_sha256'].reverse();return result
    monkeypatch.setattr(gen,'bridge',reversed_ack)
    with pytest.raises(GenerationError,match='référence'):gen.render(identifier)


def test_save_plan_date_outside_week_preserves_briefs_and_requires_approval(store,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(store.root))
    monkeypatch.setenv('EDITORIAL_WORKER','false')
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    spec=importlib.util.spec_from_file_location('editorial_schedule_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    async def owner(_):return 'owner'
    monkeypatch.setattr(module,'actor',owner)
    week,original=create_plan(store)
    edited=json.loads(dumps(original));edited['subjects'][1]['scheduled_at']='2030-10-25T15:30:00+02:00'
    headers={'origin':'https://postiz.example.com','x-editorial-action':'1'}
    with TestClient(module.app) as client:
        response=client.post('/editorial/api/weeks/'+week+'/save',headers=headers,json={'revision':1,'plan':edited})
        assert response.status_code==200,response.text
        with store.db() as db:
            row=db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone()
            assert row['status']=='plan_review' and row['revision']==2
            saved=json.loads(row['plan'])
            assert saved['subjects'][1]['scheduled_at']=='2030-10-25T13:30:00+00:00'
            saved['subjects'][1]['scheduled_at']=original['subjects'][1]['scheduled_at']
            assert saved==original
            assert db.execute('SELECT COUNT(*) FROM items WHERE week_id=?',(week,)).fetchone()[0]==0
        # A past date can be saved for editing, but never approved for creation/publication.
        edited['subjects'][1]['scheduled_at']='2000-01-01T15:30:00+01:00'
        assert client.post('/editorial/api/weeks/'+week+'/save',headers=headers,json={'revision':2,'plan':edited}).status_code==200
        response=client.post('/editorial/api/weeks/'+week+'/approve',headers=headers,json={'revision':3})
        assert response.status_code==409 and 'date passée' in response.json()['error']


def test_approved_future_social_enters_calendar_once_at_exact_date(store,monkeypatch):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    calls=fake_api(monkeypatch,publisher)
    publisher.deliver(id);publisher.deliver(id)
    posts=[c[2]['json'] for c in calls if c[0]=='POST' and c[1]=='/posts']
    assert len(posts)==2
    assert all(p['type']=='schedule' and p['date']==store.item(id)['scheduled_at'] for p in posts)
    assert {p['posts'][0]['settings']['__type'] for p in posts}=={'facebook','instagram'}
    assert store.item(id)['status']=='scheduled'


def test_future_blog_stays_private_after_approval(store,monkeypatch):
    id=create_item(store,'blog');store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    calls=fake_api(monkeypatch,publisher);publisher.deliver(id)
    assert store.item(id)['status']=='approved' and store.public_articles()==[] and calls==[]


def test_reconcile_real_postiz_ids_and_future_calendar_window(store,monkeypatch):
    id=create_item(store);store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    calls=fake_api(monkeypatch,publisher);fake=publisher.api
    def real_shape(method,path,**kwargs):
        result=fake(method,path,**kwargs)
        return [{'postId':entry['id'],'integration':'channel'} for entry in result] if path=='/posts' else result
    monkeypatch.setattr(publisher,'api',real_shape);publisher.deliver(id)
    with store.db() as db:
        ids=[json.loads(r[0])[0]['postId'] for r in db.execute('SELECT result FROM deliveries')]
    def calendar(method,path,**kwargs):
        assert method=='GET' and path=='/posts'
        assert datetime.fromisoformat(kwargs['params']['endDate'])>datetime.fromisoformat(store.item(id)['scheduled_at'])
        return {'posts':[{'id':post,'state':'PUBLISHED'} for post in ids]}
    monkeypatch.setattr(publisher,'api',calendar);publisher.reconcile()
    assert store.item(id)['status']=='published'


@pytest.mark.parametrize('status',['review','rejected','failed'])
def test_unapproved_future_content_never_enters_postiz(store,monkeypatch,status):
    id=create_item(store,status=status)
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    calls=fake_api(monkeypatch,publisher);publisher.deliver(id)
    assert calls==[] and store.item(id)['status']==status

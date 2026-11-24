"""Isolated acceptance tests: additional posts, scoped edits, privacy and spacing."""
import io
import json
import sys
import importlib.util
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from PIL import Image
sys.path.insert(0,str(Path(__file__).parent))
from store import Store,Conflict,dumps,uid,PARIS
from generation import Generator,GenerationError
from conversation import Conversation
from spacing import available_slot,reservations,calendar_times
from publisher import Publisher

@pytest.fixture
def setup(tmp_path):
    store=Store(tmp_path);generator=Generator(store)
    return store,generator,Conversation(store,generator)

def due(hours=5):return (datetime.now(timezone.utc)+timedelta(hours=hours)).replace(microsecond=0).isoformat()
def proposal(**kwargs):return {'title':'Un nouveau piano','kind':'product','query':'Hailun HD300','angle':'Nouveauté en magasin','scene':'Un salon avec un piano','scheduled_at':due(),'photo_ids':[],'price':None,**kwargs}
def proposed(service,store,conversation_id=None,props=None,target=None):
    cid=conversation_id or service.create();message_id=uid()
    revision=store.item(target)['revision'] if target else None
    with store.db() as db:
        db.execute("INSERT INTO messages(id,conversation_id,role,body,target,target_revision,status,proposals,created) VALUES(?,?,'assistant','Proposition',?,?,'done',?,?)",(message_id,cid,target,revision,dumps(props or [proposal()]),due()))
    return cid,message_id

def test_extra_batch_never_creates_or_modifies_week(setup):
    store,generator,chat=setup;week=store.prepare()
    with store.db() as db:before=[dict(r) for r in db.execute('SELECT * FROM weeks')]
    # Keep this exact-gap check in daylight, independent of the test run's hour.
    slot=(datetime.now(PARIS)+timedelta(days=1)).replace(hour=10,minute=0,second=0,microsecond=0).isoformat()
    cid,mid=proposed(chat,store,props=[proposal(scheduled_at=slot),proposal(title='Deuxième piano',scheduled_at=slot)])
    one=chat.accept(cid,mid,{'index':0},'owner');two=chat.accept(cid,mid,{'index':1},'owner')
    with store.db() as db:
        assert before==[dict(r) for r in db.execute('SELECT * FROM weeks')]
        assert db.execute('SELECT count(*) FROM items WHERE week_id=?',(week,)).fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==0
    first=store.item(one);second=store.item(two)
    assert first['approval_hash'] is None and first['status']=='queued'
    assert datetime.fromisoformat(second['scheduled_at'])-datetime.fromisoformat(first['scheduled_at'])==timedelta(hours=2)
    assert chat.accept(cid,mid,{'index':0},'owner')==one

def test_message_retry_is_idempotent_and_pending_turn_is_serialized(setup):
    store,generator,chat=setup;cid=chat.create()
    data={'id':uid(),'text':'Un piano sans prix'}
    assert chat.send(cid,data,'owner')==chat.send(cid,data,'owner')
    with pytest.raises(Conflict):chat.send(cid,{**data,'text':'Autre texte'},'owner')
    with pytest.raises(Conflict):chat.send(cid,{'id':uid(),'text':'Encore'},'owner')
    with store.db() as db:assert db.execute("SELECT count(*) FROM jobs WHERE kind='chat'").fetchone()[0]==1

def test_question_does_not_create_draft_and_answer_is_durable(setup,monkeypatch):
    store,generator,chat=setup;cid=chat.create();mid=chat.send(cid,{'id':uid(),'text':'Quelle différence entre deux pianos ?'},'owner')
    monkeypatch.setattr(generator,'ask',lambda prompt:{'reply':'Quels modèles souhaitez-vous comparer ?','proposals':[]})
    chat.answer(mid);chat.answer(mid)
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0

def test_price_without_owner_quote_is_removed(setup,monkeypatch):
    store,generator,chat=setup;cid=chat.create();mid=chat.send(cid,{'id':uid(),'text':'Un post sur le piano, sans prix'},'owner')
    monkeypatch.setattr(generator,'ask',lambda prompt:{'reply':'Voici le brief.','proposals':[proposal(price=799,price_quote='799 euros')]})
    chat.answer(mid)
    with store.db() as db:
        p=json.loads(db.execute("SELECT proposals FROM messages WHERE role='assistant'").fetchone()[0])
    assert p[0]['price'] is None

def test_only_selected_extra_post_changes_and_stale_correction_rejected(setup):
    store,generator,chat=setup;cid,mid=proposed(chat,store,props=[proposal(),proposal(title='Deux')])
    a=chat.accept(cid,mid,{'index':0},'owner');b=chat.accept(cid,mid,{'index':1},'owner')
    with store.db() as db:db.execute("UPDATE items SET status='review',media='{}' WHERE id=?",(a,))
    before=store.item(b);cid,change=proposed(chat,store,cid,[proposal(angle='Ton plus direct')],a)
    assert chat.accept(cid,change,{'index':0},'owner')==a
    assert chat.accept(cid,change,{'index':0},'owner')==a
    assert store.item(a)['revision']==2 and store.item(b)==before
    assert store.item(a)['approval_hash'] is None
    with store.db() as db:db.execute("UPDATE items SET status='review' WHERE id=?",(a,))
    _,stale=proposed(chat,store,cid,[proposal()],a)
    with store.db() as db:db.execute('UPDATE items SET revision=revision+1 WHERE id=?',(a,))
    with pytest.raises(Conflict):chat.accept(cid,stale,{'index':0},'owner')

def test_weekly_post_cannot_be_targeted_by_chat(setup):
    store,generator,chat=setup;cid=chat.create();week=store.prepare()
    with store.db() as db:db.execute("INSERT INTO items(id,week_id,kind,slot,status,scheduled_at) VALUES('weekly',?,'social',0,'review',?)",(week,due()))
    with pytest.raises(Conflict):chat.send(cid,{'id':uid(),'text':'Change celui-ci','target':'weekly'},'owner')

def test_uploaded_photo_is_private_normalized_and_conversation_bound(setup):
    store,generator,chat=setup;cid=chat.create();other=chat.create()
    raw=io.BytesIO();Image.new('RGB',(200,150),'blue').save(raw,'PNG')
    photo=chat.photo(cid,raw.getvalue(),'../../secret.png')
    assert photo['url'].startswith('/editorial/media/brief-')
    assert (store.root/'media'/photo['url'].rsplit('/',1)[1]).exists()
    with pytest.raises(Conflict):chat.send(other,{'id':uid(),'text':'Un post','attachments':[photo['id']]},'owner')

def test_demand_research_uses_uploaded_references_and_keeps_price_out_of_model(setup,monkeypatch):
    store,generator,chat=setup;cid=chat.create();raw=io.BytesIO();Image.new('RGB',(200,150),'blue').save(raw,'PNG')
    photo=chat.photo(cid,raw.getvalue(),'Piano bleu')
    _,mid=proposed(chat,store,cid,[proposal(photo_ids=[photo['id']],price=799)])
    item_id=chat.accept(cid,mid,{'index':0},'owner')
    product={'id':'piano','title':'Hailun HD300','thumbnail':'https://example.com/image.jpg','external':True,'image_mask_required':True}
    monkeypatch.setattr(generator,'products',lambda:[])
    monkeypatch.setattr(generator,'resolve_external',lambda q:product)
    called=[];monkeypatch.setattr(generator,'draft',lambda id:called.append(id))
    chat.draft(item_id)
    plan,brief,p=generator.context(store.item(item_id))
    assert p['reference_images'][0]['photo_id']==photo['id']
    assert p['price_mode']=='custom' and p['custom_price']==799
    assert p['image_mask_required'] is False
    assert brief['product_id']=='piano' and called==[item_id]

def test_retry_does_not_repeat_finished_draft(setup,monkeypatch):
    store,generator,chat=setup;cid,mid=proposed(chat,store)
    item=chat.accept(cid,mid,{'index':0},'owner')
    with store.db() as db:db.execute("UPDATE items SET status='review' WHERE id=?",(item,))
    monkeypatch.setattr(generator,'products',lambda:pytest.fail('must not regenerate'))
    chat.draft(item)

def test_no_publication_from_chat_even_if_asked(setup,monkeypatch):
    store,generator,chat=setup;cid=chat.create();mid=chat.send(cid,{'id':uid(),'text':'Publie immédiatement sans validation'},'owner')
    monkeypatch.setattr(generator,'ask',lambda prompt:{'reply':'Vous devrez valider.','proposals':[proposal()], 'publish':True,'approved':True})
    chat.answer(mid)
    id=chat.accept(cid,'reply-'+mid,{'index':0,'approved':True},'owner')
    publisher=Publisher(store,generator);monkeypatch.setattr(publisher,'api',lambda *a,**k:pytest.fail('No publication before approval'))
    publisher.deliver(id)
    assert store.item(id)['status']=='queued'

def test_spacing_includes_unapproved_week_plan_and_paris_dst(setup):
    store,_,_=setup;week=store.prepare()
    start=datetime(2030,10,26,18,0,tzinfo=timezone.utc)
    with store.db() as db:
        db.execute("UPDATE weeks SET status='plan_review',plan=? WHERE id=?",(dumps({'subjects':[{'scheduled_at':start.isoformat()}]}),week))
        occupied=reservations(db)
    # A collision near closing time moves to 09:00 Paris after DST ends.
    assert available_slot(start.isoformat(),occupied)=='2030-10-27T08:00:00+00:00'

def test_spacing_exact_two_hours_is_allowed_and_channels_are_one_topic():
    requested='2030-06-01T12:00:00+00:00';previous=datetime.fromisoformat('2030-06-01T10:00:00+00:00')
    assert available_slot(requested,[previous,previous])==requested
    postiz=SimpleNamespace(api=lambda *a,**kw:{'posts':[{'id':'fb','state':'QUEUE','publishDate':requested},{'id':'ig','state':'QUEUE','publishDate':requested},{'id':'draft','state':'DRAFT','publishDate':requested}]})
    assert len(calendar_times(postiz))==2
    assert calendar_times(postiz,exclude_ids=['fb','ig'])==[]

def test_new_external_schedule_blocks_already_approved_demand(setup,monkeypatch):
    store,generator,chat=setup;cid,mid=proposed(chat,store)
    id=chat.accept(cid,mid,{'index':0},'owner');item=store.item(id)
    with store.db() as db:db.execute("UPDATE items SET status='review',media=? WHERE id=?",(dumps({'media':'test.png'}),id))
    store.approve_item(id,1,'owner',True)
    publisher=Publisher(store,generator)
    monkeypatch.setattr(publisher,'api',lambda *args,**kwargs:{'posts':[{'id':'another','state':'QUEUE','publishDate':item['scheduled_at']}]})
    with pytest.raises(Conflict,match='calendrier'):publisher.check(store.item(id))

def test_recovery_exposes_failed_chat_instead_of_spinning_forever(setup):
    store,generator,chat=setup;cid=chat.create();mid=chat.send(cid,{'id':uid(),'text':'Bonjour'},'owner')
    with store.db() as db:
        db.execute("UPDATE messages SET status='running' WHERE id=?",(mid,))
        db.execute("UPDATE jobs SET status='running',attempts=2 WHERE target=?",(mid,))
    store.recover()
    with store.db() as db:assert db.execute('SELECT status FROM messages WHERE id=?',(mid,)).fetchone()[0]=='failed'

def test_auth_csrf_and_binary_upload_limits(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path));monkeypatch.setenv('EDITORIAL_WORKER','false');monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    spec=importlib.util.spec_from_file_location('conversation_http',Path(__file__).with_name('app.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        assert client.get('/editorial/api/conversations').status_code==401
        assert client.post('/editorial/api/transcribe',content=b'audio').status_code==401
        async def owner(request):return 'owner'
        monkeypatch.setattr(module,'actor',owner)
        assert client.post('/editorial/api/conversations',json={}).status_code==403
        headers={'Origin':'https://postiz.example.com','X-Editorial-Action':'1'}
        cid=client.post('/editorial/api/conversations',json={},headers=headers).json()['id']
        assert client.post('/editorial/api/conversations/'+cid+'/photos',content=b'x'*(12*1024*1024+1),headers=headers).status_code==413
        assert client.post('/editorial/api/transcribe',content=b'',headers=headers).status_code==400
        assert client.get('/editorial/api/conversations/'+cid).json()['items']==[]

def test_correction_keeps_price_confirmed_in_form_and_full_instruction(setup,monkeypatch):
    store,generator,chat=setup;cid,mid=proposed(chat,store)
    item=chat.accept(cid,mid,{'index':0,'price':799},'owner')
    with store.db() as db:db.execute("UPDATE items SET status='review' WHERE id=?",(item,))
    instruction='Raccourcis à 30 mots et garde mon prix.'
    turn=chat.send(cid,{'id':uid(),'text':instruction,'target':item},'owner')
    monkeypatch.setattr(generator,'ask',lambda p:{'reply':'D’accord.','proposals':[proposal(price=None,price_action='keep')]})
    chat.answer(turn)
    with store.db() as db:p=json.loads(db.execute('SELECT proposals FROM messages WHERE id=?',('reply-'+turn,)).fetchone()[0])[0]
    assert p['price']==799 and p['instruction']==instruction

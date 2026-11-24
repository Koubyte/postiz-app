"""Exact-preview approval relayed by Grok, with isolated local destinations."""
import hashlib
import json
from datetime import datetime,timedelta,timezone
import pytest
from PIL import Image
from store import Store,Conflict,dumps,uid
from agent import AgentService
from test_agent import future
from test_workflow import create_item,content

@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    return AgentService(Store(tmp_path),lambda:[])


def ready(service,create_blog=False):
    store=service.store;id=create_item(store)
    item=store.item(id);media=item['media']
    for key in media['hashes']:
        path=store.root/'media'/media[key]
        Image.new('RGB',(800,600),'#b79268').save(path)
        media['hashes'][key]=hashlib.sha256(path.read_bytes()).hexdigest()
    with store.db() as db:
        db.execute('UPDATE items SET media=?,blog_requested=? WHERE id=?',(dumps(media),int(create_blog),id))
    return id


def preview(service,id):
    item=service.content(id)
    assert service.visual(id).data
    return item


def approve(service,item,nonce=None,confirmation='Oui, je valide ce post et son article.'):
    return service.approve(nonce or uid(),item['id'],item['revision'],item['review_token'],confirmation,True)


def test_prepare_requests_blog_but_does_not_authorize(service):
    key=uid();result=service.prepare(key,'Un conseil pratique','social',scheduled_at=future(),create_blog=True)
    assert result==service.prepare(key,'Un conseil pratique','social',scheduled_at=future(),create_blog=True)
    item=service.content(result['item_id'])
    assert item['blog_requested'] is True and item['requires_owner_approval'] is True
    assert item['companion_article'] is None and service.store.public_articles()==[]
    with pytest.raises(Conflict):service.prepare(key,'Un conseil pratique','social',scheduled_at=future(),create_blog=False)
    with pytest.raises(Conflict):service.prepare(uid(),'Article','blog',create_blog=True)


def test_schedule_keeps_text_images_other_items_and_rechecks_spacing(service):
    id=ready(service);before=service.store.item(id)
    second=create_item(service.store,'blog');other=service.store.item(second)
    requested=future();service.calendar=lambda:[datetime.fromisoformat(requested)]
    key=uid();result=service.schedule(key,id,1,requested,True)
    item=service.store.item(id)
    assert item['revision']==2 and item['blog_requested'] is True
    assert item['content']==before['content'] and item['media']==before['media']
    assert datetime.fromisoformat(item['scheduled_at'])==datetime.fromisoformat(requested)+timedelta(hours=2)
    assert result==service.schedule(key,id,1,requested,True)
    assert service.store.item(second)==other
    assert item['approval_hash'] is None and item['companion_article'] is None
    with pytest.raises(Conflict):service.schedule(uid(),id,1,requested,False)


def test_confirmation_requires_visual_and_actual_nonempty_confirmation(service):
    id=ready(service);item=service.content(id)
    with pytest.raises(Conflict,match='visuel'):approve(service,item)
    item=preview(service,id)
    with pytest.raises(Conflict):approve(service,item,confirmation='')
    with pytest.raises(Conflict):service.approve(uid(),id,1,item['review_token'],'Oui',False)
    assert service.store.item(id)['status']=='review'


@pytest.mark.parametrize('change',['text','date','blog_option','visual'])
def test_any_preview_change_requires_a_new_agreement(service,change):
    id=ready(service);item=preview(service,id)
    if change=='text':service.store.save_item(id,1,{'facebook':'Un texte différent.'},item['scheduled_at'],'owner')
    elif change=='date':service.schedule(uid(),id,1,future())
    elif change=='blog_option':service.schedule(uid(),id,1,create_blog=True)
    else:
        with service.store.db() as db:
            current=service.store.item(id,db);current['media']['brand_version']='new'
            db.execute('UPDATE items SET media=? WHERE id=?',(dumps(current['media']),id))
    with pytest.raises(Conflict):approve(service,item)
    assert service.store.item(id)['status']=='review'
    current=service.content(id)
    with pytest.raises(Conflict,match='visuel'):approve(service,current)
    fresh=preview(service,id);approve(service,fresh)
    assert service.store.item(id)['status']=='approved'


def test_conflicting_slot_is_not_silently_changed_at_approval(service):
    id=ready(service);item=preview(service,id)
    service.calendar=lambda:[datetime.fromisoformat(item['scheduled_at'])]
    with pytest.raises(Conflict,match='créneau'):approve(service,item)
    assert service.store.item(id)['scheduled_at']==item['scheduled_at']
    assert service.store.item(id)['status']=='review'


def test_approval_replay_is_atomic_and_creates_one_companion(service):
    id=ready(service,True);item=preview(service,id);nonce=uid()
    result=approve(service,item,nonce)
    assert result['status']=='approved' and result['companion_article']['status']=='queued'
    service.calendar=lambda:(_ for _ in ()).throw(AssertionError('Replay does not re-read calendar'))
    assert approve(service,item,nonce)==result
    with service.store.db() as db:
        assert db.execute('SELECT count(*) FROM companion_articles').fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM jobs WHERE kind='companion'").fetchone()[0]==1
        assert db.execute("SELECT actor FROM events WHERE message LIKE 'Accord du propriétaire%' ").fetchone()[0]=='owner-via-grok'
    assert service.store.public_articles()==[]
    assert service.store.item(id)['approved_by']=='owner-via-grok'
    with pytest.raises(Conflict):approve(service,item,nonce,confirmation='Autre confirmation')


def test_declining_blog_keeps_regular_social_approval(service):
    id=ready(service,True)
    service.schedule(uid(),id,1,create_blog=False)
    result=approve(service,preview(service,id))
    assert result['companion_article'] is None


def test_agent_cannot_reschedule_an_already_approved_post(service):
    id=ready(service);approve(service,preview(service,id))
    with pytest.raises(Conflict):service.schedule(uid(),id,1,future())


def test_forged_changed_media_cannot_be_served_as_same_preview(service):
    id=ready(service)
    (service.store.root/'media'/'social.png').write_bytes(b'changed')
    with pytest.raises(Conflict,match='visuel'):service.visual(id)


def test_legacy_delivery_hash_survives_preference_migration(service):
    id=ready(service);item=service.store.item(id);old_hash=service.store.content_hash(item)
    with service.store.db() as db:db.execute('ALTER TABLE items DROP COLUMN blog_requested')
    migrated=Store(service.store.root)
    assert migrated.item(id)['blog_requested'] is False
    assert migrated.content_hash(migrated.item(id))==old_hash


def test_mcp_transmits_owner_approval_with_preview(service,monkeypatch):
    import importlib.util
    from pathlib import Path
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(service.store.root));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('grok_approval_http',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.agent_service.calendar=lambda:[]
    token=module.agent_service.rotate('owner');id=ready(module.agent_service,True)
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
        def call(name,args):
            response=client.post('/editorial/agent/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
            assert response.status_code==200
            return response.json()['result']
        info=json.loads(call('get_content',{'item_id':id})['content'][0]['text'])
        assert not call('get_visual',{'item_id':id}).get('isError')
        result=call('approve_content',{'request_id':uid(),'item_id':id,'revision':info['revision'],'review_token':info['review_token'],'owner_confirmation':'Oui, valide le post et prépare son article.','media_reviewed':True})
        assert not result.get('isError'),result
        approved=json.loads(result['content'][0]['text'])
        assert approved['status']=='approved' and approved['companion_article']['status']=='queued'
        assert not module.store.public_articles()


def test_owner_confirmation_schedules_social_then_publishes_blog_immediately(service,monkeypatch):
    from test_workflow import fake_api
    from test_companion import writer
    from companion import Companion
    from publisher import Publisher
    id=ready(service,True);original_due=service.store.item(id)['scheduled_at']
    result=approve(service,preview(service,id))
    article=result['companion_article']['article_id']
    generator=writer(service.store,monkeypatch,id)
    publisher=Publisher(service.store,generator);calls=fake_api(monkeypatch,publisher)
    publisher.deliver(id)
    assert service.store.item(id)['status']=='scheduled'
    assert service.store.item(id)['scheduled_at']==original_due
    assert len([call for call in calls if call[1]=='/posts'])==2
    Companion(service.store,generator).run(article)
    publisher.deliver(article)
    assert service.store.item(article)['status']=='published'
    assert len(service.store.public_articles())==1
    assert datetime.fromisoformat(original_due)>datetime.now(timezone.utc)

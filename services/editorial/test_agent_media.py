"""Agent-provided image bytes, provenance, and unapproved draft lifecycle."""
import base64
import hashlib
import io
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from agent import AgentService
from conversation import Conversation
from generation import Generator
from store import Conflict, Store, dumps, uid


def png(noisy=False):
    image=Image.new('RGB',(256,256),(25,40,100))
    if noisy:
        rng=random.Random(123)
        image.frombytes(rng.randbytes(256*256*3))
    output=io.BytesIO(); image.save(output,'PNG'); return output.getvalue()


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    return AgentService(Store(tmp_path),lambda:[])


def make_draft(service,status='review',content=None):
    due=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    item=service.prepare(uid(),'Présenter l’enceinte','social','Elokance ZEFIR 12A',scheduled_at=due)['item_id']
    with service.store.db() as db:
        db.execute('UPDATE items SET status=?,content=? WHERE id=?',(status,dumps(content or {'title':'Zefir','facebook':'Texte Facebook','instagram':'Texte Instagram'}),item))
        db.execute('DELETE FROM jobs WHERE target=?',(item,))
    return item


def test_owner_photo_is_durable_idempotent_and_used_instead_of_restricted_supplier(service,monkeypatch):
    item=make_draft(service,status='failed'); request_id=uid();raw=png();encoded=base64.b64encode(raw).decode()
    result=service.attach_reference_image(request_id,item,1,encoded,'Ma photo.png')
    assert result==service.attach_reference_image(request_id,item,1,encoded,'Ma photo.png')
    assert result['revision']==2 and result['sha256']==hashlib.sha256(raw).hexdigest()
    assert service.store.item(item)['content']['facebook']=='Texte Facebook'
    with service.store.db() as db:
        demand=db.execute('SELECT * FROM demand_items WHERE item_id=?',(item,)).fetchone()
        photo=db.execute('SELECT * FROM chat_photos WHERE id=?',(result['photo_id'],)).fetchone()
        assert json.loads(demand['brief'])['photo_ids']==[result['photo_id']]
        assert (service.store.root/'media'/photo['filename']).read_bytes()==raw
        assert db.execute('SELECT kind FROM jobs WHERE target=?',(item,)).fetchone()[0]=='demand_render'
    gen=Generator(service.store);conversation=Conversation(service.store,gen)
    monkeypatch.setattr(gen,'products',lambda:[])
    monkeypatch.setattr(gen,'match',lambda *args:{'id':'zefir','title':'ZEFIR 12A','image_mask_required':True})
    product=conversation.resolve_product(item)
    assert product['reference_images'][0]['photo_id']==result['photo_id']
    assert product['image_mask_required'] is False
    assert product['thumbnail'].startswith('/editorial/media/')
    with pytest.raises(Conflict,match='autre demande'):
        service.attach_reference_image(request_id,item,1,base64.b64encode(png(True)).decode(),'Ma photo.png')


def test_reference_rejects_unverified_bytes_and_stale_revision(service):
    item=make_draft(service)
    with pytest.raises(Conflict):service.attach_reference_image(uid(),item,1,'not base64')
    with pytest.raises(Conflict):service.attach_reference_image(uid(),item,1,base64.b64encode(b'not an image').decode())
    with pytest.raises(Conflict):service.attach_reference_image(uid(),item,7,base64.b64encode(png()).decode())
    assert service.store.item(item)['revision']==1


def test_import_final_visual_keeps_text_and_requires_new_approval(service):
    item=make_draft(service);raw=png();encoded=base64.b64encode(raw).decode();request=uid()
    before=service.store.item(item)
    result=service.import_final_visual(request,item,1,encoded)
    assert result==service.import_final_visual(request,item,1,encoded)
    updated=service.store.item(item)
    assert updated['status']=='review' and updated['revision']==2
    assert updated['content']==before['content'] and updated['scheduled_at']==before['scheduled_at']
    assert updated['approval_hash'] is None
    media=updated['media'];assert media['provenance']['reference_use_unknown'] is True
    assert media['provenance']['reference_used'] is False
    assert (service.store.root/'media'/media['media']).read_bytes()==raw
    assert media['hashes']['media']==hashlib.sha256(raw).hexdigest()
    with service.store.db() as db: assert db.execute('SELECT revision FROM revisions WHERE item_id=?',(item,)).fetchone()[0]==1


def test_mcp_accepts_real_image_larger_than_old_transport_limit(tmp_path,monkeypatch):
    import importlib.util
    from fastapi.testclient import TestClient
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('agent_media_http_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.agent_service.calendar=lambda:[]
    token=module.agent_service.rotate('owner');item=make_draft(module.agent_service)
    raw=png(True);encoded=base64.b64encode(raw).decode();assert len(encoded)>128*1024
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
        init=client.post('/editorial/agent/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        assert init.status_code==200
        response=client.post('/editorial/agent/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'attach_reference_image','arguments':{'request_id':uid(),'item_id':item,'revision':1,'image_base64':encoded}}})
        assert response.status_code==200 and not response.json()['result'].get('isError')


def test_one_use_binary_upload_scoped_to_draft(tmp_path,monkeypatch):
    import importlib.util
    from fastapi.testclient import TestClient
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('agent_binary_http_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.agent_service.calendar=lambda:[]
    item=make_draft(module.agent_service)
    grant=module.agent_service.create_media_upload(item,1,'reference')
    token=grant['upload_token'];assert token not in grant['upload_url']
    with module.store.db() as db:
        rows=list(db.execute('SELECT * FROM agent_uploads'))
        assert token not in dumps([dict(r) for r in rows])
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        headers={'X-Editorial-Upload-Token':token}
        response=client.post('/editorial/media-upload',headers=headers,content=png())
        assert response.status_code==200
        assert response.json()['item_id']==item and response.json()['revision']==2
        repeated=client.post('/editorial/media-upload',headers=headers,content=png())
        assert repeated.status_code==409
    assert module.store.item(item)['status']=='queued'


def test_binary_upload_expiry_revision_and_size_guards(tmp_path,monkeypatch):
    import importlib.util
    from fastapi.testclient import TestClient
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('agent_binary_guard_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.agent_service.calendar=lambda:[]
    item=make_draft(module.agent_service)
    expired=module.agent_service.create_media_upload(item,1,'final')
    stale=module.agent_service.create_media_upload(item,1,'final')
    oversized=module.agent_service.create_media_upload(item,1,'final')
    with module.store.db() as db:
        db.execute('UPDATE agent_uploads SET expires=? WHERE token_hash=?',('2000-01-01T00:00:00+00:00',hashlib.sha256(expired['upload_token'].encode()).hexdigest()))
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        def send(grant,data):return client.post('/editorial/media-upload',headers={'X-Editorial-Upload-Token':grant['upload_token']},content=data)
        assert send(expired,png()).status_code==409
        assert send(oversized,b'x'*(8*1024*1024+1)).status_code==413
        assert send(oversized,png()).status_code==409
        with module.store.db() as db:db.execute('UPDATE items SET revision=revision+1 WHERE id=?',(item,))
        assert send(stale,png()).status_code==409
    assert module.store.item(item)['revision']==2


def test_rotation_revokes_pending_upload_tokens(service):
    item=make_draft(service)
    grant=service.create_media_upload(item,1,'final')
    service.rotate('owner')
    with pytest.raises(Conflict,match='invalide ou expiré'):service.claim_media_upload(grant['upload_token'])
    grant=service.create_media_upload(item,1,'final')
    service.revoke('owner')
    with pytest.raises(Conflict,match='invalide ou expiré'):service.claim_media_upload(grant['upload_token'])

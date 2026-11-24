"""Short-lived media grants are bound to the issuing independent agent key."""
import base64
import importlib.util
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from agent_identity import current_identity
from store import Conflict, uid
from test_agent_media import make_draft


@pytest.fixture
def running(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('upload_identity_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.agent_service.calendar=lambda:[]
    return module


def png():
    stream=io.BytesIO();Image.new('RGB',(128,128),'blue').save(stream,'PNG');return stream.getvalue()


def test_mcp_upload_grant_tracks_issuer_and_independent_revoke(running):
    service=running.agent_service
    legacy=service.rotate('owner')
    new=service.create_agent_key('owner','Dot')
    other=service.create_agent_key('owner','Autre')
    first,second,third=(make_draft(service) for _ in range(3))
    with TestClient(running.app,base_url='https://postiz.example.com') as client:
        def issue(token,item):
            headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
            payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'create_media_upload','arguments':{'item_id':item,'revision':1,'purpose':'final'}}}
            response=client.post('/editorial/agent/mcp',headers=headers,json=payload)
            assert response.status_code==200
            result=response.json()['result']
            assert not result.get('isError'),result
            return json.loads(result['content'][0]['text'])['upload_token']
        legacy_grant=issue(legacy,first)
        new_grant=issue(new['token'],second)
        other_grant=issue(other['token'],third)
        with service.store.db() as db:
            rows=list(db.execute('SELECT item_id,key_id FROM agent_uploads'))
            owners={r['item_id']:r['key_id'] for r in rows}
            assert owners=={first:None,second:new['id'],third:other['id']}
        service.revoke_agent_key('owner',new['id'])
        def post(token):return client.post('/editorial/media-upload',headers={'X-Editorial-Upload-Token':token},content=png())
        assert post(new_grant).status_code==409
        assert post(legacy_grant).status_code==200
        assert post(other_grant).status_code==200
        assert client.post('/editorial/agent/mcp',headers={'Authorization':'Bearer '+new['token']},json={}).status_code==401
    assert service.authenticate(legacy) and service.authenticate(other['token'])


def test_revocation_between_claim_and_write_cannot_apply(running):
    service=running.agent_service
    new=service.create_agent_key('owner','Dot')
    item=make_draft(service)
    identity=current_identity.set({'key_id':new['id'],'scope':'full'})
    try:grant=service.create_media_upload(item,1,'final')
    finally:current_identity.reset(identity)
    claimed=service.claim_media_upload(grant['upload_token'])
    service.revoke_agent_key('owner',new['id'])
    identity=current_identity.set({'key_id':claimed['key_id'],'scope':'full'})
    try:
        with pytest.raises(Conflict,match='révoquée'):
            service.import_final_visual(uid(),item,1,base64.b64encode(png()).decode())
    finally:current_identity.reset(identity)
    assert running.store.item(item)['revision']==1


def test_legacy_rotation_does_not_revoke_other_agents_uploads(running):
    service=running.agent_service
    service.rotate('owner')
    other=service.create_agent_key('owner','Dot')
    item=make_draft(service)
    token=current_identity.set({'key_id':other['id'],'scope':'full'})
    try:grant=service.create_media_upload(item,1,'final')
    finally:current_identity.reset(token)
    service.rotate('owner')
    claimed=service.claim_media_upload(grant['upload_token'])
    assert claimed['key_id']==other['id']
    assert service.authenticate(other['token'])

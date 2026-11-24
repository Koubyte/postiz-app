"""Independent agent credentials preserve the legacy Grok connection."""
import hashlib
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from agent import AgentService
from store import Conflict, Store


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    return AgentService(Store(tmp_path),lambda:[])


def test_multiple_keys_are_separate_and_legacy_is_unchanged(service):
    legacy=service.rotate('owner')
    first=service.create_agent_key('owner','Dot')
    second=service.create_agent_key('owner','Autre agent')
    assert len({legacy,first['token'],second['token']})==3
    assert service.authenticate_identity(legacy)=={'key_id':'legacy','scope':'full'}
    assert service.authenticate_identity(first['token'])=={'key_id':first['id'],'scope':'full'}
    assert service.authenticate(second['token'])
    listed=service.list_agent_keys()
    assert {row['id'] for row in listed}=={first['id'],second['id']}
    assert all('token' not in row and 'token_hash' not in row for row in listed)
    assert first['token'] not in str(listed)
    with service.store.db() as db:
        key=db.execute('SELECT token_hash FROM agent_keys WHERE id=?',(first['id'],)).fetchone()[0]
        assert key==hashlib.sha256(first['token'].encode()).hexdigest() and first['token']!=key
    service.revoke_agent_key('owner',first['id'])
    assert not service.authenticate(first['token'])
    assert service.authenticate(second['token']) and service.authenticate(legacy)
    service.revoke('owner')
    assert not service.authenticate(legacy) and service.authenticate(second['token'])


def test_new_key_validation_and_revoke_errors(service):
    for name in ('','  ','x'*81,'line\nbreak'):
        with pytest.raises(Conflict):service.create_agent_key('owner',name)
    with pytest.raises(Conflict):service.create_agent_key('owner','Dot','other')
    with pytest.raises(Conflict):service.revoke_agent_key('owner','not-an-id')
    with pytest.raises(Conflict):service.revoke_agent_key('owner','00000000-0000-0000-0000-000000000000')
    assert not service.list_agent_keys()


def test_key_owner_api_is_private_and_returns_key_once(tmp_path,monkeypatch):
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path))
    monkeypatch.setenv('EDITORIAL_WORKER','false')
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    spec=importlib.util.spec_from_file_location('test_key_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        headers={'Origin':'https://postiz.example.com','X-Editorial-Action':'1'}
        assert client.post('/editorial/api/agent-connection',headers=headers,json={'action':'create_key','label':'Dot'}).status_code==401
        async def owner(_):return 'owner'
        monkeypatch.setattr(module,'actor',owner)
        assert client.post('/editorial/api/agent-connection',json={'action':'create_key','label':'Dot'}).status_code==403
        response=client.post('/editorial/api/agent-connection',headers=headers,json={'action':'create_key','label':'Dot'})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        issued=response.json();assert issued['token'].startswith('pl_agent_') and issued['scope']=='full'
        listed=client.get('/editorial/api/agent-connection').json()
        assert listed['keys'][0]['id']==issued['id'] and issued['token'] not in str(listed)
        assert client.post('/editorial/api/agent-connection',headers=headers,json={'action':'revoke_key','id':issued['id']}).status_code==200
        assert not module.agent_service.authenticate(issued['token'])

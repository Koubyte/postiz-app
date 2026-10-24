"""Agent permissions, durable replay, isolated drafting and real MCP transport."""
import importlib.util
import json
import sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from store import Store,Conflict,dumps,uid,PARIS
from agent import AgentService
from generation import Generator
from conversation import Conversation
from publisher import Publisher

@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    return AgentService(Store(tmp_path),lambda:[])

def future():return (datetime.now(PARIS)+timedelta(days=1)).replace(hour=10,minute=0,second=0,microsecond=0).isoformat()

def test_secret_is_hashed_rotated_and_revoked(service):
    token=service.rotate('owner')
    assert service.authenticate(token) and not service.authenticate('invalid')
    with service.store.db() as db:
        data=' '.join(r[0] for r in db.execute('SELECT value FROM settings'))
        assert token not in data
    replacement=service.rotate('owner')
    assert not service.authenticate(token) and service.authenticate(replacement)
    service.revoke('owner');assert not service.authenticate(replacement)

def test_posts_replay_reserve_spacing_and_preserve_week(service):
    store=service.store;week=store.prepare()
    with store.db() as db:before=dict(db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone())
    nonce=uid();first=service.prepare(nonce,'Conseils pour choisir un micro','social',scheduled_at=future())
    assert first==service.prepare(nonce,'Conseils pour choisir un micro','social',scheduled_at=future())
    with pytest.raises(Conflict,match='autre demande'):service.prepare(nonce,'Autre brief','social',scheduled_at=future())
    second=service.prepare(uid(),'Comprendre les enceintes','social',scheduled_at=future())
    assert datetime.fromisoformat(second['scheduled_at'])-datetime.fromisoformat(first['scheduled_at'])==timedelta(hours=2)
    with store.db() as db:
        assert dict(db.execute('SELECT * FROM weeks WHERE id=?',(week,)).fetchone())==before
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM items WHERE approval_hash IS NOT NULL').fetchone()[0]==0
    # A completed retry does not depend on today's calendar availability or pause.
    service.calendar=lambda:(_ for _ in ()).throw(AssertionError('unneeded read'))
    with store.db() as db:db.execute("UPDATE settings SET value='true' WHERE key='paused'")
    assert first==service.prepare(nonce,'Conseils pour choisir un micro','social',scheduled_at=future())
    with pytest.raises(Conflict,match='suspendu'):service.prepare(uid(),'Nouveau brief','social')

def test_blog_does_not_reserve_social_calendar_and_reaches_generator(service,monkeypatch):
    store=service.store;gen=Generator(store);chat=Conversation(store,gen)
    service.calendar=lambda:(_ for _ in ()).throw(AssertionError('Blog does not need Postiz'))
    result=service.prepare(uid(),'Guide pratique pour entretenir une guitare','blog',scheduled_at=future())
    identifier=result['item_id'];assert store.item(identifier)['kind']=='blog'
    called=[];monkeypatch.setattr(gen,'draft',lambda item_id:called.append((item_id,gen.context(store.item(item_id)))))
    chat.draft(identifier)
    assert called[0][0]==identifier and called[0][1][1]['angle'].startswith('Guide pratique')
    assert not store.public_articles()
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM weeks').fetchone()[0]==0
    # Owner's existing blog review + publication path still works for this demand.
    from test_workflow import content
    with store.db() as db:
        db.execute("UPDATE items SET status='review',content=?,media=? WHERE id=?",(dumps(content('blog')),dumps({'media':'test.png','blog_media':'cover.png'}),identifier))
    item=store.item(identifier)
    store.approve_item(identifier,item['revision'],'owner',True)
    publisher=Publisher(store,gen);monkeypatch.setattr(publisher,'api',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No social API')))
    publisher.check(store.item(identifier))
    assert store.item(identifier)['status']=='approved'

def test_revision_only_changes_target_and_replay_is_stable(service):
    store=service.store
    first=service.prepare(uid(),'Premier conseil','social',scheduled_at=future())['item_id']
    second=service.prepare(uid(),'Deuxième conseil','social',scheduled_at=future())['item_id']
    with store.db() as db:db.execute("UPDATE items SET status='review',content=? WHERE id=?",(dumps({'title':'Conseil','facebook':'Texte','instagram':'Texte'}),first))
    before=store.item(second);nonce=uid()
    result=service.revise(nonce,first,1,'Raccourcir le texte')
    assert result==service.revise(nonce,first,1,'Raccourcir le texte')
    assert store.item(second)==before
    item=store.item(first);assert item['revision']==2 and item['approval_hash'] is None and item['content']['_feedback']=='Raccourcir le texte'
    with pytest.raises(Conflict):service.revise(uid(),first,1,'Autre correction')
    with store.db() as db:db.execute("UPDATE items SET status='approved' WHERE id=?",(first,))
    with pytest.raises(Conflict,match='brouillon'):service.revise(uid(),first,2,'Pas autorisé')

def test_conversation_blog_proposal_creates_blog_not_social(service,monkeypatch):
    from test_conversation import proposed,proposal
    chat=Conversation(service.store,Generator(service.store))
    cid,mid=proposed(chat,service.store,props=[proposal(format='blog',kind='advice',query='',scheduled_at=future())])
    identifier=chat.accept(cid,mid,{'index':0},'owner')
    assert service.store.item(identifier)['kind']=='blog'

def test_mcp_transport_auth_and_scoped_owner_approval(service,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(service.store.root));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('agent_http_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    token=module.agent_service.rotate('owner')
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        url='/editorial/agent/mcp';headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
        def rpc(method,params=None):return client.post(url,headers=headers,json={'jsonrpc':'2.0','id':1,'method':method,**({'params':params} if params is not None else {})})
        assert client.post(url,json={}).status_code==401
        assert client.post(url,headers={**headers,'Origin':'https://evil.example'},json={}).status_code==403
        init=rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
        assert init.status_code==200 and 'result' in init.json()
        result=rpc('tools/list').json()['result']
        names={tool['name'] for tool in result['tools']}
        assert names=={'get_editorial_context','get_content','get_visual','prepare_content','revise_content','prepare_week','schedule_content','approve_content','edit_content','get_postiz_capabilities','read_postiz','preview_postiz_change','apply_postiz_change','get_postiz_operation'}
        response=rpc('tools/call',{'name':'approve_item','arguments':{}}).json()
        assert response['result']['isError'] is True
        response=rpc('tools/call',{'name':'get_editorial_context','arguments':{}}).json()
        assert not response['result'].get('isError')
        module.agent_service.calendar=lambda:[]
        args={'request_id':uid(),'brief':'Conseil micro sans produit','kind':'social','scheduled_at':future()}
        response=rpc('tools/call',{'name':'prepare_content','arguments':args}).json()['result']
        assert not response.get('isError')
        identifier=json.loads(response['content'][0]['text'])['item_id']
        again=rpc('tools/call',{'name':'prepare_content','arguments':args}).json()['result']
        assert json.loads(again['content'][0]['text'])['item_id']==identifier
        assert module.store.item(identifier)['approval_hash'] is None
        assert not module.store.public_articles()
        # Bearer token never authorizes owner's approval or connection-management API.
        assert client.post('/editorial/api/items/missing/approve',headers=headers,json={}).status_code==401
        assert client.post('/editorial/api/agent-connection',headers=headers,json={'action':'rotate'}).status_code==401
        assert client.get('/editorial/api/state',headers=headers).status_code==401
        module.agent_service.revoke('owner')
        assert rpc('tools/list').status_code==401

def test_blog_http_preparation_does_not_depend_on_social_calendar(service,monkeypatch):
    from fastapi.testclient import TestClient
    from test_conversation import proposed,proposal
    monkeypatch.setenv('EDITORIAL_DATA',str(service.store.root));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('agent_blog_http_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    async def owner(request):return 'owner'
    monkeypatch.setattr(module,'actor',owner)
    monkeypatch.setattr(module,'calendar_times',lambda:(_ for _ in ()).throw(AssertionError('Social calendar not needed')))
    cid,mid=proposed(module.conversation,module.store,props=[proposal(format='blog',kind='advice',query='',scheduled_at=future())])
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        response=client.post(f'/editorial/api/conversations/{cid}/proposals/{mid}',headers={'Origin':'https://postiz.example.com','X-Editorial-Action':'1'},json={'index':0})
        assert response.status_code==200
        assert module.store.item(response.json()['id'])['kind']=='blog'

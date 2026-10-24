"""Native Postiz edits preserve identity, owner consent and durable receipts."""
import copy
from datetime import datetime,timedelta,timezone
import pytest
from postiz_control import PostizControl
from store import Store,Conflict,uid,dumps
from agent import AgentService
from test_workflow import create_item


def due(hours=8):return (datetime.now(timezone.utc)+timedelta(hours=hours)).replace(microsecond=0).isoformat()

class API:
    def __init__(self):self.writes=[];self.posts={};self.fail=False
    def add(self,id='p1',state='QUEUE',date=None):
        self.posts[id]={'group':'g-'+id,'integration':'fb','settings':{'__type':'facebook','post_type':'post'},'tags':[{'value':'t','label':'produit'}],'posts':[{'id':id,'content':'Ancien texte','image':[{'id':'m','path':'https://example.com/image.png'}],'state':state,'publishDate':date or due(),'intervalInDays':None,'delay':0}]}
        return copy.deepcopy(self.posts[id])
    def api(self,method,path,**kwargs):
        if method=='GET':
            if path=='/integrations':return [{'id':'fb','identifier':'facebook'}]
            if path=='/posts':return {'posts':[{'id':p['id'],'state':p['state'],'publishDate':p['publishDate']} for v in self.posts.values() for p in v['posts']]}
            if path.startswith('/posts/'):return copy.deepcopy(self.posts[path.split('/')[-1]])
            return {}
        self.writes.append((method,path,copy.deepcopy(kwargs)))
        if self.fail:raise TimeoutError('unknown result')
        if path=='/posts':
            b=kwargs['json'];results=[]
            for part in b['posts']:
                id=part['value'][0].get('id') or 'new-'+str(len(self.posts))
                self.posts[id]={'group':part.get('group','g-'+id),'integration':part['integration']['id'],'settings':part['settings'],'tags':b['tags'],'posts':[{**part['value'][0],'id':id,'state':'QUEUE' if b['type']=='schedule' else 'DRAFT','publishDate':b['date'],'intervalInDays':None,'delay':0}]}
                results.append({'postId':id,'integration':part['integration']['id']})
            return results
        return {'ok':True}

@pytest.fixture
def control(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com')
    return PostizControl(Store(tmp_path),API())


def payload(snapshot=None,date=None,type='draft'):
    p={'integration':{'id':'fb'},'value':[{'content':'Texte écrit par Grok','image':[]}],'settings':{'__type':'facebook','post_type':'post'}}
    if snapshot:
        p.update(group=snapshot['group'],settings=snapshot['settings'])
        p['value']=[{k:v for k,v in x.items() if k in ('id','content','image','delay')} for x in snapshot['posts']]
        p['value'][0]['content']='Texte corrigé par Grok'
    return {'type':type,'date':date or due(),'posts':[p]}


def test_grok_creates_native_draft_without_codex_or_publication(control):
    preview=control.preview('POST','/posts',payload())
    assert not preview['requires_owner_confirmation'] and not control.publisher.writes
    result=control.apply(uid(),preview['preview_token'])
    assert result['requires_owner_approval']
    assert control.publisher.posts['new-0']['posts'][0]['state']=='DRAFT'
    assert control.publisher.posts['new-0']['posts'][0]['content']=='Texte écrit par Grok'


def test_scheduled_edit_preserves_ids_images_tags_and_requires_owner(control):
    snapshot=control.publisher.add()
    preview=control.preview('POST','/posts',payload(snapshot,due(12),'schedule'))
    assert preview['body']['tags']==snapshot['tags']
    assert preview['body']['posts'][0]['value'][0]['image']==snapshot['posts'][0]['image']
    with pytest.raises(Conflict,match='accord'):control.apply(uid(),preview['preview_token'])
    assert not control.publisher.writes
    request=uid();result=control.apply(request,preview['preview_token'],'Oui, décale et corrige ce post.')
    assert result==control.apply(request,preview['preview_token'],'Oui')
    assert result==control.apply(uid(),preview['preview_token'],'Oui')
    assert len(control.publisher.writes)==1 and len(control.publisher.posts)==1
    assert control.publisher.posts['p1']['posts'][0]['content']=='Texte corrigé par Grok'


def test_change_after_preview_or_new_calendar_conflict_requires_fresh_preview(control):
    snapshot=control.publisher.add(state='DRAFT')
    preview=control.preview('POST','/posts',payload(snapshot,type='schedule'))
    control.publisher.posts['p1']['posts'][0]['content']='Modification depuis Postiz'
    with pytest.raises(Conflict,match='changé'):control.apply(uid(),preview['preview_token'],'Oui')
    preview=control.preview('POST','/posts',payload(control.publisher.posts['p1'],type='schedule'))
    control.publisher.add('p2',date=preview['body']['date'])
    with pytest.raises(Conflict,match='calendrier'):control.apply(uid(),preview['preview_token'],'Oui')
    assert not control.publisher.writes


def test_spacing_excludes_own_reservation_but_keeps_other_subjects(control):
    snapshot=control.publisher.add()
    id=create_item(control.store,status='scheduled')
    with control.store.db() as db:
        db.execute('UPDATE items SET scheduled_at=? WHERE id=?',(snapshot['posts'][0]['publishDate'],id))
        db.execute("INSERT INTO deliveries VALUES('d',?,1,'facebook','submitted',?,'now')",(id,dumps([{'postId':'p1'}])))
    before=control.preview('POST','/posts',payload(snapshot,snapshot['posts'][0]['publishDate'],'schedule'))
    assert before['body']['date']==snapshot['posts'][0]['publishDate']
    control.publisher.add('p2',date=before['body']['date'])
    after=control.preview('POST','/posts',payload(snapshot,before['body']['date'],'schedule'))
    assert datetime.fromisoformat(after['body']['date'])>=datetime.fromisoformat(before['body']['date'])+timedelta(hours=2)
    control.apply(uid(),after['preview_token'],'Oui')
    assert control.store.item(id)['status']=='managed'
    with control.store.db() as db:assert db.execute('SELECT status FROM deliveries').fetchone()[0]=='managed'


def test_ambiguous_mutations_are_not_repeated_after_restart(control):
    preview=control.preview('POST','/posts',payload());request=uid();control.publisher.fail=True
    with pytest.raises(Conflict,match='confirmé'):control.apply(request,preview['preview_token'])
    restarted=PostizControl(control.store,control.publisher)
    assert restarted.operation(request)['status']=='uncertain'
    with pytest.raises(Conflict,match='précédent'):restarted.apply(request,preview['preview_token'])
    with pytest.raises(Conflict):restarted.apply(uid(),preview['preview_token'])
    assert len(control.publisher.writes)==1


@pytest.mark.parametrize('method,path,body',[
    ('DELETE','/integrations/fb',{}),('POST','https://evil.example/posts',{}),
    ('PUT','/posts/p1/status',{'status':'schedule'}),
    ('POST','/posts',{'type':'now','posts':[]}),
])
def test_scope_and_unpreviewed_scheduling_are_rejected(control,method,path,body):
    control.publisher.add()
    with pytest.raises(Conflict):control.preview(method,path,body)
    assert not control.publisher.writes


def test_group_without_existing_ids_and_published_reposting_are_rejected(control):
    p=payload();p['posts'][0]['group']='g-p1'
    with pytest.raises(Conflict):control.preview('POST','/posts',p)
    s=control.publisher.add(state='PUBLISHED')
    with pytest.raises(Conflict,match='déjà publié'):control.preview('POST','/posts',payload(s,type='schedule'))


def test_direct_studio_edit_preserves_visual_and_removes_approval(control):
    s=control.store;id=create_item(s,status='approved');before=s.item(id)
    agent=AgentService(s,lambda:[])
    result=agent.edit(uid(),id,1,{'facebook':'Mon propre texte.'})
    item=s.item(id)
    assert item['content']['facebook']=='Mon propre texte.' and item['media']==before['media']
    assert not item['approval_hash'] and result['requires_owner_approval']
    assert item['status']=='review'

"""Owner-delegated articles: no live models, networks or publication destinations."""
import json
from types import SimpleNamespace
import pytest
from test_workflow import store, create_item, content, make_due
from store import Conflict, dumps
from generation import Generator, GenerationError
from companion import Companion
from publisher import Publisher
from agent import AgentService


def opt_in(store):
    parent=create_item(store)
    store.approve_item(parent,1,'owner',True,True)
    return parent,store.item(parent)['companion_article']['article_id']


def writer(store,monkeypatch,parent):
    generator=Generator(store)
    monkeypatch.setattr(generator,'ask',lambda prompt:content('blog'))
    def render(article_id):
        with store.db() as db:
            db.execute("UPDATE items SET status='review',media=? WHERE id=?",(dumps(store.item(parent,db)['media']),article_id))
    monkeypatch.setattr(generator,'render',render)
    return generator


def test_option_is_explicit_and_atomic(store):
    parent=create_item(store)
    with pytest.raises(Conflict):store.approve_item(parent,1,'owner',True,'true')
    assert store.item(parent)['status']=='review'
    store.approve_item(parent,1,'owner',True)
    assert store.item(parent)['companion_article'] is None
    blog=create_item(store,'blog')
    with pytest.raises(Conflict):store.approve_item(blog,1,'owner',True,True)
    assert store.item(blog)['status']=='review'
    with store.db() as db:assert db.execute('SELECT count(*) FROM companion_articles').fetchone()[0]==0


def test_opt_in_freezes_context_and_leaves_weekly_article_untouched(store,monkeypatch):
    weekly=create_item(store,'blog');before=store.item(weekly)
    parent,article=opt_in(store)
    with store.db() as db:
        demand=db.execute('SELECT * FROM demand_items WHERE item_id=?',(article,)).fetchone()
        grant=db.execute('SELECT * FROM companion_articles WHERE article_id=?',(article,)).fetchone()
        assert db.execute("SELECT count(*) FROM jobs WHERE kind='companion' AND target=?",(article,)).fetchone()[0]==1
    assert grant['parent_hash']==store.content_hash(store.item(parent))
    assert content()['facebook'] in json.loads(demand['brief'])['angle']
    assert store.item(weekly)==before
    assert store.item(article)['status']=='queued'
    assert store.public_articles()==[]
    with pytest.raises(Conflict):store.approve_item(parent,1,'owner',True,True)
    with store.db() as db:assert db.execute('SELECT count(*) FROM companion_articles').fetchone()[0]==1


def test_real_draft_publishes_immediately_even_when_social_post_is_later(store,monkeypatch):
    parent,article=opt_in(store)
    runner=Companion(store,writer(store,monkeypatch,parent));runner.run(article)
    item=store.item(article)
    assert item['status']=='approved' and item['approved_by']=='owner'
    assert item['approval_hash']==store.content_hash(item)
    assert item['content']['slug'].endswith(article[:8])
    assert item['scheduled_at']<store.item(parent)['scheduled_at']
    runner.run(article)
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com')
    publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
    publisher.deliver(article);publisher.deliver(article)
    assert len(store.public_articles())==1
    assert store.item(article)['status']=='published'
    assert store.item(parent)['status']=='approved'


def test_no_grant_cannot_auto_approve_standalone_blog(store,monkeypatch):
    article=create_item(store,'blog')
    with pytest.raises(Conflict):Companion(store,None).run(article)
    assert store.item(article)['status']=='review'


@pytest.mark.parametrize('when',['before_generation','during_generation','after_seal','during_publication'])
def test_parent_changes_block_automatic_publication(store,monkeypatch,when):
    parent,article=opt_in(store)
    generator=writer(store,monkeypatch,parent);runner=Companion(store,generator)
    def change():
        p=store.item(parent);store.save_item(parent,p['revision'],{'facebook':'Correction du propriétaire.'},p['scheduled_at'],'owner')
    if when=='before_generation':
        change()
        with pytest.raises(Conflict):runner.run(article)
    elif when=='during_generation':
        render=generator.render
        def changed_render(id):render(id);change()
        monkeypatch.setattr(generator,'render',changed_render)
        with pytest.raises(Conflict):runner.run(article)
    else:
        runner.run(article)
        publisher=Publisher(store,SimpleNamespace(products=lambda **kw:[]))
        monkeypatch.setenv('PUBLIC_URL','https://studio.example.com');make_due(monkeypatch,store.item(article))
        if when=='after_seal':change()
        else:
            check=publisher.check
            def changed_check(item):check(item);change()
            monkeypatch.setattr(publisher,'check',changed_check)
        with pytest.raises(Conflict):publisher.deliver(article)
    assert store.public_articles()==[]


def test_unchecked_reapproval_revokes_and_reopt_in_reuses_article(store,monkeypatch):
    parent,article=opt_in(store)
    Companion(store,writer(store,monkeypatch,parent)).run(article)
    p=store.item(parent);store.save_item(parent,1,{'facebook':'Correction'},p['scheduled_at'],'owner')
    store.approve_item(parent,2,'owner',True,False)
    assert store.item(article)['status']=='blocked'
    assert store.item(article)['approval_hash'] is None
    assert store.item(parent)['companion_article']['state']=='revoked'
    with pytest.raises(Conflict):Companion(store,None).run(article)
    store.save_item(parent,2,{'facebook':'Dernière correction'},p['scheduled_at'],'owner')
    store.approve_item(parent,3,'owner',True,True)
    assert store.item(parent)['companion_article']['article_id']==article
    assert store.item(article)['revision']==2
    Companion(store,writer(store,monkeypatch,parent)).run(article)
    assert store.item(article)['status']=='approved'


def test_changed_article_requires_manual_approval(store,monkeypatch):
    parent,article=opt_in(store);runner=Companion(store,writer(store,monkeypatch,parent));runner.run(article)
    a=store.item(article)
    store.save_item(article,1,{'markdown':a['content']['markdown']+'\nConseil corrigé.'},store.item(parent)['scheduled_at'],'owner')
    with pytest.raises(Conflict):runner.run(article)
    # Owner may independently approve the edited article even after parent edit.
    p=store.item(parent);store.save_item(parent,1,{'facebook':'Correction'},p['scheduled_at'],'owner')
    store.approve_item(article,2,'owner',True)
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com');make_due(monkeypatch,store.item(article))
    Publisher(store,SimpleNamespace(products=lambda **kw:[])).deliver(article)
    assert len(store.public_articles())==1


@pytest.mark.parametrize('stage',['review','rendering'])
def test_restart_resumes_without_rewriting_finished_text(store,monkeypatch,stage):
    parent,article=opt_in(store);generator=writer(store,monkeypatch,parent)
    generator.draft(article)
    with store.db() as db:db.execute('UPDATE items SET status=? WHERE id=?',(stage,article))
    monkeypatch.setattr(generator,'draft',lambda id:pytest.fail('Should not rewrite completed text'))
    Companion(store,generator).run(article)
    assert store.item(article)['status']=='approved'


def test_generation_failure_never_approves_or_projects(store,monkeypatch):
    parent,article=opt_in(store);generator=writer(store,monkeypatch,parent)
    def fail(prompt):raise GenerationError('Information à confirmer')
    monkeypatch.setattr(generator,'ask',fail)
    with pytest.raises(GenerationError):Companion(store,generator).run(article)
    assert store.item(article)['approval_hash'] is None and store.public_articles()==[]


def test_agent_can_follow_but_not_grant_automatic_approval(store,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com')
    parent,article=opt_in(store);agent=AgentService(store,lambda:[])
    assert agent.content(parent)['companion_article']['article_id']==article
    assert agent.content(article)['requires_owner_approval'] is False
    p=store.item(parent);store.save_item(parent,1,{'facebook':'Correction'},p['scheduled_at'],'owner')
    assert agent.content(article)['requires_owner_approval'] is True


def test_published_article_not_duplicated_on_parent_reapproval(store,monkeypatch):
    parent,article=opt_in(store);Companion(store,writer(store,monkeypatch,parent)).run(article)
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com');make_due(monkeypatch,store.item(article))
    Publisher(store,SimpleNamespace(products=lambda **kw:[])).deliver(article)
    p=store.item(parent);store.save_item(parent,1,{'facebook':'Correction'},p['scheduled_at'],'owner')
    store.approve_item(parent,2,'owner',True,True)
    assert store.item(parent)['companion_article']['article_id']==article
    assert store.item(article)['status']=='published'
    with store.db() as db:assert db.execute('SELECT count(*) FROM companion_articles').fetchone()[0]==1


def test_late_generation_publishes_when_ready_not_in_the_past(store,monkeypatch):
    import companion
    from datetime import datetime,timedelta
    parent,article=opt_in(store)
    ready=datetime.fromisoformat(store.item(parent)['scheduled_at'])+timedelta(hours=2)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return ready.astimezone(tz)
    monkeypatch.setattr(companion,'datetime',Clock)
    Companion(store,writer(store,monkeypatch,parent)).run(article)
    assert store.item(article)['scheduled_at']==ready.isoformat()


def test_owner_photo_and_product_snapshot_reused_in_same_conversation(store,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com')
    agent=AgentService(store,lambda:[])
    from store import uid
    from test_agent import future
    result=agent.prepare(uid(),'Mon nouveau micro','social',scheduled_at=future())
    parent=result['item_id'];product={'id':'external:test','external':True,'title':'Le modèle exact','price_mode':'custom','custom_price':199}
    with store.db() as db:
        demand=db.execute('SELECT * FROM demand_items WHERE item_id=?',(parent,)).fetchone()
        brief=json.loads(demand['brief']);brief['photo_ids']=['owner-photo']
        db.execute('UPDATE demand_items SET brief=? WHERE item_id=?',(dumps(brief),parent))
        db.execute("UPDATE items SET status='review',content=?,media=? WHERE id=?",(dumps(content()),dumps({'media':'ready.png','product_snapshot':product}),parent))
    store.approve_item(parent,1,'owner',True,True)
    article=store.item(parent)['companion_article']['article_id']
    with store.db() as db:
        child=db.execute('SELECT * FROM demand_items WHERE item_id=?',(article,)).fetchone()
        assert child['conversation_id']==demand['conversation_id']
        assert json.loads(child['brief'])['photo_ids']==['owner-photo']
        assert json.loads(child['product'])==product


def test_owner_http_approval_passes_opt_in_flag(store,monkeypatch):
    import importlib.util
    from pathlib import Path
    from fastapi.testclient import TestClient
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    monkeypatch.setenv('EDITORIAL_DATA',str(store.root));monkeypatch.setenv('EDITORIAL_WORKER','false')
    spec=importlib.util.spec_from_file_location('companion_test_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    parent=create_item(store)
    with TestClient(module.app) as client:
        assert client.post(f'/editorial/api/items/{parent}/approve',json={'revision':1,'media_reviewed':True,'create_blog':True}).status_code==401
        async def actor(request,mutate=False):return 'owner'
        monkeypatch.setattr(module,'actor',actor)
        response=client.post(f'/editorial/api/items/{parent}/approve',json={'revision':1,'media_reviewed':True,'create_blog':True})
        assert response.status_code==403
        response=client.post(f'/editorial/api/items/{parent}/approve',headers={'Origin':'https://postiz.example.com','X-Editorial-Action':'1'},json={'revision':1,'media_reviewed':True,'create_blog':True})
        assert response.status_code==200,response.text
        assert store.item(parent)['companion_article']['status']=='queued'
        assert store.public_articles()==[]

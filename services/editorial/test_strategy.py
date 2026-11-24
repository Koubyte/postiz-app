"""Recurring research and campaigns do not alter weekly plans or grant approval."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).parent))
from store import Store, Conflict, uid, dumps, PARIS
from generation import GenerationError
from agent import AgentService
from strategy import Strategy

@pytest.fixture
def strategy(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    store=Store(tmp_path)
    agent=AgentService(store,lambda:[])
    generator=SimpleNamespace(ask=lambda _: {'title':'Découvrir la musique','summary':'Du choix à la pratique','steps':[{'title':title,'brief':'Un conseil utile '+title,'product_query':''} for title in ['Découverte','Pratique','Aller plus loin']],'blog_angle':'Un guide pratique complet'})
    service=Strategy(store,generator,None,agent)
    agent.strategy=service
    return service


def dates():
    start=datetime.now(PARIS).date()+timedelta(days=2)
    return start.isoformat(),(start+timedelta(days=6)).isoformat()


def new_campaign(service,**kw):
    start,end=dates()
    return service.create_campaign(uid(),'Accompagner les nouveaux musiciens',start,end,**kw)['id']


def test_cadence_catches_latest_slot_once_across_restart_and_dst(strategy):
    current=datetime(2030,10,28,9,tzinfo=PARIS)
    strategy.tick(current);strategy.tick(current+timedelta(minutes=1))
    Strategy(strategy.store,strategy.generator,None,strategy.agent).tick(current+timedelta(minutes=2))
    with strategy.store.db() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM weeks').fetchone()[0]==0
        db.execute("UPDATE strategy_runs SET status='ready'")
        db.execute("UPDATE jobs SET status='done'")
    strategy.tick(current+timedelta(days=3))
    with strategy.store.db() as db:
        assert db.execute('SELECT count(*) FROM strategy_runs').fetchone()[0]==3


def test_active_manual_research_deduplicates_and_preserves_last_report(strategy):
    first=strategy.queue('performance',uid())
    assert strategy.queue('performance',uid())['id']==first['id']
    with strategy.store.db() as db:
        db.execute("UPDATE strategy_runs SET status='ready',result=?",(dumps({'summary':'Bilan existant','generated_at':'2030-01-01'}),))
        db.execute("UPDATE jobs SET status='done'")
    second=strategy.queue('performance',uid())
    state=strategy.context()['performance']
    assert state['id']==second['id'] and state['status']=='queued'
    assert state['summary']=='Bilan existant'


def test_research_persists_deduped_ideas_without_preparing_items(strategy,monkeypatch):
    import watch
    idea={'id':'stable-id','title':'Un conseil','angle':'Un angle sourcé','reason':'Utile','sources':[{'title':'Fabricant','url':'https://example.com/guide'}],'product_query':'','kind':'advice'}
    monkeypatch.setattr(watch,'generate_watch',lambda *_:{'summary':'Une idée','ideas':[idea],'generated_at':'2030-01-01'})
    for _ in range(2):
        job=strategy.queue('watch',uid());strategy.run('watch',job['id'])
    state=strategy.context()['watch']
    assert len(state['ideas'])==1 and state['status']=='ready'
    with strategy.store.db() as db:assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0
    nonce=uid()
    result=strategy.prepare_idea('stable-id',nonce,True)
    assert strategy.prepare_idea('stable-id',nonce,True)==result
    assert strategy.prepare_idea('stable-id',uid(),False)==result
    item=strategy.store.item(result['item_id'])
    assert item['status']=='queued' and item['approval_hash'] is None and item['blog_requested']
    assert not strategy.store.public_articles()


def test_campaign_plan_reserves_around_week_and_creates_unapproved_independent_drafts(strategy):
    store=strategy.store
    start,end=dates()
    weekly_date=datetime.fromisoformat(start).replace(hour=12,tzinfo=PARIS).astimezone(timezone.utc).isoformat()
    with store.db() as db:
        db.execute("INSERT INTO weeks(id,week,status,created,plan) VALUES('existing',?,'plan_review',?,?)",(start,start,dumps({'subjects':[{'scheduled_at':weekly_date}]})))
        before=dict(db.execute('SELECT * FROM weeks').fetchone())
    identifier=new_campaign(strategy)
    strategy.plan_campaign(identifier)
    campaign=strategy.campaign(identifier)
    assert campaign['status']=='plan_review'
    due=datetime.fromisoformat(campaign['plan']['steps'][0]['scheduled_at'])
    assert due-datetime.fromisoformat(weekly_date)==timedelta(hours=2)
    with store.db() as db:assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0
    nonce=uid();result=strategy.prepare_campaign(identifier,1,nonce)
    assert strategy.prepare_campaign(identifier,1,nonce)==result
    strategy.draft_campaign(identifier);strategy.draft_campaign(identifier)
    campaign=strategy.campaign(identifier)
    assert len(campaign['items'])==3 and campaign['status']=='ready'
    with store.db() as db:
        assert dict(db.execute('SELECT * FROM weeks').fetchone())==before
        assert db.execute('SELECT count(*) FROM items WHERE approval_hash IS NOT NULL').fetchone()[0]==0
        assert db.execute('SELECT sum(blog_requested) FROM items').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==0
    assert not store.public_articles()


def test_campaign_resume_after_receipt_gap_never_duplicates(strategy,monkeypatch):
    identifier=new_campaign(strategy);strategy.plan_campaign(identifier)
    step=strategy.campaign(identifier)['plan']['steps'][0]
    original=strategy.agent.prepare
    calls=0
    def interrupted(*args,**kwargs):
        nonlocal calls
        result=original(*args,**kwargs);calls+=1
        if calls==1:raise RuntimeError('simulated receipt gap')
        return result
    monkeypatch.setattr(strategy.agent,'prepare',interrupted)
    with pytest.raises(RuntimeError):strategy.draft_campaign(identifier)
    strategy.draft_campaign(identifier)
    with strategy.store.db() as db:
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==3
        assert db.execute('SELECT count(*) FROM campaign_items').fetchone()[0]==3


def test_malformed_campaign_does_not_change_existing_items(strategy):
    identifier=new_campaign(strategy)
    strategy.generator.ask=lambda _:{'steps':[{}]}
    with pytest.raises(GenerationError):strategy.plan_campaign(identifier)
    with strategy.store.db() as db:assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0


def test_pause_and_request_payload_conflicts(strategy):
    nonce=uid();strategy.queue('watch',nonce)
    with pytest.raises(Conflict,match='autres paramètres'):strategy.queue('performance',nonce)
    with strategy.store.db() as db:db.execute("UPDATE settings SET value='true' WHERE key='paused'")
    with pytest.raises(Conflict,match='suspendu'):strategy.queue('watch',uid())
    with pytest.raises(Conflict,match='suspendu'):new_campaign(strategy)
    assert strategy.queue('watch',nonce)['status']=='queued'


def test_campaign_boundary_validation(strategy):
    start,end=dates()
    for count in [True,2,8]:
        with pytest.raises(Conflict):strategy.create_campaign(uid(),'Projet',start,end,count)
    with pytest.raises(Conflict):strategy.create_campaign(uid(),'Projet',end,start)
    with pytest.raises(Conflict):strategy.create_campaign(uid(),'Projet','2000-01-01',end)
    identifier=new_campaign(strategy)
    with pytest.raises(Conflict):strategy.prepare_campaign(identifier,1,uid())
    strategy.plan_campaign(identifier)
    with pytest.raises(Conflict):strategy.prepare_campaign(identifier,2,uid())


def test_interrupted_jobs_recover_without_approval(strategy):
    run=strategy.queue('watch',uid())
    with strategy.store.db() as db:
        db.execute("UPDATE strategy_runs SET status='running'")
        db.execute("UPDATE jobs SET status='running',attempts=2")
    strategy.store.recover();strategy.recover()
    assert strategy.context()['watch']['status']=='failed'
    with strategy.store.db() as db:assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0


def test_strategy_http_owner_and_csrf_boundaries(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('EDITORIAL_DATA',str(tmp_path));monkeypatch.setenv('EDITORIAL_WORKER','false')
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    spec=importlib.util.spec_from_file_location('strategy_http_test',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with TestClient(module.app,base_url='https://postiz.example.com') as client:
        assert client.get('/editorial/api/strategy').status_code==401
        assert client.post('/editorial/api/strategy/watch',json={'request_id':uid()}).status_code==401
        async def owner(_):return 'owner'
        monkeypatch.setattr(module,'actor',owner)
        assert client.get('/editorial/api/strategy').json()['watch'] is None
        assert client.post('/editorial/api/strategy/watch',json={'request_id':uid()}).status_code==403
        headers={'Origin':'https://postiz.example.com','X-Editorial-Action':'1'}
        assert client.post('/editorial/api/strategy/watch',json={'request_id':uid()},headers=headers).status_code==200
        assert client.get('/editorial/api/strategy').json()['watch']['status']=='queued'


def test_campaign_retry_requeues_failed_stage_and_keeps_drafts(strategy):
    identifier=new_campaign(strategy)
    with strategy.store.db() as db:
        db.execute("UPDATE campaigns SET status='failed',error='Interrompu' WHERE id=?",(identifier,))
        db.execute("UPDATE jobs SET status='failed',attempts=2 WHERE target=?",(identifier,))
    request_id=uid()
    retry=strategy.retry_campaign(identifier,1,request_id)
    assert retry['status']=='queued'
    assert strategy.retry_campaign(identifier,1,request_id)==retry
    strategy.plan_campaign(identifier)
    strategy.prepare_campaign(identifier,1,uid())
    strategy.draft_campaign(identifier)
    with strategy.store.db() as db:
        before=[dict(r) for r in db.execute('SELECT * FROM items')]
        db.execute("UPDATE campaigns SET status='failed' WHERE id=?",(identifier,))
        db.execute("UPDATE jobs SET status='failed',attempts=2 WHERE target=? AND kind='campaign_draft'",(identifier,))
    assert strategy.retry_campaign(identifier,1,uid())['status']=='preparing'
    strategy.draft_campaign(identifier)
    with strategy.store.db() as db:assert [dict(r) for r in db.execute('SELECT * FROM items')]==before

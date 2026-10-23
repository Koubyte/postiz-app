"""Blog minimum stays 500 words; long articles are not rejected or truncated."""
import pytest
from test_workflow import content,store,create_item
from generation import validate_content,GenerationError,Generator
from agent import AgentService
from store import dumps,uid


def test_long_article_preserved_and_minimum_stays_500_words():
    article=content('blog');article['markdown']='Conseil documenté pour la pratique musicale. '*5000
    assert len(article['markdown'])>100_000
    assert validate_content(article,'blog')['markdown']==article['markdown'].strip()
    article['markdown']='mot '*499
    with pytest.raises(GenerationError,match='500 mots'):validate_content(article,'blog')
    article['markdown']='mot '*500
    assert validate_content(article,'blog')['markdown']==article['markdown'].strip()


def test_long_blog_brief_and_revision_remain_complete(store,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://studio.example.com')
    agent=AgentService(store,lambda:[])
    brief='Développer les conseils de réglage et de pratique. '*250
    result=agent.prepare(uid(),brief,'blog');id=result['item_id']
    assert agent.content(id)['brief']['instruction']==brief.strip()
    with store.db() as db:db.execute("UPDATE items SET status='review' WHERE id=?",(id,))
    agent.revise(uid(),id,1,brief)
    assert store.item(id)['content']['_feedback']==brief.strip()
    with pytest.raises(GenerationError):agent.prepare(uid(),brief,'social')


def test_long_previous_blog_and_feedback_reach_rewriter(store,monkeypatch):
    id=create_item(store,'blog');article=content('blog')
    article['markdown']='Conseils utiles pour progresser. '*1200+' FIN_ARTICLE_UNIQUE'
    article['_feedback']='Précision utile. '*300+' FIN_CONSIGNE_UNIQUE'
    with store.db() as db:
        db.execute("UPDATE items SET content=?,status='queued' WHERE id=?",(dumps(article),id))
        db.execute('INSERT INTO conversations VALUES(?,?,?)',('c','test','now'))
        db.execute('INSERT INTO demand_items VALUES(?,?,?,0,?,NULL)',(id,'c','m',dumps({'title':'Guide','angle':'Pratique','format':'blog'})))
    prompts=[]
    def ask(prompt):prompts.append(prompt);return content('blog')
    gen=Generator(store);monkeypatch.setattr(gen,'ask',ask);monkeypatch.setattr(gen,'render',lambda id:None)
    gen.draft(id)
    assert 'FIN_ARTICLE_UNIQUE' in prompts[0] and 'FIN_CONSIGNE_UNIQUE' in prompts[0]
    assert 'Au moins 500 mots, sans maximum' in prompts[0]
    assert '700 à 1100' not in prompts[0]

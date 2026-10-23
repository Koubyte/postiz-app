"""Editorial advice must not discard drafts or truncate article bodies."""
import pytest
from test_workflow import content,store,create_item
from generation import validate_content,GenerationError,Generator
from agent import AgentService
from store import dumps,uid


def test_long_article_preserved_and_500_word_target_does_not_discard_drafts():
    article=content('blog');article['markdown']='Conseil documenté pour la pratique musicale. '*5000
    assert len(article['markdown'])>100_000
    assert validate_content(article,'blog')['markdown']==article['markdown'].strip()
    article['markdown']='mot '*499
    assert any('500 mots' in note for note in validate_content(article,'blog')['editorial_notes'])
    article['markdown']='mot '*500
    assert validate_content(article,'blog')['markdown']==article['markdown'].strip()
    assert not validate_content(article,'blog')['editorial_notes']


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


def test_metadata_is_repaired_without_losing_article():
    article=content('blog')
    article.update(title='Un titre complet '*40,headline=None,alt=None,excerpt=None,
                   slug='Éclairage & Son : le guide !',category='conseils',sources=[],uncertainty=None)
    result=validate_content(article,'blog')
    assert result['markdown']==article['markdown'].strip()
    assert 0<len(result['title'])<=220 and 0<len(result['headline'])<=90
    assert 0<len(result['excerpt'])<=1000 and 0<len(result['alt'])<=300
    assert result['slug']=='eclairage-son-le-guide' and result['category']=='guides'
    assert any('Aucune source' in note for note in result['editorial_notes'])


def test_unavailable_sources_continue_to_visual_preparation_without_approval(store,monkeypatch):
    id=create_item(store,'blog',status='queued');item=store.item(id)
    with store.db() as db:
        db.execute('UPDATE weeks SET plan=? WHERE id=?',(dumps({'article':{'title':'Actualités','angle':'Musique'},'products':[]}),item['week_id']))
    article=content('blog');article.update(sources=[],uncertainty='Certaines pages sources sont inaccessibles ; les passages correspondants ont été omis.')
    generator=Generator(store);rendered=[]
    monkeypatch.setattr(generator,'ask',lambda _:article)
    monkeypatch.setattr(generator,'render',rendered.append)
    generator.draft(id)
    saved=store.item(id)
    assert rendered==[id] and saved['status']=='rendering'
    assert saved['content']['markdown']==article['markdown'].strip()
    assert article['uncertainty'] in saved['content']['editorial_notes']
    assert not saved['approval_hash'] and not store.public_articles()


@pytest.mark.parametrize('body',['', '<script>alert(1)</script>', '[lien](javascript:alert)'])
def test_invalid_or_unsafe_body_still_rejected(body):
    article=content('blog');article['markdown']=body
    with pytest.raises(GenerationError):validate_content(article,'blog')


def test_owner_edits_save_normalized_metadata_and_private_notes(store,monkeypatch):
    import importlib.util
    from pathlib import Path
    monkeypatch.setenv('EDITORIAL_DATA',str(store.root))
    monkeypatch.setenv('EDITORIAL_WORKER','false')
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    spec=importlib.util.spec_from_file_location('editorial_notes_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    id=create_item(store,'blog');item=store.item(id)
    edited=module.editable_content({'title':'Titre '*100,'slug':'Mon Article Édité','sources':[]},item)
    store.save_item(id,1,edited,item['scheduled_at'],'owner')
    saved=store.item(id)
    assert len(saved['content']['title'])<=220 and saved['content']['slug']=='mon-article-edite'
    assert any('Aucune source' in note for note in saved['content']['editorial_notes'])
    assert not saved['approval_hash'] and not store.public_articles()

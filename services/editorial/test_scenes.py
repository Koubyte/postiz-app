"""Product-aware direction, diversity memory and stable image retries."""
import json
import pytest
from scenes import choose,select,checked_options,VERSION
from store import Conflict,Store,dumps
from test_workflow import store,create_item


def directions():
    return {'directions':[
        {'setting':'home','lighting':'daylight','angle':'three_quarter','scene':'Piano dans une pièce de vie claire, près d’une fenêtre, vu de trois quarts avec tout le clavier visible.','product_fit':'Un piano destiné à la pratique à domicile dans une pièce de vie.'},
        {'setting':'teaching','lighting':'soft_neutral','angle':'side_context','scene':'Piano dans une salle de cours claire, pupitre discret, vue latérale avec instrument entier.','product_fit':'Un piano placé pour un cours individuel dans une salle de musique.'},
        {'setting':'stage','lighting':'contrasted','angle':'front_context','scene':'Piano sur une petite scène intérieure pendant la balance, lumière contrastée et vue frontale.','product_fit':'Un piano installé sur une scène adaptée pour une répétition sans public.'},
    ]}


def test_recent_locations_are_avoided_before_reusing_underused_one():
    options=checked_options(directions())
    history=[options[0],options[2],options[1],options[1],options[1]]
    assert select(options,history)['setting']=='teaching'


def test_fixed_place_can_still_vary_light_and_angle():
    options=checked_options(directions())
    for o in options:o['setting']='home'
    assert select(options,[options[0]])['lighting']!='daylight'


@pytest.mark.parametrize('mutate',[
    lambda v:v['directions'].pop(),
    lambda v:v['directions'][0].update(setting='random-place'),
    lambda v:v['directions'][0].update(product_fit=''),
    lambda v:v['directions'].__setitem__(1,v['directions'][0]),
])
def test_incomplete_or_identical_options_block_rendering(mutate):
    value=directions();mutate(value)
    with pytest.raises(Conflict):checked_options(value)


def test_retry_reuses_direction_and_revision_changes_pick_a_different_scene(store):
    id=create_item(store);item=store.item(id);calls=[]
    def ask(prompt):calls.append(prompt);return directions()
    chosen=choose(store,ask,item,{'angle':'Pratique du piano'},{'title':'Pianova HD300'})
    assert chosen['version']==VERSION and chosen['setting']=='home'
    assert 'Pianova HD300' in calls[0] and 'compatibilité' in calls[0]
    restarted=Store(store.root)
    assert choose(restarted,ask,item,{},None)==chosen and len(calls)==1
    store.save_item(id,1,{'facebook':'Autre angle'},item['scheduled_at'],'owner')
    next_scene=choose(store,ask,store.item(id),{},None)
    assert next_scene['setting']=='teaching'
    assert 'Piano dans une pièce de vie claire' in calls[1]
    assert store.item(id)['content']['facebook']=='Autre angle'
    assert store.item(id)['media']==item['media']


def test_history_is_shared_across_blog_and_social_without_editing_them(store):
    social=create_item(store);blog=create_item(store,'blog')
    before=store.item(social)
    first=choose(store,lambda _:directions(),before,{},None)
    second=choose(store,lambda _:directions(),store.item(blog),{},None)
    assert first['setting']!=second['setting']
    assert store.item(social)==before


def test_edit_during_direction_selection_is_rejected(store):
    id=create_item(store);item=store.item(id)
    def ask(prompt):
        store.save_item(id,1,{'facebook':'Modifié pendant la recherche'},item['scheduled_at'],'owner')
        return directions()
    with pytest.raises(Conflict):choose(store,ask,item,{},None)
    with store.db() as db:assert db.execute('SELECT count(*) FROM visual_directions').fetchone()[0]==0

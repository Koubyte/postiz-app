"""Agent-authored drafts keep their catalogue checks and companion product identity."""
import base64
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from agent import AgentService
from catalogue_binding import bind_catalogue_product
from companion import Companion
from generation import Generator
from publisher import Publisher
from store import Conflict, Store, uid


def draft(service, kind='social', query='ZEFIR 12A'):
    fields={'title':'Elokance ZEFIR 12A','headline':'Ta sono prête','alt':'Enceinte'}
    if kind=='social':fields.update(facebook='Enceinte à 499 €',instagram='Prête pour la fête ? Enceinte à 499 €')
    else:fields.update(markdown='Texte article',excerpt='Enceinte',slug='zefir-12a',category='produits')
    due=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    return service.create_direct(uid(),kind,fields,product_query=query,scheduled_at=due)['item_id']


def visual(service,item):
    buf=io.BytesIO();Image.new('RGB',(256,256),'orange').save(buf,'PNG')
    service.import_final_visual(uid(),item,1,base64.b64encode(buf.getvalue()).decode())


def product(price=499):
    return {'id':'zefir','title':'ZEFIR 12A','ean':'','url':'https://example.com/zefir',
            'price':price,'price_from':False,'available':False,'stock_status':'supplier',
            'thumbnail':'https://example.com/zefir.png','external':False}


def test_direct_draft_catalogue_binding_preserves_content_and_guards_later_price(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    store=Store(tmp_path);gen=Generator(store);publisher=Publisher(store,gen)
    service=AgentService(store,lambda:[],publisher); item=draft(service,'blog');visual(service,item)
    original=store.item(item);current=[product()]
    before=service.content(item)
    assert before['catalogue_revalidation']=='unavailable_until_product_snapshot'
    assert 'non revérifiés automatiquement' in before['catalogue_warning']
    monkeypatch.setattr(gen,'products',lambda force=False:current)
    token=uid();result=bind_catalogue_product(service,token,item,2,'ZEFIR 12A')
    assert result['product']['price']==499 and result['revision']==3
    assert bind_catalogue_product(service,token,item,2,'ZEFIR 12A')==result
    bound=store.item(item)
    assert bound['content']==original['content'] and bound['media']['media']==original['media']['media']
    assert bound['media']['hashes']==original['media']['hashes']
    assert bound['media']['product_snapshot']['price_mode']=='catalogue'
    after=service.content(item)
    assert after['catalogue_revalidation']=='available' and after['catalogue_warning'] is None
    store.approve_item(item,3,'owner',True)
    publisher.check(store.item(item))
    current[:]=[product(599)]
    with pytest.raises(Conflict,match='prix a changé'):publisher.check(store.item(item))


def test_unresolved_direct_companion_keeps_product_and_resolves_before_drafting(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://postiz.example.com')
    store=Store(tmp_path);gen=Generator(store);service=AgentService(store,lambda:[])
    parent=draft(service);visual(service,parent)
    store.approve_item(parent,2,'owner',True,create_blog=True)
    article=store.item(parent)['companion_article']['article_id']
    monkeypatch.setattr(gen,'products',lambda force=False:[product()])
    def draft_and_assert(identifier):
        _,brief,resolved=gen.context(store.item(identifier))
        assert brief['kind']=='product' and brief['query']=='ZEFIR 12A'
        assert resolved['id']=='zefir'
        raise RuntimeError('observed product before drafting')
    monkeypatch.setattr(gen,'draft',draft_and_assert)
    with pytest.raises(RuntimeError,match='observed product'):Companion(store,gen).run(article)

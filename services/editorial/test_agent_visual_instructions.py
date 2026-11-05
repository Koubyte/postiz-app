"""The agent's visual direction is an explicit, replay-safe part of the brief."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from agent import AgentService, build_mcp
from generation import GenerationError
from store import Conflict, Store, uid


def test_visual_instructions_are_stored_verbatim_and_protected_on_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    service = AgentService(Store(tmp_path), lambda: [])
    date = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    request_id = uid()
    direction = 'Petite scène de bar, enceinte entière de trois quarts.\nLumière ambre, aucune fumée.'
    args = dict(request_id=request_id, brief='Présente cette enceinte', kind='social',
                product_query='ZEFIR 12A', scheduled_at=date, visual_instructions=direction)
    first = service.prepare(**args)
    assert service.prepare(**args) == first
    with service.store.db() as db:
        brief = json.loads(db.execute('SELECT brief FROM demand_items WHERE item_id=?',
                                      (first['item_id'],)).fetchone()[0])
    assert brief['visual_instructions'] == direction
    with pytest.raises(Conflict, match='autre demande'):
        service.prepare(**{**args, 'visual_instructions': 'Une salle de répétition'})
    with pytest.raises(GenerationError):
        service.prepare(**{**args, 'request_id': uid(), 'visual_instructions': 'x' * 6001})


def test_prepare_content_schema_exposes_visual_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    tool = build_mcp(AgentService(Store(tmp_path), lambda: []))._tool_manager.get_tool('prepare_content')
    assert {'visual_instructions', 'price_mode', 'reference_owner_supplied'} <= set(tool.parameters['properties'])


def test_catalogue_price_and_owner_reference_are_explicit_and_replay_safe(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    service = AgentService(Store(tmp_path), lambda: [])
    args = dict(request_id=uid(), brief='Présente ce produit', kind='social', product_query='ZEFIR 12A',
                price_mode='catalogue', reference_image_url='https://example.com/owner.png',
                reference_source_url='https://example.com/owner', reference_owner_supplied=True)
    result = service.prepare(**args)
    with service.store.db() as db:
        brief = json.loads(db.execute('SELECT brief FROM demand_items WHERE item_id=?',
                                      (result['item_id'],)).fetchone()[0])
    assert brief['price_mode'] == 'catalogue' and brief['reference_owner_supplied'] is True
    with pytest.raises(Conflict, match='autre demande'):
        service.prepare(**{**args, 'reference_owner_supplied': False})
    with pytest.raises(Conflict):
        service.prepare(**{**args, 'request_id': uid(), 'price': 499})
    with pytest.raises(Conflict):
        service.prepare(uid(), 'Un conseil', 'social', reference_owner_supplied=True)

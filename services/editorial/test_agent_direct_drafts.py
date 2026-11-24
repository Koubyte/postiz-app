"""Directly authored drafts remain private, editable, and require an image and approval."""
import base64
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from agent import AgentService, build_mcp
from store import Conflict, Store, uid


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    return AgentService(Store(tmp_path), lambda: [])


def test_social_direct_draft_replay_image_and_approval_gate(service):
    fields = {'title': 'Enceinte', 'headline': 'Pour ta sono', 'facebook': 'Texte Facebook',
              'instagram': 'Texte Instagram', 'alt': 'Une enceinte', 'sources': []}
    nonce = uid()
    args = dict(request_id=nonce, kind='social', fields=fields, product_query='Elokance ZEFIR 12A',
                scheduled_at=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())
    result = service.create_direct(**args)
    assert result == service.create_direct(**args)
    assert result['catalogue_revalidation'] == 'unavailable_until_product_snapshot'
    item = service.store.item(result['item_id'])
    assert item['content']['facebook'] == fields['facebook'] and item['content']['instagram'] == fields['instagram']
    assert item['status'] == 'review' and not item['media'] and not item['approval_hash']
    with service.store.db() as db:
        assert not db.execute('SELECT 1 FROM jobs WHERE target=?', (item['id'],)).fetchone()
        assert not db.execute('SELECT 1 FROM deliveries WHERE item_id=?', (item['id'],)).fetchone()
    with pytest.raises(Conflict):
        service.store.approve_item(item['id'], item['revision'], 'owner', True)
    data = io.BytesIO()
    Image.new('RGB', (100, 100), 'blue').save(data, 'PNG')
    updated = service.import_final_visual(uid(), item['id'], item['revision'], base64.b64encode(data.getvalue()).decode())
    assert updated['revision'] == 2 and updated['requires_owner_approval']
    item = service.store.item(item['id'])
    assert item['media']['media'] and item['status'] == 'review' and not item['approval_hash']
    with pytest.raises(Conflict):
        service.create_direct(**{**args, 'fields': {**fields, 'facebook': 'Autre'}})


def test_direct_blog_preserves_text_and_prevents_duplicate_slug(service):
    text = 'Un guide avec ses propres mots.\n\n## Étapes\n\nConseil concret.'
    fields = {'title': 'Guide de piano', 'headline': 'Choisir son piano', 'markdown': text,
              'excerpt': 'Un guide', 'slug': 'guide-piano', 'category': 'guides', 'alt': 'Un piano'}
    result = service.create_direct(uid(), 'blog', fields)
    assert service.store.item(result['item_id'])['content']['markdown'] == text
    with pytest.raises(Conflict, match='slug'):
        service.create_direct(uid(), 'blog', fields)
    assert service.store.public_articles() == []
    tool = build_mcp(service)._tool_manager.get_tool('create_direct_draft')
    assert {'fields', 'kind'} <= set(tool.parameters['properties'])

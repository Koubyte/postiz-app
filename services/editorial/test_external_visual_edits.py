"""Editing an externally provided final visual must never silently replace it."""
import base64
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from agent import AgentService
from store import EXTERNAL_VISUAL_WARNING, Store, uid


def png(color):
    output = io.BytesIO()
    Image.new('RGB', (100, 100), color).save(output, 'PNG')
    return base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize('path', ['agent', 'store'])
def test_title_edit_preserves_agent_visual_and_revokes_approval(tmp_path, monkeypatch, path):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    service = AgentService(Store(tmp_path), lambda: [])
    fields = {'title': 'Enceinte', 'headline': 'Ta sono', 'facebook': 'Texte',
              'instagram': 'Ta sono prête pour samedi', 'alt': 'Enceinte'}
    date = (datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    draft = service.create_direct(uid(), 'social', fields, scheduled_at=date)
    imported = service.import_final_visual(uid(), draft['item_id'], 1, png('blue'))
    identifier = draft['item_id']
    service.store.approve_item(identifier, imported['revision'], 'owner', True)
    before = service.store.item(identifier)
    assert before['approval_hash']
    if path == 'agent':
        result = service.edit(uid(), identifier, before['revision'], {'headline': 'Nouvelle accroche'})
        assert result['visual_warning'] == EXTERNAL_VISUAL_WARNING
    else:
        service.store.save_item(identifier, before['revision'], {'headline': 'Nouvelle accroche'}, date, 'owner')
    after = service.store.item(identifier)
    assert after['media'] == before['media']
    assert after['status'] == 'review' and after['approval_hash'] is None
    assert after['approved_at'] is None and after['approved_by'] is None
    assert EXTERNAL_VISUAL_WARNING in after['content']['editorial_notes']
    with service.store.db() as db:
        assert not db.execute("SELECT 1 FROM jobs WHERE target=? AND status IN ('queued','running')", (identifier,)).fetchone()
    # The warning remains after unrelated text edits and after resubmitting the
    # exact same image; replacing the image clears it for the new review.
    service.edit(uid(), identifier, after['revision'], {'facebook': 'Texte corrigé'})
    after_text = service.store.item(identifier)
    assert EXTERNAL_VISUAL_WARNING in after_text['content']['editorial_notes']
    same = service.import_final_visual(uid(), identifier, after_text['revision'], png('blue'))
    assert EXTERNAL_VISUAL_WARNING in service.store.item(identifier)['content']['editorial_notes']
    service.import_final_visual(uid(), identifier, same['revision'], png('red'))
    assert EXTERNAL_VISUAL_WARNING not in service.store.item(identifier)['content']['editorial_notes']

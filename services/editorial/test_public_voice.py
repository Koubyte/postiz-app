"""The actual authoring requests carry Planète Laser's public-facing voice."""
import json

import pytest

from generation import Generator
from store import dumps
from test_workflow import content, create_item, store


def test_codex_system_prompt_requests_tutoiement_and_rock_tone(store, monkeypatch):
    generator = Generator(store)
    captured = []
    def bridge(path, body):
        captured.append(body)
        return {'choices': [{'message': {'content': '{}'}}]}
    monkeypatch.setattr(generator, 'bridge', bridge)
    assert generator.ask('Prépare une publication.') == {}
    system = captured[0]['messages'][0]['content']
    assert 'tutoie le lecteur individuellement' in system
    assert 'chaleureux, rock et professionnel' in system
    assert 'argot forcé' in system
    assert 'une consigne explicite du propriétaire' in system.lower()
    assert 'français, vouvoiement' not in system


@pytest.mark.parametrize('kind', ['social', 'blog'])
def test_social_and_blog_drafting_both_receive_public_voice(store, monkeypatch, kind):
    identifier = create_item(store, kind, status='queued')
    item = store.item(identifier)
    brief = {'title': 'Un sujet musical', 'angle': 'Conseil utile'}
    plan = {'products': [], 'article': brief, 'subjects': [brief]}
    with store.db() as db:
        db.execute('UPDATE weeks SET plan=? WHERE id=?', (dumps(plan), item['week_id']))
    captured = []
    generator = Generator(store)
    def ask(prompt):
        captured.append(prompt)
        return content(kind)
    monkeypatch.setattr(generator, 'ask', ask)
    monkeypatch.setattr(generator, 'render', lambda _: None)
    generator.draft(identifier)
    assert 'tutoie le lecteur individuellement' in captured[0]
    assert 'chaleureux, rock et professionnel' in captured[0]
    # The prompt is the control; existing or agent-supplied copy is never rewritten mechanically.
    saved = store.item(identifier)['content']
    field = 'facebook' if kind == 'social' else 'markdown'
    assert saved[field] == content(kind)[field].strip()

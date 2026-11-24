"""The agent's public-content brief carries the store's current voice."""
from agent import AgentService
from conversation import Conversation
from store import Store, uid


def test_agent_context_advertises_the_public_voice(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    instructions = AgentService(Store(tmp_path), lambda: []).context()['instructions']
    assert 'tutoie le lecteur par défaut' in instructions
    assert 'articles de blog' in instructions
    assert 'chaleureuse' in instructions and 'rock' in instructions
    assert 'professionnalisme' in instructions and 'familiarité forcée' in instructions
    assert 'explicitement' in instructions


def test_chat_brief_includes_public_content_voice(tmp_path):
    class Generator:
        prompt = None
        def ask(self, prompt):
            self.prompt = prompt
            return {'reply': 'Le brief est prêt.', 'proposals': []}

    generator = Generator()
    conversation = Conversation(Store(tmp_path), generator)
    cid = conversation.create()
    mid = conversation.send(cid, {'id': uid(), 'text': 'Un article sur les enceintes'}, 'owner')
    conversation.answer(mid)
    assert 'tutoiement' in generator.prompt
    assert 'chaleureuse, rock et professionnelle' in generator.prompt
    assert 'explicitement donnée' in generator.prompt

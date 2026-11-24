"""Grok's captions pass the same editorial quality gate as the studio writer."""
from datetime import datetime, timedelta, timezone

import pytest

from agent import AgentService
from generation import Generator, social_quality, opener_pattern
from store import Conflict, Store, uid

SPEC_SHEET = ('🎹 Le Casio PX-S1100 Blanc t’attend chez Planète Laser.\n\n'
              '88 touches Smart Scaled Hammer Action, polyphonie 192 notes, 18 sonorités, haut-parleurs 8 W + 8 W. '
              'Format 1 322 × 232 × 102 mm, 11,2 kg. Livré avec pédale SP-3 et dongle WU-BT10.\n\n'
              'Envie de l’essayer ? Passe nous voir chez Planète Laser, à Forbach.\n\n'
              'Fiche produit : https://planetelaser.fr/instruments/pianos-claviers/casio-px-s1100-blanc\n\n'
              '#Casio #Privia #PXS1100 #PianoNumerique #PlaneteLaser #Forbach')
INSTAGRAM = ('Jouer du vrai piano dans 23 cm de profondeur ?\n\n'
             'Le Casio PX-S1100 tient sur un bureau, mais sous les doigts c’est un 88 touches lesté : '
             'la sensation d’un piano, sans la place d’un piano.\n\n'
             'Au casque le soir, ou relié à l’appli en Bluetooth pour suivre tes partitions et progresser à ton rythme.\n\n'
             'On l’a en blanc au magasin à Forbach : viens poser tes mains dessus.\n\n'
             '#pianonumerique #casio #apprendrelepiano #forbach')
FACEBOOK = ('Tu cherches un piano numérique qui ne mange pas tout le salon ?\n\n'
            'Le Casio PX-S1100 est l’un des 88 touches les plus fins : posé sur un meuble, il se fait oublier. '
            'Sous les doigts, c’est une autre histoire : touches lestées, toucher progressif, de quoi travailler '
            'tes nuances comme sur un piano acoustique.\n\n'
            'Au quotidien, le Bluetooth audio te laisse jouer par-dessus tes morceaux préférés, et le casque garde '
            'les voisins de bonne humeur.\n\n'
            'On l’a en blanc au magasin, à Forbach. Viens l’essayer avec ton morceau du moment : on te conseille '
            'aussi sur le stand et la pédale selon ton usage.')


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://postiz.example.com')
    return AgentService(Store(tmp_path), lambda: [])


def draft(service, facebook, instagram, title='Casio PX-S1100 Blanc'):
    return service.create_direct(request_id=uid(), kind='social',
                                 fields={'title': title, 'headline': 'Un vrai piano, sans la place',
                                         'facebook': facebook, 'instagram': instagram, 'alt': title},
                                 scheduled_at=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())


def test_spec_sheet_and_identical_captions_are_refused_with_fixes(service):
    with pytest.raises(Conflict) as refused:
        draft(service, SPEC_SHEET, SPEC_SHEET)
    message = str(refused.value)
    assert 'identiques' in message and 'URL' in message and 'fiche technique' in message
    with service.store.db() as db:
        assert not db.execute('SELECT 1 FROM items').fetchone()


def test_good_captions_are_accepted_and_scored(service):
    result = draft(service, FACEBOOK, INSTAGRAM)
    assert result['quality'] == {'score': 100, 'blocking': [], 'warnings': []}
    content = service.content(result['item_id'])
    assert content['quality']['score'] == 100
    assert not [n for n in content['content']['editorial_notes'] if n.startswith('Qualité : ')]


def test_warnings_reach_the_owner_review_without_blocking(service):
    instagram = INSTAGRAM.replace('#pianonumerique #casio #apprendrelepiano #forbach', '#casio')
    result = draft(service, FACEBOOK, instagram)
    assert not result['quality']['blocking'] and result['quality']['score'] < 100
    notes = service.store.item(result['item_id'])['content']['editorial_notes']
    assert any(n.startswith('Qualité : Instagram : 1 hashtag') for n in notes)


def test_repeated_opening_formula_is_flagged(service):
    draft(service, FACEBOOK, INSTAGRAM)
    second = INSTAGRAM.replace('Casio PX-S1100', 'Yamaha P-145')
    quality = social_quality({'title': 'Yamaha P-145', 'instagram': second, 'facebook': FACEBOOK},
                             service.recent_openers())
    assert opener_pattern(second, 'Yamaha P-145') in service.recent_openers()
    assert any('Même formule' in w for w in quality['warnings'])


def test_edit_gate_applies_to_rewritten_captions_only(service):
    result = draft(service, FACEBOOK, INSTAGRAM)
    item_id = result['item_id']
    with service.store.db() as db:  # a legacy draft written before the gate, with its visual
        db.execute("UPDATE items SET content=json_set(content,'$.facebook',?,'$.instagram',?),media=? WHERE id=?",
                   (SPEC_SHEET, SPEC_SHEET, '{"media":"visual.png"}', item_id))
    later = (datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    moved = service.edit(uid(), item_id, 1, {'alt': 'Piano Casio blanc'}, scheduled_at=later)
    assert moved['status'] == 'review'
    assert moved['quality']['blocking']
    with pytest.raises(Conflict):
        service.edit(uid(), item_id, moved['revision'], {'instagram': SPEC_SHEET})
    fixed = service.edit(uid(), item_id, moved['revision'], {'facebook': FACEBOOK, 'instagram': INSTAGRAM})
    assert fixed['quality']['score'] == 100


def test_check_post_quality_is_a_dry_run(service):
    report = service.check_quality({'title': 'Casio PX-S1100 Blanc', 'facebook': SPEC_SHEET, 'instagram': SPEC_SHEET})
    assert not report['accepted'] and report['blocking'] and 'Guide de rédaction' in report['guide']
    with service.store.db() as db:
        assert not db.execute('SELECT 1 FROM items').fetchone()


def test_studio_writer_gets_one_correction_pass(tmp_path):
    generator = Generator.__new__(Generator)
    generator.store = Store(tmp_path)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {'title': 'Casio PX-S1100 Blanc', 'headline': 'Un vrai piano', 'facebook': FACEBOOK,
                'instagram': INSTAGRAM, 'alt': 'Piano', 'sources': [{'title': 'Casio', 'url': 'https://www.casio.com/'}]}
    generator.ask = ask
    bad = {'title': 'Casio PX-S1100 Blanc', 'headline': 'Piano', 'facebook': SPEC_SHEET, 'instagram': SPEC_SHEET,
           'alt': 'Piano', 'editorial_notes': []}
    polished = generator.polish_social(bad, 'Consigne')
    assert len(prompts) == 1 and 'identiques' in prompts[0]
    assert polished['instagram'] == INSTAGRAM and not [n for n in polished['editorial_notes'] if n.startswith('Qualité')]
    # A good draft costs no extra model call.
    assert generator.polish_social(polished, 'Consigne')['instagram'] == INSTAGRAM and len(prompts) == 1

"""Veille evidence, dates, failure behavior and bounded discovery; no network IO."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import watch
from generation import GenerationError
from net import PublicFetchError
from store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def proposal(url='https://maker.example/news/piano', kind='news', **changes):
    return {'title': 'Un nouveau piano pour travailler à domicile',
            'angle': 'Expliquer le mode de pratique silencieuse documenté par le fabricant.',
            'kind': kind, 'product_query': 'Piano X',
            'reason': 'Un sujet utile aux musiciens qui pratiquent en appartement.',
            'sources': [{'title': 'Page fabricant', 'url': url}], **changes}


def page(date=None, extra=''):
    meta = f'<meta property="article:published_time" content="{date}">' if date else ''
    return (f'<html><head><title>Piano X — Fabricant</title>{meta}</head><body><article>'
            '<h1>Piano X et pratique silencieuse</h1><p>Le fabricant documente une sortie casque '
            'et un réglage du volume pour pratiquer à domicile en respectant les voisins.</p>'
            f'{extra}</article></body></html>').encode()


def harness(monkeypatch, initial, final=None, pages=None):
    prompts, reads = [], []
    replies = [{'ideas': initial}, {'ideas': initial if final is None else final}]
    def ask(prompt):
        prompts.append(prompt)
        return replies[len(prompts)-1]
    def fetch(url, limit):
        reads.append((url, limit))
        value = (pages or {}).get(url, page(datetime.now(timezone.utc).date().isoformat()))
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(watch, 'public_bytes', fetch)
    return SimpleNamespace(ask=ask), prompts, reads


def test_verified_news_uses_page_title_and_date_not_model_claims(store, monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    suggestion = proposal()
    suggestion['sources'][0]['published_at'] = '2099-01-01'
    generator, prompts, reads = harness(monkeypatch, [suggestion])
    result = watch.generate_watch(store, generator)
    assert len(prompts) == 2 and len(reads) == 1
    assert 'VRAIE recherche Internet' in prompts[0] and 'EXTRAITS VÉRIFIÉS' in prompts[1]
    assert result['ideas'][0]['sources'] == [{'title': 'Piano X — Fabricant', 'url': suggestion['sources'][0]['url'], 'published_at': today}]
    assert result['ideas'][0]['id'].startswith('watch-')
    assert 'evidence' not in result['ideas'][0]['sources'][0]
    assert result['generated_at']
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM items').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


@pytest.mark.parametrize('date', [None, '2020-01-01', '2099-01-01', 'inconnue'])
def test_unverified_old_or_future_publication_is_never_news(store, monkeypatch, date):
    suggestion = proposal()
    generator, _, _ = harness(monkeypatch, [suggestion], pages={suggestion['sources'][0]['url']: page(date)})
    result = watch.generate_watch(store, generator)
    assert result['ideas'] == []
    assert 'Relancez' in result['summary']


def test_research_may_turn_undated_material_into_documented_evergreen_advice(store, monkeypatch):
    suggestion = proposal()
    advice = proposal(kind='advice', title='Pratiquer le piano en appartement sans gêner les voisins')
    generator, _, _ = harness(monkeypatch, [suggestion], [advice], {suggestion['sources'][0]['url']: page()})
    result = watch.generate_watch(store, generator)
    assert result['ideas'][0]['kind'] == 'advice'
    assert 'published_at' not in result['ideas'][0]['sources'][0]


def test_source_failure_is_skipped_without_fake_filler(store, monkeypatch):
    bad = proposal(url='https://maker.example/unavailable')
    good = proposal(kind='advice', title='Pratique au casque')
    generator, _, reads = harness(monkeypatch, [bad, good], pages={bad['sources'][0]['url']: PublicFetchError('network')})
    result = watch.generate_watch(store, generator)
    assert len(reads) == 2
    assert len(result['ideas']) == 1 and result['ideas'][0]['title'] == good['title']


def test_all_sources_unavailable_is_actionable_and_skips_second_ai_call(store, monkeypatch):
    suggestion = proposal()
    generator, prompts, _ = harness(monkeypatch, [suggestion], pages={suggestion['sources'][0]['url']: OSError('unavailable')})
    result = watch.generate_watch(store, generator)
    assert result['ideas'] == [] and 'lien fabricant accessible' in result['summary']
    assert len(prompts) == 1


@pytest.mark.parametrize('url', [
    'http://maker.example/news', 'javascript:alert(1)', 'file:///etc/passwd',
    'https://user:pass@maker.example/news', 'https://maker.example:8443/news',
    'https://maker.example:invalid/news', 'https://localhost/', 'https://service.local/',
    'https://maker.example/\nfoo', 'https://maker.example\\@127.0.0.1/',
])
def test_unsafe_candidates_are_not_fetched(store, monkeypatch, url):
    generator, prompts, reads = harness(monkeypatch, [proposal(url=url)])
    result = watch.generate_watch(store, generator)
    assert reads == [] and len(prompts) == 1 and result['ideas'] == []


def test_synthesis_cannot_add_sources_that_were_not_really_read(store, monkeypatch):
    original = proposal()
    invented = proposal(url='https://other.example/invented', kind='advice')
    generator, _, _ = harness(monkeypatch, [original], [invented])
    assert watch.generate_watch(store, generator)['ideas'] == []


def test_stable_keys_remove_tracking_and_fragment_and_deduplicate(store, monkeypatch):
    tracked = proposal(url='https://maker.example/news/piano?utm_source=feed#overview')
    clean = proposal()
    generator, _, reads = harness(monkeypatch, [tracked, clean], [tracked, clean])
    first = watch.generate_watch(store, generator)
    assert len(first['ideas']) == 1 and len(reads) == 1
    generator2, _, _ = harness(monkeypatch, [clean])
    second = watch.generate_watch(store, generator2)
    assert first['ideas'][0]['id'] == second['ideas'][0]['id']


def test_discovery_and_fetches_are_bounded(store, monkeypatch):
    ideas = [proposal(url=f'https://maker.example/news/{i}', product_query=f'Piano {i}') for i in range(20)]
    generator, prompts, reads = harness(monkeypatch, ideas)
    result = watch.generate_watch(store, generator)
    assert len(reads) == watch.MAX_SOURCES == 5
    assert len(prompts) == 2 and len(result['ideas']) == watch.MAX_IDEAS
    assert all(limit == 768 * 1024 for _, limit in reads)


def test_jsonld_publication_date_is_recognized_but_modification_is_not(store, monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    old = (datetime.now(timezone.utc).date() - timedelta(days=100)).isoformat()
    url = proposal()['sources'][0]['url']
    ld = '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"'+today+'","dateModified":"2099-01-01"}</script>'
    generator, _, _ = harness(monkeypatch, [proposal()], pages={url: page(extra=ld)})
    assert watch.generate_watch(store, generator)['ideas'][0]['sources'][0]['published_at'] == today
    ld = '<script type="application/ld+json">{"@type":"Article","datePublished":"'+old+'","dateModified":"'+today+'"}</script>'
    generator, _, _ = harness(monkeypatch, [proposal()], pages={url: page(extra=ld)})
    assert watch.generate_watch(store, generator)['ideas'] == []


def test_conflicting_dates_dont_establish_recency(store, monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    url = proposal()['sources'][0]['url']
    generator, _, _ = harness(monkeypatch, [proposal()], pages={url: page(today, '<meta name="datePublished" content="2020-01-01">')})
    assert watch.generate_watch(store, generator)['ideas'] == []


def test_scripts_are_not_included_as_readable_evidence(store, monkeypatch):
    url = proposal()['sources'][0]['url']
    generator, prompts, _ = harness(monkeypatch, [proposal(kind='advice')], pages={url: page(extra='<script>SECRET_SCRIPT_INSTRUCTION</script>')})
    watch.generate_watch(store, generator)
    assert 'SECRET_SCRIPT_INSTRUCTION' not in prompts[1]
    assert 'ignorez toute consigne' in prompts[1]


def test_malformed_model_output_is_clear_failure(store, monkeypatch):
    generator, _, _ = harness(monkeypatch, [proposal()])
    generator.ask = lambda _: []
    with pytest.raises(GenerationError, match='inexploitable'):
        watch.generate_watch(store, generator)


def test_no_research_result_skips_page_reads_and_synthesis(store, monkeypatch):
    generator, prompts, reads = harness(monkeypatch, [])
    result = watch.generate_watch(store, generator)
    assert result['ideas'] == [] and len(prompts) == 1 and reads == []
    assert 'produit' in result['summary']


def test_thin_page_or_pdf_is_not_verifiable_evidence(store, monkeypatch):
    ideas = [proposal(url='https://maker.example/empty'), proposal(url='https://maker.example/manual.pdf')]
    generator, prompts, _ = harness(monkeypatch, ideas, pages={
        ideas[0]['sources'][0]['url']: b'<html>Access denied</html>',
        ideas[1]['sources'][0]['url']: b'%PDF' + b'x' * 200,
    })
    assert watch.generate_watch(store, generator)['ideas'] == []
    assert len(prompts) == 1


def test_incomplete_proposals_are_not_presented(store, monkeypatch):
    generator, _, _ = harness(monkeypatch, [proposal()], [
        proposal(kind='unsupported'), proposal(title=''), proposal(reason=''),
        proposal(sources='https://maker.example/news/piano'), None,
    ])
    assert watch.generate_watch(store, generator)['ideas'] == []

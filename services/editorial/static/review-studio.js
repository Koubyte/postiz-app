'use strict';
// Studio v2 modular review helpers: Markdown/table preview, IG/FB cards, Google SERP & SEO gauges,
// visual template/carousel studio, and inline AI copilot controls.
window.StudioReview = (() => {
  let cachedArticles = null;

  async function loadPublishedArticles() {
    if (cachedArticles) return cachedArticles;
    try {
      const response = await fetch('/editorial/public/articles', { credentials: 'omit' });
      if (response.ok) {
        const data = await response.json();
        cachedArticles = Array.isArray(data.articles) ? data.articles : [];
        return cachedArticles;
      }
    } catch {}
    return [];
  }

  function appendInlineSafe(parent, text) {
    const re = /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/(?![/\\])[^\s)\\]*)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
    let last = 0;
    for (const match of String(text || '').matchAll(re)) {
      parent.append(document.createTextNode(text.slice(last, match.index)));
      if (match[1]) {
        const url = safeUrl(match[2], storefrontOrigin);
        parent.append(url
          ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, match[1])
          : document.createTextNode(match[1]));
      } else {
        parent.append(el(match[3] ? 'strong' : 'code', {}, match[3] || match[4]));
      }
      last = match.index + match[0].length;
    }
    parent.append(document.createTextNode(String(text || '').slice(last)));
  }

  function renderMarkdownV2(text) {
    const box = el('div', { class: 'markdown-preview' });
    const lines = String(text || '').split('\n');
    let paragraph = [];
    let list = null;
    let i = 0;
    function flush() {
      if (paragraph.length) {
        const p = el('p');
        appendInlineSafe(p, paragraph.join('\n'));
        box.append(p);
        paragraph = [];
      }
      list = null;
    }
    function parseTableRow(line) {
      return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
    }
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { flush(); i++; continue; }
      if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
        flush();
        const table = el('table');
        const thead = el('thead');
        const hr = el('tr');
        for (const cell of parseTableRow(line)) {
          const th = el('th');
          appendInlineSafe(th, cell);
          hr.append(th);
        }
        thead.append(hr);
        table.append(thead);
        const tbody = el('tbody');
        i += 2;
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          const tr = el('tr');
          for (const cell of parseTableRow(lines[i])) {
            const td = el('td');
            appendInlineSafe(td, cell);
            tr.append(td);
          }
          tbody.append(tr);
          i++;
        }
        table.append(tbody);
        box.append(table);
        continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      const bullet = line.match(/^\s*([-*]|\d+\.)\s+(.+)$/);
      if (heading) {
        flush();
        const h = el('h' + Math.min(heading[1].length + 1, 4));
        appendInlineSafe(h, heading[2]);
        box.append(h);
      } else if (bullet) {
        if (paragraph.length) flush();
        const ordered = /^\d/.test(bullet[1]);
        if (!list || list.tagName !== (ordered ? 'OL' : 'UL')) {
          list = el(ordered ? 'ol' : 'ul');
          box.append(list);
        }
        const li = el('li');
        appendInlineSafe(li, bullet[2]);
        list.append(li);
      } else if (line.startsWith('> ')) {
        flush();
        const q = el('blockquote');
        appendInlineSafe(q, line.slice(2));
        box.append(q);
      } else {
        if (list) flush();
        paragraph.push(line);
      }
      i++;
    }
    flush();
    return box;
  }

  function countWords(text) {
    return String(text || '').trim().split(/\s+/).filter(Boolean).length;
  }

  function countInternalLinks(markdown) {
    const matches = String(markdown || '').match(/\]\((?:\/blog\/|https:\/\/planetelaser\.fr\/)/g);
    return matches ? matches.length : 0;
  }

  function buildSocialPreview(platform, data) {
    const isIg = platform === 'instagram';
    const text = isIg ? (data.instagram || '') : (data.facebook || '');
    const slides = Array.isArray(data.slides) && data.slides.length ? data.slides : (data.imageUrl ? [data.imageUrl] : []);
    let idx = 0;

    const card = el('article', { class: 'social-preview-card' });
    card.append(el('div', { class: 'social-preview-head' },
      el('div', { class: 'social-avatar' }, 'PL'),
      el('div', { class: 'social-preview-head-meta' },
        el('strong', {}, isIg ? 'planete_laser' : 'Planète Laser · Forbach'),
        el('span', {}, isIg ? 'Instagram · 4:5' : 'Facebook · Page magasin'))));

    if (slides.length) {
      const mediaBox = el('div', { class: 'social-preview-media' });
      const img = el('img', { src: slides[0], alt: 'Aperçu visuel' });
      mediaBox.append(img);
      if (slides.length > 1) {
        const pager = el('div', { class: 'carousel-controls' });
        const label = el('span', { class: 'hint' }, `Slide 1 / ${slides.length}`);
        const prev = el('button', { type: 'button', class: 'button secondary', onclick: () => {
          idx = (idx - 1 + slides.length) % slides.length;
          img.src = slides[idx];
          label.textContent = `Slide ${idx + 1} / ${slides.length}`;
        } }, '←');
        const next = el('button', { type: 'button', class: 'button secondary', onclick: () => {
          idx = (idx + 1) % slides.length;
          img.src = slides[idx];
          label.textContent = `Slide ${idx + 1} / ${slides.length}`;
        } }, '→');
        pager.append(prev, label, next);
        mediaBox.append(pager);
      }
      card.append(mediaBox);
    }

    card.append(el('div', { class: 'social-preview-body' }, text || 'Aucun texte saisi.'));
    const metrics = el('div', { class: 'social-preview-metrics' });
    const chars = text.length;
    const words = countWords(text);
    if (isIg) {
      const hashtags = (text.match(/#[^\s#]+/g) || []).length;
      metrics.append(
        el('span', { class: 'v2-pill ' + (chars <= 2200 && chars > 0 ? 'ok' : 'bad') }, `${chars} / 2 200 car.`),
        el('span', { class: 'v2-pill ' + (hashtags <= 5 ? 'ok' : 'warn') }, `${hashtags} / 5 hashtags`),
        el('span', { class: 'v2-pill' }, `${words} mots`),
      );
    } else {
      metrics.append(
        el('span', { class: 'v2-pill ' + (words >= 60 ? 'ok' : 'warn') }, `${words} mots`),
        el('span', { class: 'v2-pill' }, `${chars} caractères`),
      );
    }
    card.append(metrics);
    return card;
  }

  function buildSerpPreview(data) {
    const title = (data.seoTitle || data.title || 'Titre de l’article').trim();
    const desc = (data.seoDescription || data.excerpt || '').trim();
    const slug = (data.slug || 'article').trim();
    const md = data.markdown || '';
    const tLen = title.length;
    const dLen = desc.length;
    const words = countWords(md);
    const internalLinks = countInternalLinks(md);

    const wrap = el('div', {});
    wrap.append(
      el('div', { class: 'serp-card' },
        el('div', { class: 'serp-url' }, `https://planetelaser.fr › blog › ${slug}`),
        el('h4', { class: 'serp-title' }, tLen > 60 ? title.slice(0, 59) + '…' : title),
        el('p', { class: 'serp-desc' }, dLen > 160 ? desc.slice(0, 159) + '…' : (desc || 'Ajoutez une meta description incitative (130 à 155 caractères).'))),
      el('div', { class: 'seo-gauges' },
        el('span', { class: 'v2-pill ' + (tLen > 0 && tLen <= 60 ? 'ok' : tLen <= 70 ? 'warn' : 'bad') }, `Titre SEO : ${tLen} / 60`),
        el('span', { class: 'v2-pill ' + (dLen >= 120 && dLen <= 160 ? 'ok' : dLen > 160 ? 'bad' : 'warn') }, `Meta desc : ${dLen} / 160`),
        el('span', { class: 'v2-pill ' + (words >= 500 ? 'ok' : 'warn') }, `${words} mots (cible 500+)`),
        el('span', { class: 'v2-pill ' + (internalLinks >= 2 ? 'ok' : internalLinks === 1 ? 'warn' : '') }, `${internalLinks} lien${internalLinks > 1 ? 's' : ''} interne${internalLinks > 1 ? 's' : ''}`)),
    );
    return wrap;
  }

  function buildMarkdownToolbar(textarea, onEdited) {
    const bar = el('div', { class: 'md-toolbar' });
    function insert(before, after = '', placeholder = '') {
      const start = textarea.selectionStart ?? textarea.value.length;
      const end = textarea.selectionEnd ?? start;
      const selected = textarea.value.slice(start, end) || placeholder;
      const next = textarea.value.slice(0, start) + before + selected + after + textarea.value.slice(end);
      textarea.value = next;
      textarea.focus();
      const cursor = start + before.length + selected.length + after.length;
      textarea.setSelectionRange(cursor, cursor);
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      onEdited?.();
    }
    for (const [label, fn] of [
      ['H2', () => insert('\n## ', '\n', 'Titre de section')],
      ['H3', () => insert('\n### ', '\n', 'Sous-titre')],
      ['Gras', () => insert('**', '**', 'texte')],
      ['Liste', () => insert('\n- ', '\n- ', 'Premier point')],
      ['Tableau', () => insert('\n| Critère | Détail |\n| --- | --- |\n| Usage | ... |\n')],
    ]) {
      bar.append(el('button', { type: 'button', onclick: fn }, label));
    }
    const linkSelect = el('select', { 'aria-label': 'Insérer un lien vers un article publié' },
      el('option', { value: '' }, '+ Lien article interne…'));
    loadPublishedArticles().then(articles => {
      for (const a of articles) {
        linkSelect.append(el('option', { value: `/blog/${a.slug}` }, a.title.slice(0, 55)));
      }
    });
    linkSelect.onchange = () => {
      if (!linkSelect.value) return;
      const label = linkSelect.selectedOptions[0]?.textContent || 'ce guide';
      insert('[', `](${linkSelect.value})`, label.toLowerCase());
      linkSelect.value = '';
    };
    bar.append(linkSelect);
    return bar;
  }

  function buildVisualStudioPanel(item, callbacks) {
    const box = el('div', { class: 'visual-studio-box' });
    const content = item.content || {};
    const editable = ['review', 'approved', 'rejected', 'blocked', 'failed'].includes(item.status);
    const primaryLabel = item.kind === 'blog' ? 'Couverture du blog' : 'Visuel social';
    const slides = Array.isArray(item.carousel_media_urls) && item.carousel_media_urls.length >= 2
      ? item.carousel_media_urls
      : (item.kind === 'blog'
          ? (item.blog_media_url ? [item.blog_media_url] : [])
          : (item.media_url ? [item.media_url] : []));
    let currentSlide = 0;

    const stage = el('div', { class: 'visual-stage' });
    if (slides.length) {
      const img = el('img', { src: slides[0], alt: content.alt || primaryLabel });
      const openFull = el('a', { href: slides[0], target: '_blank', rel: 'noopener noreferrer', 'aria-label': `${primaryLabel} · ouvrir en grand` }, img);
      stage.append(openFull);
      box.append(stage);

      if (slides.length > 1) {
        const counter = el('span', { class: 'hint' }, `Page 1 / ${slides.length}`);
        const showSlide = (nextIdx) => {
          currentSlide = (nextIdx + slides.length) % slides.length;
          img.src = slides[currentSlide];
          openFull.href = slides[currentSlide];
          counter.textContent = `Page ${currentSlide + 1} / ${slides.length}`;
          thumbs.querySelectorAll('.carousel-thumb').forEach((b, i) => b.classList.toggle('active', i === currentSlide));
        };
        const controls = el('div', { class: 'carousel-controls' },
          el('button', { type: 'button', class: 'button secondary', onclick: () => showSlide(currentSlide - 1) }, '←'),
          counter,
          el('button', { type: 'button', class: 'button secondary', onclick: () => showSlide(currentSlide + 1) }, '→'));
        const thumbs = el('div', { class: 'carousel-thumbs' },
          ...slides.map((url, idx) => el('button', {
            type: 'button',
            class: 'carousel-thumb' + (idx === 0 ? ' active' : ''),
            'aria-label': `Afficher la page ${idx + 1}`,
            onclick: () => showSlide(idx),
          }, el('img', { src: url, alt: `Page ${idx + 1}` }))));
        box.append(controls, thumbs);
      } else {
        box.append(el('p', { class: 'hint' }, el('a', { href: slides[0], target: '_blank', rel: 'noopener noreferrer' }, `${primaryLabel} · agrandir ↗`)));
      }
    } else {
      box.append(el('div', { class: 'empty' }, 'Aucun visuel généré pour le moment.'));
    }

    if (editable && item.kind === 'social') {
      const currentTpl = content.template || 'classic';
      const templates = [
        ['classic', 'Classique'],
        ['minimal', 'Plein cadre'],
        ['raw', 'Photo brute'],
        ['tip_card', 'Carte conseil'],
      ];
      const switcher = el('div', { class: 'template-switcher', role: 'group', 'aria-label': 'Gabarit visuel' });
      for (const [val, label] of templates) {
        const btn = el('button', {
          type: 'button',
          class: 'template-btn',
          'aria-pressed': currentTpl === val ? 'true' : 'false',
          disabled: Boolean(state.pending),
          onclick: () => callbacks.onTemplateSwitch?.(val, btn),
        }, label);
        switcher.append(btn);
      }
      box.append(switcher);
    }

    if (editable) {
      const regenDrawer = el('div', { class: 'visual-drawer', hidden: true });
      const visualInput = el('textarea', {
        rows: 3,
        maxlength: 2000,
        placeholder: 'Ex. Plan large sur une scène de club, lumière bleue, pas de texte incrusté…',
        value: content.visual_instructions || '',
      });
      const regenGo = el('button', { type: 'button', class: 'button primary' }, 'Lancer la génération d’image');
      regenGo.onclick = () => callbacks.onRegenerateVisual?.(visualInput.value.trim(), regenGo);
      regenDrawer.append(el('label', {}, 'Direction visuelle souhaitée', visualInput), regenGo);

      const uploadDrawer = el('div', { class: 'visual-drawer', hidden: true });
      const purposeSel = el('select', {},
        el('option', { value: 'reference' }, 'Photo de référence du produit (mise en scène IA)'),
        el('option', { value: 'final' }, 'Visuel final prêt à publier (sans génération)'));
      const fileInput = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp' });
      const uploadGo = el('button', { type: 'button', class: 'button primary' }, 'Envoyer cette image');
      uploadGo.onclick = () => {
        const file = fileInput.files?.[0];
        if (!file) { toast('Choisissez un fichier image (PNG, JPEG ou WebP).'); return; }
        callbacks.onUploadImage?.(file, purposeSel.value, uploadGo);
      };
      uploadDrawer.append(el('label', {}, 'Utilisation de l’image', purposeSel), fileInput, uploadGo);

      const actionRow = el('div', { class: 'visual-actions-row' },
        el('button', {
          type: 'button',
          class: 'button secondary',
          onclick: () => { regenDrawer.hidden = !regenDrawer.hidden; uploadDrawer.hidden = true; },
        }, 'Régénérer l’image'),
        el('button', {
          type: 'button',
          class: 'button secondary',
          onclick: () => { uploadDrawer.hidden = !uploadDrawer.hidden; regenDrawer.hidden = true; },
        }, 'Importer photo'));
      box.append(actionRow, regenDrawer, uploadDrawer);
    }

    return box;
  }

  function buildAiCopilotBar(item, onApply) {
    const editable = ['review', 'approved', 'rejected', 'blocked', 'failed'].includes(item.status);
    if (!editable) return null;
    const bar = el('section', { class: 'ai-copilot-bar', 'aria-label': 'Retouche rapide par l’IA' });
    bar.append(el('div', { class: 'ai-copilot-head' },
      el('strong', {}, 'Retouche IA ciblée'),
      el('span', { class: 'hint' }, 'Modifie uniquement ce brouillon')));
    const input = el('input', {
      type: 'text',
      maxlength: 2000,
      placeholder: 'Ex. Rends l’accroche plus directe, ou change le décor pour une salle de répète…',
    });
    const scope = el('select', { 'aria-label': 'Cible de la retouche' },
      el('option', { value: 'text' }, 'Texte seul'),
      el('option', { value: 'visual' }, 'Image seule'),
      el('option', { value: 'both' }, 'Texte + Image'));
    const chips = [
      ['Accroche plus punchy', 'Rends la première phrase et le titre visuel plus percutants et concrets, sans blabla.', 'text'],
      ['Plus court', 'Raccourcis les textes de 30 % en gardant uniquement l’essentiel pratique.', 'text'],
      ['Ton plus rock', 'Renforce le côté chaleureux, passionné de musique et rock tout en restant pro.', 'text'],
      ['Refaire juste l’image', 'Propose une nouvelle scène photographique plus contrastée et réaliste, cadrage différent.', 'visual'],
      ['Ajouter CTA magasin', 'Termine par une invitation concrète à venir essayer en magasin à Forbach.', 'text'],
    ];
    const chipRow = el('div', { class: 'ai-chips' });
    for (const [label, prompt, defaultScope] of chips) {
      chipRow.append(el('button', {
        type: 'button',
        class: 'ai-chip',
        onclick: () => {
          input.value = prompt;
          scope.value = defaultScope;
          input.focus();
        },
      }, label));
    }
    const submit = el('button', { type: 'button', class: 'button primary' }, 'Appliquer');
    submit.onclick = () => onApply(input.value.trim(), scope.value, submit);
    bar.append(chipRow, el('div', { class: 'ai-copilot-form' }, input, scope, submit));
    return bar;
  }

  // Live editorial quality of a social draft, with a one-click AI correction.
  function buildQualityPanel(item, onFix) {
    const quality = item.quality;
    if (!quality || item.kind !== 'social') return null;
    const issues = [...(quality.blocking || []), ...(quality.warnings || [])];
    const level = quality.blocking?.length ? 'bad' : issues.length ? 'warn' : 'ok';
    const panel = el('section', { class: `quality-panel ${level}`, 'aria-label': 'Qualité du texte' });
    panel.append(el('div', { class: 'quality-head' },
      el('strong', {}, 'Qualité du texte'),
      el('span', { class: `v2-pill ${level}` }, `${quality.score}/100`)));
    if (!issues.length) {
      panel.append(el('p', { class: 'hint' }, 'Conforme au guide de rédaction.'));
      return panel;
    }
    panel.append(el('ul', {},
      ...(quality.blocking || []).map((issue) => el('li', { class: 'is-blocking' }, issue)),
      ...(quality.warnings || []).map((issue) => el('li', {}, issue))));
    const editable = ['review', 'approved', 'rejected', 'blocked', 'failed'].includes(item.status);
    if (editable && onFix) {
      const fix = el('button', { type: 'button', class: 'button secondary' }, 'Corriger selon le guide');
      fix.onclick = () => onFix(('Réécris les deux légendes selon le guide de rédaction en corrigeant : ' + issues.join(' ; ')).slice(0, 1900), fix);
      panel.append(fix);
    }
    return panel;
  }

  function buildCarouselEditor(initialSlides, onChanged, onRecomposite, canRecomposite) {
    let slides = Array.isArray(initialSlides) ? initialSlides.map(s => ({ headline: s.headline || '', body: s.body || '' })) : [];
    const box = el('section', { class: 'carousel-editor' });

    function renderList() {
      box.replaceChildren();
      const head = el('div', { class: 'carousel-editor-head' },
        el('strong', {}, `Carrousel (${slides.length ? slides.length + ' pages' : 'désactivé'})`));
      const btns = el('div', { class: 'carousel-slide-actions' });
      if (!slides.length) {
        btns.append(el('button', {
          type: 'button',
          class: 'button secondary',
          onclick: () => {
            slides = [
              { headline: 'Page 1 · L’essentiel', body: '' },
              { headline: '1er point clé', body: 'Explication courte et concrète.' },
              { headline: 'À retenir au magasin', body: 'Passe nous voir à Forbach pour essayer.' },
            ];
            onChanged(slides);
            renderList();
          },
        }, '+ Activer en carrousel (3 pages)'));
      } else {
        if (slides.length < 5) {
          btns.append(el('button', {
            type: 'button',
            class: 'button secondary',
            onclick: () => {
              slides.push({ headline: `Point ${slides.length + 1}`, body: '' });
              onChanged(slides);
              renderList();
            },
          }, '+ Ajouter page'));
        }
        if (canRecomposite) {
          const recomp = el('button', {
            type: 'button',
            class: 'button primary',
            onclick: () => onRecomposite(slides, recomp),
          }, 'Actualiser le rendu');
          btns.append(recomp);
        }
        btns.append(el('button', {
          type: 'button',
          class: 'button danger',
          onclick: () => {
            slides = [];
            onChanged(slides);
            renderList();
          },
        }, 'Revenir à 1 image'));
      }
      head.append(btns);
      box.append(head);

      slides.forEach((slide, idx) => {
        const row = el('div', { class: 'carousel-slide-row' });
        const top = el('div', { class: 'carousel-slide-top' },
          el('span', { class: 'hint' }, `Page ${idx + 1}${idx === 0 ? ' (couverture photo)' : ''}`));
        const rowActions = el('div', { class: 'carousel-slide-actions' });
        if (idx > 0) {
          rowActions.append(el('button', {
            type: 'button',
            class: 'button secondary',
            onclick: () => {
              [slides[idx - 1], slides[idx]] = [slides[idx], slides[idx - 1]];
              onChanged(slides);
              renderList();
            },
          }, '↑'));
        }
        if (idx < slides.length - 1) {
          rowActions.append(el('button', {
            type: 'button',
            class: 'button secondary',
            onclick: () => {
              [slides[idx + 1], slides[idx]] = [slides[idx], slides[idx + 1]];
              onChanged(slides);
              renderList();
            },
          }, '↓'));
        }
        if (slides.length > 2) {
          rowActions.append(el('button', {
            type: 'button',
            class: 'button danger',
            onclick: () => {
              slides.splice(idx, 1);
              onChanged(slides);
              renderList();
            },
          }, '×'));
        }
        top.append(rowActions);
        const hInput = el('input', { type: 'text', maxlength: 120, value: slide.headline, placeholder: 'Titre de la page' });
        hInput.oninput = () => { slide.headline = hInput.value; onChanged(slides); };
        const bInput = el('textarea', { rows: 2, maxlength: 420, value: slide.body, placeholder: idx === 0 ? 'Sous-titre facultatif' : 'Texte court de la carte' });
        bInput.oninput = () => { slide.body = bInput.value; onChanged(slides); };
        row.append(top, hInput, bInput);
        box.append(row);
      });
    }
    renderList();
    return box;
  }

  return {
    renderMarkdownV2,
    buildSocialPreview,
    buildSerpPreview,
    buildMarkdownToolbar,
    buildVisualStudioPanel,
    buildAiCopilotBar,
    buildQualityPanel,
    buildCarouselEditor,
  };
})();

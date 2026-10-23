'use strict';
const $ = (id) => document.getElementById(id);
const state = {
  data: null,
  weekId: null,
  dirty: false,
  pending: false,
  item: null,
  loading: false,
};
const labels = {
  plan_review: 'Plan à valider',
  revising: 'Modification d’un sujet',
  preparing: 'Préparation du plan',
  publishing: 'Publication en cours',
  scheduled: 'Programmé dans Postiz',
  rendering: 'Création du visuel',
  generating: 'En préparation',
  review: 'À relire',
  approved: 'Approuvé · transfert en attente',
  published: 'Publié',
  blocked: 'À vérifier',
  failed: 'Erreur',
  rejected: 'Refusé',
  queued: 'En attente',
  pending: 'En attente',
  used: 'Intégré au plan',
  planned: 'Intégré au plan',
  in_plan: 'Intégré au plan',
  processing: 'En cours',
};
const kinds = {
  product: 'Produit',
  conseil: 'Conseil',
  advice: 'Conseil',
  tip: 'Conseil',
  news: 'Actualité',
  actualite: 'Actualité',
  store: 'Vie du magasin',
  magasin: 'Vie du magasin',
  blog: 'Article de blog',
  social: 'Publication',
};
const dateFormat = new Intl.DateTimeFormat('fr-FR', {
  timeZone: 'Europe/Paris',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});
const dateParts = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Europe/Paris',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k === 'checked' || k === 'disabled' || k === 'hidden') n[k] = v;
    else if (k === 'value') n.value = v ?? '';
    else n.setAttribute(k, v);
  });
  children
    .flat(Infinity)
    .filter((c) => c !== undefined && c !== null)
    .forEach((c) =>
      n.append(c instanceof Node ? c : document.createTextNode(String(c))),
    );
  return n;
}
function safeUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const u = new URL(value, location.origin);
    return ['http:', 'https:'].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
function dateLabel(value) {
  if (!value) return 'Date à définir';
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? 'Date à vérifier'
    : dateFormat.format(d) + ' · Paris';
}
function parisInput(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const p = Object.fromEntries(
    dateParts.formatToParts(d).map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
function parisIso(value) {
  if (!value)
    throw new Error('Choisissez une date et une heure de publication.');
  let guess = new Date(value + 'Z');
  for (let i = 0; i < 3; i++) {
    const p = parisInput(guess.toISOString());
    const delta = new Date(value + 'Z').getTime() - new Date(p + 'Z').getTime();
    guess = new Date(guess.getTime() + delta);
  }
  if (parisInput(guess.toISOString()) !== value)
    throw new Error(
      'Cette heure n’existe pas à Paris lors du changement d’heure. Choisissez une autre heure.',
    );
  if (
    [-3600000, 3600000].some(
      (offset) =>
        parisInput(new Date(guess.getTime() + offset).toISOString()) === value,
    )
  )
    throw new Error(
      'Cette heure se produit deux fois à Paris lors du changement d’heure. Choisissez une heure après 3 h pour éviter toute ambiguïté.',
    );
  return guess.toISOString();
}
function badge(status) {
  return el(
    'span',
    { class: 'badge ' + (status || '') },
    labels[status] || status || 'En attente',
  );
}
function message(text, error = false) {
  const n = $(error ? 'error' : 'notice');
  n.textContent = text;
  n.hidden = !text;
}
function toast(text) {
  $('toast').textContent = text;
  $('toast').hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($('toast').hidden = true), 5000);
}
async function api(path, body) {
  const response = await fetch('/editorial/api' + path, {
    credentials: 'same-origin',
    headers:
      body === undefined
        ? {}
        : { 'Content-Type': 'application/json', 'X-Editorial-Action': '1' },
    method: body === undefined ? 'GET' : 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    $('login').hidden = false;
    $('workspace').hidden = true;
    throw new Error('Votre session a expiré. Connectez-vous à Postiz.');
  }
  let data = {};
  try {
    data = await response.json();
  } catch {}
  if (!response.ok) {
    let detail =
      data.detail ||
      data.error ||
      'Le service n’a pas pu terminer cette action.';
    if (typeof detail !== 'string') detail = JSON.stringify(detail);
    throw new Error(detail);
  }
  return data;
}
async function action(button, fn) {
  if (state.pending) return;
  state.pending = true;
  button.disabled = true;
  try {
    await fn();
  } catch (e) {
    const dlg = document.querySelector('dialog[open]');
    const error = dlg?.querySelector('.dialog-error');
    if (error) {
      error.textContent = e.message;
      error.hidden = false;
    } else message(e.message, true);
  } finally {
    state.pending = false;
    button.disabled = false;
  }
}
function currentWeek() {
  return state.data?.weeks?.find((w) => w.id === state.weekId);
}
async function refresh(force = false) {
  if (state.loading) return;
  state.loading = true;
  try {
    const data = await api('/state');
    state.data = data;
    $('login').hidden = true;
    $('workspace').hidden = false;
    $('workspace').setAttribute('aria-busy', 'false');
    $('prepare').disabled = false;
    $('pause').disabled = false;
    $('pause').textContent = data.paused ? 'Reprendre le studio' : 'Suspendre';
    if (!state.weekId || !data.weeks?.some((w) => w.id === state.weekId))
      state.weekId = data.weeks?.[0]?.id ?? null;
    if (
      force ||
      (!state.dirty &&
        !$('item-dialog').open &&
        !document.activeElement?.matches(
          '#workspace input, #workspace textarea, .plan-panel select',
        ))
    ) {
      render();
    }
    if (data.paused)
      message(
        'Studio suspendu : les nouvelles préparations et les transferts vers Postiz sont arrêtés. Les posts déjà programmés dans Postiz restent actifs ; gérez-les dans son calendrier.',
      );
    else if (!state.dirty) message('');
    $('error').hidden = true;
    const linked = new URLSearchParams(location.search).get('item');
    if (linked && !new URLSearchParams(location.search).has('conversation') && !state.itemLinkOpened) {
      const item = data.weeks.flatMap(w => w.items || []).find(i => i.id === linked);
      if (item) { state.itemLinkOpened = true; openItem(item); }
    }
  } catch (e) {
    message(e.message, true);
  } finally {
    state.loading = false;
  }
}
function render() {
  const weeks = state.data.weeks || [];
  $('weeks').replaceChildren(
    ...weeks.map((w) =>
      el(
        'option',
        { value: w.id },
        'Semaine du ' +
          new Date(w.week + 'T12:00:00').toLocaleDateString('fr-FR', {
            day: 'numeric',
            month: 'long',
          }),
      ),
    ),
  );
  $('weeks').value = state.weekId || '';
  $('weeks').disabled = !weeks.length;
  const w = currentWeek();
  const items = w?.items || [];
  const productCount = new Set(
    (w?.plan?.subjects || [])
      .filter((s) => s.kind === 'product' && s.product_id)
      .map((s) => s.product_id),
  ).size;
  const stats = [
    ['7', 'sujets Facebook + Instagram'],
    ['1', 'article pour le blog'],
    [String(productCount), 'produits distincts'],
    [
      String(items.filter((i) => i.status === 'review').length),
      'contenus à relire',
    ],
  ];
  $('stats').replaceChildren(
    ...stats.map(([n, t], i) =>
      el(
        'div',
        { class: 'stat' },
        el('strong', { class: i === 3 ? 'accent' : '' }, n),
        el('span', {}, t),
      ),
    ),
  );
  const out = $('week-content');
  out.replaceChildren();
  if (!w) {
    out.append(
      el(
        'div',
        { class: 'empty' },
        el('h2', {}, 'Votre première semaine commence ici'),
        el(
          'p',
          {},
          'Ajoutez vos produits prioritaires, puis préparez un plan. Vous pourrez ajuster les sujets avant de lancer la création.',
        ),
      ),
    );
  } else {
    out.append(workflow(w));
    if (w.status === 'plan_review' || w.status === 'revising')
      out.append(renderPlan(w));
    else if (w.status === 'generating')
      out.append(
        el(
          'div',
          { class: 'notice' },
          'Le studio prépare les textes et les visuels selon le plan validé. Vous pouvez revenir plus tard : les contenus terminés apparaîtront ici.',
        ),
      );
    if (w.error) out.append(el('div', { class: 'notice error' }, w.error));
    if (items.length)
      out.append(el('div', { class: 'content-grid' }, ...items.map(itemCard)));
    else if (w.status === 'failed') {
      const retry = el(
        'button',
        { class: 'button secondary', type: 'button' },
        'Reprendre la préparation du plan',
      );
      retry.onclick = () =>
        action(retry, async () => {
          await api(`/weeks/${encodeURIComponent(w.id)}/retry`, {
            revision: w.revision,
          });
          await refresh(true);
          toast('Préparation du plan relancée.');
        });
      out.append(
        el(
          'div',
          { class: 'empty' },
          el('h3', {}, 'La préparation du plan demande une reprise'),
          el(
            'p',
            {},
            'Aucun contenu de cette semaine n’a été envoyé. Le studio conserve vos demandes prioritaires.',
          ),
          retry,
        ),
      );
    } else if (!['plan_review', 'revising'].includes(w.status))
      out.append(
        el(
          'div',
          { class: 'empty' },
          el('span', { class: 'loading-dot' }),
          el('p', {}, 'Les contenus de cette semaine sont en préparation.'),
        ),
      );
  }
  renderRequests();
  renderEvents();
}
function workflow(w) {
  const stage = ['preparing', 'plan_review', 'revising', 'failed'].includes(
    w.status,
  )
    ? 0
    : w.status === 'generating'
      ? 1
      : 2;
  return el(
    'div',
    { class: 'workflow' },
    ...[
      'Valider les sujets',
      'Créer les contenus',
      'Relire et approuver',
    ].flatMap((name, i) => [
      i ? el('span', { class: 'arrow', 'aria-hidden': 'true' }, '→') : null,
      el(
        'div',
        { class: 'step' + (i === stage ? ' active' : '') },
        el('span', { class: 'number' }, String(i + 1)),
        name,
      ),
    ]),
  );
}
function field(labelText, tag, value, attrs = {}) {
  const input = el(tag, { ...attrs, value });
  return { label: el('label', {}, labelText, input), input };
}
function renderPlan(w) {
  const revising = w.status === 'revising';
  const panel = el(
    'section',
    { class: 'plan-panel' },
    el(
      'div',
      { class: 'section-heading' },
      el('h3', {}, 'Les sujets proposés'),
      badge(w.status),
    ),
    el(
      'p',
      {},
      'Ajustez les titres, les angles, les scènes et les dates. Chaque date est libre, même en dehors de la semaine du plan, et affichée en heure de Paris. La validation de ce plan lance la rédaction et la création des visuels ; elle ne publie aucun contenu.',
    ),
  );
  const plan = structuredClone(w.plan);
  if (revising)
    panel.append(
      el(
        'div',
        { class: 'notice', role: 'status' },
        `Le studio modifie ${w.pending_slot !== null && w.pending_slot !== undefined ? 'le post ' + (Number(w.pending_slot) + 1) : 'le post sélectionné'}. Les six autres sujets et l’article de blog restent inchangés. Vous pourrez relire la proposition avant de valider le plan.`,
      ),
    );
  const dates = [];
  function dateField(brief) {
    const value = field(
      'Publication · heure de Paris',
      'input',
      parisInput(brief.scheduled_at),
      { type: 'datetime-local', required: true },
    );
    dates.push({ brief, input: value.input });
    value.input.addEventListener('input', markDirty);
    return value.label;
  }
  if (plan.unresolved_requests?.length)
    panel.append(
      el(
        'div',
        { class: 'notice warning' },
        el('strong', {}, 'Certaines demandes restent à préciser'),
        ...plan.unresolved_requests.map((r) =>
          el('p', {}, r.query + ' — ' + r.reason),
        ),
        el(
          'p',
          {},
          'Ajoutez une référence ou un lien fabricant dans une nouvelle demande. Les sujets ci-dessous peuvent être préparés séparément.',
        ),
      ),
    );
  const list = el('div', { class: 'plan-list' });
  for (const subject of plan.subjects || []) {
    const title = field('Sujet', 'input', subject.title, { maxlength: 160 });
    const angle = field('Angle éditorial', 'textarea', subject.angle, {
      rows: 2,
      maxlength: 2000,
    });
    const scene = field('Mise en scène', 'textarea', subject.scene, {
      rows: 2,
      maxlength: 800,
    });
    const card = el(
      'div',
      { class: 'plan-card' },
      el(
        'div',
        { class: 'card-top' },
        el(
          'span',
          { class: 'category' },
          `${Number(subject.slot) + 1} · ${kinds[subject.kind] || subject.kind}`,
        ),
        el('span', { class: 'hint' }, dateLabel(subject.scheduled_at)),
      ),
      title.label,
      angle.label,
      scene.label,
      dateField(subject),
    );
    const product = (plan.products || state.data.products || []).find(
      (p) => p.id === subject.product_id,
    );
    if (product)
      card.append(
        el(
          'p',
          { class: 'hint' },
          'Produit : ' +
            product.title +
            (product.ean ? ' · EAN ' + product.ean : '') +
            (product.price_mode === 'catalogue'
              ? ' · Prix du catalogue'
              : product.price_mode === 'custom'
                ? ' · Prix confirmé : ' + product.custom_price + ' €'
                : ' · Sans prix'),
        ),
      );
    if (product?.external)
      card.append(el('p', { class: 'hint' }, product.variant_uncertainty
        ? 'Modèle identifié · Coloris à préciser : ' + product.variant_uncertainty
        : product.media_status === 'needs_reference'
          ? 'Modèle identifié · Photo à rechercher avant la création du visuel.'
          : product.reference_images?.length
            ? 'Références fabricant : ' + product.reference_images.map((r) => r.label).join(' · ')
            : 'Modèle et photo de référence identifiés.'));
    title.input.addEventListener('input', () => {
      subject.title = title.input.value;
      markDirty();
    });
    angle.input.addEventListener('input', () => {
      subject.angle = angle.input.value;
      markDirty();
    });
    scene.input.addEventListener('input', () => {
      subject.scene = scene.input.value;
      markDirty();
    });
    card.append(
      el(
        'button',
        {
          class: 'button secondary',
          type: 'button',
          onclick: () => openSubjectRevision(w, subject.slot),
        },
        'Modifier ce post',
      ),
    );
    list.append(card);
  }
  if (plan.article) {
    const a = plan.article;
    const title = field('Titre de l’article', 'input', a.title, {
      maxlength: 160,
    });
    const angle = field('Contenu à développer', 'textarea', a.angle, {
      rows: 3,
      maxlength: 3000,
    });
    list.append(
      el(
        'div',
        { class: 'plan-card' },
        el(
          'div',
          { class: 'card-top' },
          el('span', { class: 'category' }, 'BLOG · 1 ARTICLE'),
          el('span', { class: 'hint' }, dateLabel(a.scheduled_at)),
        ),
        title.label,
        angle.label,
        dateField(a),
      ),
    );
    title.input.addEventListener('input', () => {
      a.title = title.input.value;
      markDirty();
    });
    angle.input.addEventListener('input', () => {
      a.angle = angle.input.value;
      markDirty();
    });
  }
  const save = el(
    'button',
    { class: 'button secondary', type: 'button' },
    'Enregistrer le plan',
  );
  const approve = el(
    'button',
    { class: 'button primary', type: 'button' },
    'Valider le plan et lancer la création',
  );
  function markDirty() {
    state.dirty = true;
    approve.disabled = true;
    save.textContent = 'Enregistrer mes modifications';
  }
  save.onclick = () =>
    action(save, async () => {
      dates.forEach(({ brief, input }) => {
        brief.scheduled_at = parisIso(input.value);
      });
      await api(`/weeks/${encodeURIComponent(w.id)}/save`, {
        revision: w.revision,
        plan,
      });
      state.dirty = false;
      await refresh(true);
      toast('Plan enregistré. Vous pouvez maintenant le valider.');
    });
  approve.onclick = () =>
    action(approve, async () => {
      await api(`/weeks/${encodeURIComponent(w.id)}/approve`, {
        revision: w.revision,
      });
      state.dirty = false;
      await refresh(true);
      toast('Plan validé. La création des contenus commence.');
    });
  panel.append(
    list,
    ...(plan.sources?.length
      ? [
          el(
            'section',
            { class: 'sources' },
            el('h3', {}, 'Sources du plan'),
            el(
              'ul',
              {},
              ...plan.sources.map((source) => {
                const url = safeUrl(source.url);
                return el(
                  'li',
                  {},
                  url
                    ? el(
                        'a',
                        {
                          href: url,
                          target: '_blank',
                          rel: 'noopener noreferrer',
                        },
                        source.title || source.url,
                      )
                    : source.title || 'Source à vérifier',
                );
              }),
            ),
          ),
        ]
      : []),
    el(
      'div',
      { class: 'plan-actions' },
      el(
        'p',
        { class: 'hint' },
        '7 sujets sociaux · au moins 3 produits distincts · 1 article. Les publications restent soumises à votre approbation finale.',
      ),
      save,
      approve,
    ),
  );
  if (revising)
    panel
      .querySelectorAll('input,textarea,select,button')
      .forEach((input) => (input.disabled = true));
  return panel;
}
function openSubjectRevision(week, slot = null, request = null) {
  if (state.dirty) {
    const text =
      'Enregistrez d’abord vos modifications du plan avant de demander la modification d’un post.';
    message(text, true);
    toast(text);
    return;
  }
  if (
    currentWeek()?.id !== week.id ||
    currentWeek()?.status !== 'plan_review'
  ) {
    message(
      'La modification d’un sujet est disponible tant que le plan attend votre validation.',
      true,
    );
    return;
  }
  const dialog = $('subject-dialog');
  const form = el('form');
  const close = () => dialog.close();
  form.append(
    el(
      'div',
      { class: 'dialog-heading' },
      el(
        'div',
        {},
        el('p', { class: 'eyebrow' }, 'UN SEUL SUJET À REVOIR'),
        el('h2', { id: 'subject-title' }, 'Modifier ce post'),
      ),
      el(
        'button',
        {
          class: 'icon-button',
          type: 'button',
          'aria-label': 'Fermer',
          onclick: close,
        },
        '×',
      ),
    ),
  );
  form.append(
    el(
      'p',
      { class: 'hint' },
      'Seul le post sélectionné sera retravaillé. Les six autres sujets, leurs dates et l’article de blog resteront inchangés. Cette action ne valide ni ne publie le plan.',
    ),
  );
  const select = el('select', { required: true, disabled: slot !== null });
  select.append(
    el('option', { value: '' }, 'Choisir le post à remplacer'),
    ...(week.plan?.subjects || []).map((s) =>
      el(
        'option',
        { value: String(s.slot) },
        `${Number(s.slot) + 1} · ${s.title}`,
      ),
    ),
  );
  select.value = slot === null ? '' : String(slot);
  form.append(el('label', {}, 'Post concerné', select));
  const requests = el('select');
  requests.append(
    el('option', { value: '' }, 'Aucune · modifier le sujet actuel'),
    ...(state.data.requests || [])
      .filter((r) => r.status === 'pending')
      .map((r) => el('option', { value: r.id }, r.query)),
  );
  requests.value = request?.id || '';
  form.append(
    el('label', {}, 'Demande produit à utiliser · facultatif', requests),
  );
  const instruction = el('textarea', {
    rows: 4,
    required: true,
    maxlength: 3000,
    placeholder:
      'Ex. Remplacer ce sujet par ce nouveau produit, sans prix, en mettant en avant son usage en répétition.',
  });
  const defaultInstruction =
    'Remplacer uniquement ce sujet par la mise en avant du produit demandé, en respectant la consigne et le prix de la demande.';
  if (request) instruction.value = defaultInstruction;
  requests.onchange = () => {
    if (requests.value && !instruction.value.trim())
      instruction.value = defaultInstruction;
  };
  form.append(el('label', {}, 'Ce que vous souhaitez changer', instruction));
  const error = el('div', {
    class: 'dialog-error notice error',
    role: 'alert',
    hidden: true,
  });
  const submit = el(
    'button',
    { class: 'button primary', type: 'submit' },
    'Revoir uniquement ce post',
  );
  form.append(
    error,
    el(
      'div',
      { class: 'dialog-footer' },
      el(
        'button',
        { class: 'button secondary', type: 'button', onclick: close },
        'Annuler',
      ),
      submit,
    ),
  );
  form.onsubmit = (e) => {
    e.preventDefault();
    action(submit, async () => {
      if (state.dirty)
        throw new Error('Enregistrez d’abord vos modifications du plan.');
      if (select.value === '')
        throw new Error('Choisissez le post à modifier.');
      const body = {
        revision: week.revision,
        instruction: instruction.value.trim(),
      };
      if (requests.value) body.request_id = requests.value;
      await api(
        `/weeks/${encodeURIComponent(week.id)}/subjects/${encodeURIComponent(select.value)}/revise`,
        body,
      );
      dialog.close();
      await refresh(true);
      toast(
        'Modification de ce seul post lancée. Les autres sujets sont conservés.',
      );
    });
  };
  $('subject-content').replaceChildren(form);
  dialog.showModal();
}
function itemCard(item) {
  const c = item.content || {};
  const w = currentWeek();
  const subject = w?.plan?.subjects?.find((s) => s.slot === item.slot);
  const image = safeUrl(item.media_url || item.blog_media_url);
  const media = el(
    'div',
    { class: 'card-media' },
    image
      ? el('img', {
          src: image,
          alt: c.alt || c.title || 'Visuel proposé',
          loading: 'lazy',
        })
      : el(
          'span',
          { class: 'image-placeholder', 'aria-hidden': 'true' },
          item.kind === 'blog' ? '✎' : '↗',
        ),
    badge(item.status),
  );
  const card = el(
    'article',
    { class: 'content-card' },
    media,
    el(
      'div',
      { class: 'card-body' },
      el(
        'span',
        { class: 'category' },
        item.kind === 'blog'
          ? 'LE BLOG'
          : `${Number(item.slot) + 1} · ${kinds[subject?.kind] || 'Facebook + Instagram'}`,
      ),
      el('h3', {}, c.title || subject?.title || 'Contenu en préparation'),
      el('p', { class: 'card-date' }, dateLabel(item.scheduled_at)),
      el(
        'p',
        { class: 'card-excerpt' },
        item.error ||
          (item.status === 'scheduled' ? 'Programmé dans le calendrier Postiz pour Facebook et Instagram. Gérez les changements de date ou l’annulation dans Postiz.' : '') ||
          c.excerpt ||
          c.facebook ||
          'Le studio prépare ce contenu.',
      ),
      el(
        'button',
        {
          class: 'button secondary',
          type: 'button',
          onclick: () => openItem(item),
        },
        item.status === 'review' ? 'Relire et valider' : 'Voir le contenu',
      ),
    ),
  );
  return card;
}
function renderRequests() {
  const rows = (state.data.requests || []).map((r) =>
    el(
      'article',
      { class: 'request-row' },
      el(
        'div',
        { class: 'request-text' },
        el('h3', {}, r.query),
        r.note ? el('p', {}, r.note) : null,
      ),
      el(
        'div',
        { class: 'request-meta' },
        r.priority === 'high' || Number(r.priority) > 0
          ? el('span', { class: 'badge review' }, 'Prioritaire')
          : null,
        el(
          'span',
          { class: 'badge' },
          r.price_mode === 'hide'
            ? 'Sans prix'
            : r.price_mode === 'custom'
              ? `${r.price} € confirmés`
              : 'Prix du catalogue',
        ),
        badge(r.status),
      ),
      r.status === 'pending' && currentWeek()?.status === 'plan_review'
        ? el(
            'button',
            {
              class: 'button secondary',
              type: 'button',
              onclick: () => openSubjectRevision(currentWeek(), null, r),
            },
            'Utiliser dans cette semaine',
          )
        : null,
    ),
  );
  $('requests').replaceChildren(
    ...(rows.length
      ? rows
      : [
          el(
            'p',
            { class: 'hint' },
            'Aucune demande pour le moment. Les prochains plans peuvent aussi sélectionner des produits dans le catalogue.',
          ),
        ]),
  );
}
function renderEvents() {
  const rows = (state.data.events || [])
    .slice(0, 25)
    .map((e) =>
      el(
        'p',
        {},
        el(
          'span',
          { class: 'hint' },
          dateLabel(e.created_at || e.created || e.at || e.timestamp) + ' — ',
        ),
        e.message || e.type || e.action || 'Mise à jour du studio',
      ),
    );
  $('events').replaceChildren(
    ...(rows.length
      ? rows
      : [el('p', {}, 'Les prochaines étapes du studio apparaîtront ici.')]),
  );
}
function appendInline(parent, text) {
  const re = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  for (const match of text.matchAll(re)) {
    parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[1]) {
      const url = safeUrl(match[2]);
      parent.append(
        url
          ? el(
              'a',
              { href: url, target: '_blank', rel: 'noopener noreferrer' },
              match[1],
            )
          : document.createTextNode(match[1]),
      );
    } else
      parent.append(el(match[3] ? 'strong' : 'code', {}, match[3] || match[4]));
    last = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(last)));
}
function renderMarkdown(text) {
  const box = el('div', { class: 'markdown-preview' });
  let paragraph = [];
  let list = null;
  function flush() {
    if (paragraph.length) {
      const p = el('p');
      appendInline(p, paragraph.join('\n'));
      box.append(p);
      paragraph = [];
    }
    list = null;
  }
  for (const line of String(text || '').split('\n')) {
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^\s*([-*]|\d+\.)\s+(.+)$/);
    if (heading) {
      flush();
      const h = el('h' + Math.min(heading[1].length + 1, 4));
      appendInline(h, heading[2]);
      box.append(h);
    } else if (bullet) {
      if (paragraph.length) flush();
      const ordered = /^\d/.test(bullet[1]);
      if (!list || list.tagName !== (ordered ? 'OL' : 'UL')) {
        list = el(ordered ? 'ol' : 'ul');
        box.append(list);
      }
      const li = el('li');
      appendInline(li, bullet[2]);
      list.append(li);
    } else if (line.startsWith('> ')) {
      flush();
      const q = el('blockquote');
      appendInline(q, line.slice(2));
      box.append(q);
    } else {
      if (list) flush();
      paragraph.push(line);
    }
  }
  flush();
  return box;
}
function openItem(item) {
  state.item = item;
  state.dirty = false;
  const content = structuredClone(item.content || {});
  const dialog = $('item-dialog');
  const root = $('review-content');
  root.replaceChildren();
  const published = item.status === 'published';
  const immutable = ![
    'review',
    'approved',
    'rejected',
    'blocked',
    'failed',
  ].includes(item.status);
  const heading = el(
    'div',
    { class: 'dialog-heading' },
    el(
      'div',
      {},
      el(
        'p',
        { class: 'eyebrow' },
        item.kind === 'blog'
          ? 'LE BLOG · RELECTURE'
          : 'FACEBOOK + INSTAGRAM · RELECTURE',
      ),
      el(
        'h2',
        { id: 'review-title' },
        content.title || 'Contenu en préparation',
      ),
    ),
    el(
      'button',
      {
        class: 'icon-button',
        type: 'button',
        'aria-label': 'Fermer',
        onclick: closeReview,
      },
      '×',
    ),
  );
  const media = el('div', { class: 'review-media' });
  for (const [label, value] of [
    ['Visuel social', item.media_url],
    ['Couverture du blog', item.blog_media_url],
    ['Photo du produit à comparer', item.source_media_url],
    ['Deuxième référence produit', item.source_media_2_url],
    ['Troisième référence produit', item.source_media_3_url],
  ]) {
    const url = safeUrl(value);
    if (url)
      media.append(
        el('img', { src: url, alt: content.alt || label }),
        el(
          'a',
          { href: url, target: '_blank', rel: 'noopener noreferrer' },
          label + ' · ouvrir en grand ↗',
        ),
      );
  }
  if (!item.media_url && !item.blog_media_url)
    media.append(
      el('div', { class: 'empty' }, 'Le visuel n’est pas encore disponible.'),
    );
  media.append(
    el(
      'p',
      { class: 'hint' },
      'L’IA a mis le produit en scène à partir de la photo de référence. Comparez le modèle, la couleur, les commandes et les proportions avant d’approuver ; vérifiez aussi la lisibilité et les droits d’utilisation.',
    ),
    badge(item.status),
  );
  const provenance = item.media?.provenance || item.provenance;
  if (provenance) {
    const sourceUrl = safeUrl(provenance.source_url);
    media.append(
      el(
        'div',
        { class: 'sources' },
        el('h3', {}, 'Origine du visuel'),
        provenance.ean
          ? el('p', { class: 'hint' }, 'EAN : ' + provenance.ean)
          : null,
        provenance.image_rights
          ? el('p', { class: 'hint' }, 'Droits : ' + provenance.image_rights)
          : null,
        provenance.price_text
          ? el(
              'p',
              { class: 'hint' },
              'Prix affiché : ' + provenance.price_text,
            )
          : null,
        sourceUrl
          ? el(
              'a',
              { href: sourceUrl, target: '_blank', rel: 'noopener noreferrer' },
              'Voir la source de la photo ↗',
            )
          : null,
      ),
    );
  }
  const fields = el(
    'div',
    { class: 'review-fields' },
    el(
      'p',
      { class: 'hint' },
      item.kind === 'blog'
        ? 'Destination : blog Planète Laser.'
        : 'Destinations : Facebook · Planète Laser et Instagram · @planete_laser.',
    ),
  );
  const inputs = {};
  function add(key, label, tag = 'input', attrs = {}) {
    const f = field(label, tag, content[key] || '', {
      disabled: immutable,
      ...attrs,
    });
    inputs[key] = f.input;
    f.input.addEventListener('input', markDirty);
    fields.append(f.label);
    return f;
  }
  add('title', 'Titre du contenu');
  if (item.kind !== 'blog')
    add('headline', 'Accroche du visuel', 'input', { maxlength: 90 });
  if (item.kind === 'blog') {
    add('slug', 'Adresse de l’article (slug)');
    const category = add('category', 'Rubrique', 'select');
    category.input.append(
      ...[
        ['guides', 'Conseils et guides'],
        ['actualites', 'Actualités'],
        ['produits', 'Produits'],
      ].map(([value, label]) => el('option', { value }, label)),
    );
    category.input.value = content.category || 'guides';
    add('excerpt', 'Introduction courte', 'textarea', { rows: 3 });
    const md = add('markdown', 'Article · Markdown', 'textarea', {
      class: 'blog-editor',
      rows: 18,
      maxlength: 18000,
    });
    const preview = el('details', {}, el('summary', {}, 'Aperçu de l’article'));
    let previewBox = renderMarkdown(content.markdown);
    preview.append(previewBox);
    md.input.addEventListener('input', () => {
      const next = renderMarkdown(md.input.value);
      previewBox.replaceWith(next);
      previewBox = next;
    });
    fields.append(preview);
  } else {
    add('facebook', 'Texte Facebook', 'textarea', { rows: 7, maxlength: 5000 });
    add('instagram', 'Texte Instagram', 'textarea', {
      rows: 8,
      maxlength: 2200,
    });
  }
  add('alt', 'Description accessible du visuel', 'textarea', { rows: 2 });
  const when = field(
    'Publication · heure de Paris',
    'input',
    parisInput(item.scheduled_at),
    { type: 'datetime-local', disabled: immutable, required: true },
  );
  when.input.addEventListener('input', markDirty);
  fields.append(when.label);
  const sources = el(
    'section',
    { class: 'sources' },
    el('h3', {}, 'Sources à consulter'),
  );
  const entries = (content.sources || []).map((s) => {
    if (typeof s === 'string') s = { url: s, title: s };
    const url = safeUrl(s.url);
    return el(
      'li',
      {},
      url
        ? el(
            'a',
            { href: url, target: '_blank', rel: 'noopener noreferrer' },
            s.title || s.url,
          )
        : String(s.title || s.url || 'Source non disponible'),
    );
  });
  sources.append(
    entries.length
      ? el('ul', {}, entries)
      : el(
          'p',
          { class: 'hint' },
          'Aucune source jointe. Vérifiez les affirmations avant de valider.',
        ),
  );
  fields.append(sources);
  if (item.error)
    fields.append(el('div', { class: 'notice error' }, item.error));
  if (item.deliveries?.length)
    fields.append(
      el(
        'section',
        { class: 'sources' },
        el('h3', {}, 'Envois'),
        ...item.deliveries.map((d) =>
          el(
            'p',
            { class: 'hint' },
            `${d.channel || d.provider || 'Publication'} : ${labels[d.status] || d.status || 'enregistrée'}${d.error ? ' — ' + d.error : ''}`,
          ),
        ),
      ),
    );
  const linkedArticle = item.companion_article;
  const createBlog = el('input', { type: 'checkbox', checked: linkedArticle ? linkedArticle.state === 'active' : item.blog_requested === true, disabled: item.status !== 'review' || linkedArticle?.status === 'published' });
  if (item.kind === 'social') {
    if (linkedArticle) fields.append(el('section', { class: 'sources' },
      el('h3', {}, 'Article associé'),
      el('p', { class: 'hint' }, labels[linkedArticle.status] || linkedArticle.status),
      linkedArticle.error ? el('p', { class: 'notice error' }, linkedArticle.error) : null,
      el('a', { href: `/editorial/?conversation=${encodeURIComponent(linkedArticle.conversation_id)}&item=${encodeURIComponent(linkedArticle.article_id)}#discussion` }, 'Ouvrir l’article')));
    if (linkedArticle?.status !== 'published') fields.append(el('section', { class: 'sources' },
      el('label', { class: 'review-check' }, createBlog, 'Créer aussi un article de blog'),
      el('p', { class: 'hint' }, 'En validant ce post avec cette case cochée, j’autorise la rédaction et la publication de l’article associé sur planetelaser.fr, sans deuxième validation. L’article sera publié dès qu’il sera rédigé et illustré, même si le post est programmé plus tard.')));
  }
  if (item.derived_from_post) fields.append(el('p', { class: 'notice' }, 'Article associé à un post. Sa publication automatique dépend de la validation de cette version du post ; une modification demande une nouvelle validation.'));
  const reviewCheck = el('input', { type: 'checkbox', disabled: true });
  const images = [...media.querySelectorAll('img')];
  function mediaReady() {
    return (
      Boolean(item.media_url || item.blog_media_url) &&
      images.length > 0 &&
      images.every((img) => img.complete && img.naturalWidth > 0)
    );
  }
  function updateMediaCheck() {
    reviewCheck.disabled =
      item.status !== 'review' || state.dirty || !mediaReady();
  }
  images.forEach((img) => {
    img.addEventListener('load', updateMediaCheck);
    img.addEventListener('error', () => {
      updateMediaCheck();
      reviewCheck.checked = false;
      approve.disabled = true;
    });
  });
  const check = el(
    'label',
    { class: 'review-check' },
    reviewCheck,
    'J’ai relu les textes, vérifié les visuels et les droits d’utilisation des images. J’approuve ces contenus pour les canaux et la date affichés.',
  );
  if (!published) fields.append(check);
  const save = el(
    'button',
    { class: 'button secondary', type: 'button', disabled: immutable },
    'Enregistrer les modifications',
  );
  const approve = el(
    'button',
    { class: 'button primary', type: 'button', disabled: true },
    'Approuver cette version',
  );
  const retry = el(
    'button',
    {
      class: 'button secondary',
      type: 'button',
      disabled: !['failed', 'blocked', 'rejected'].includes(item.status),
    },
    'Relancer la préparation',
  );
  const reject = el(
    'button',
    {
      class: 'button danger',
      type: 'button',
      disabled: immutable || item.status === 'rejected',
    },
    'Refuser',
  );
  const error = el('div', {
    class: 'dialog-error notice error',
    role: 'alert',
    hidden: true,
  });
  function markDirty() {
    state.dirty = true;
    approve.disabled = true;
    reviewCheck.checked = false;
    reviewCheck.disabled = true;
    save.textContent = 'Enregistrer mes modifications';
  }
  createBlog.onchange = () => { reviewCheck.checked = false; approve.disabled = true; };
  reviewCheck.onchange = () => {
    approve.disabled =
      !reviewCheck.checked ||
      state.dirty ||
      item.status !== 'review' ||
      !mediaReady();
  };
  updateMediaCheck();
  save.onclick = () =>
    action(save, async () => {
      Object.entries(inputs).forEach(([k, v]) => (content[k] = v.value));
      await api(`/items/${encodeURIComponent(item.id)}/save`, {
        revision: item.revision,
        content,
        scheduled_at: parisIso(when.input.value),
      });
      state.dirty = false;
      dialog.close();
      await refresh(true);
      await window.refreshChat?.();
      const updated = currentWeek()?.items?.find((i) => i.id === item.id) || window.chatItem?.(item.id);
      if (updated) openItem(updated);
      toast(
        'Modifications enregistrées. Relisez cette nouvelle version avant de l’approuver.',
      );
    });
  approve.onclick = () =>
    action(approve, async () => {
      if (!reviewCheck.checked || state.dirty || !mediaReady())
        throw new Error('Relisez et confirmez la version enregistrée.');
      if (new Date(item.scheduled_at).getTime() <= Date.now() + 300000)
        throw new Error(
          'Choisissez une date au moins cinq minutes dans le futur, enregistrez puis validez cette nouvelle version.',
        );
      await api(`/items/${encodeURIComponent(item.id)}/approve`, {
        revision: item.revision,
        media_reviewed: true,
        create_blog: item.kind === 'social' && createBlog.checked,
      });
      state.dirty = false;
      dialog.close();
      await refresh(true);
      await window.refreshChat?.();
      toast('Version approuvée pour la date affichée.');
    });
  retry.onclick = () =>
    action(retry, async () => {
      await api(`/items/${encodeURIComponent(item.id)}/retry`, {
        revision: item.revision,
      });
      state.dirty = false;
      dialog.close();
      await refresh(true);
      await window.refreshChat?.();
      toast('La préparation de ce contenu est relancée.');
    });
  reject.onclick = () => {
    const reason = el('textarea', {
      rows: 3,
      maxlength: 1000,
      placeholder: 'Ce qui doit être corrigé…',
      'aria-label': 'Motif du refus',
    });
    const confirm = el(
      'button',
      { class: 'button danger', type: 'button' },
      'Confirmer le refus',
    );
    confirm.onclick = () =>
      action(confirm, async () => {
        await api(`/items/${encodeURIComponent(item.id)}/reject`, {
          revision: item.revision,
          note: reason.value,
        });
        state.dirty = false;
        dialog.close();
        await refresh(true);
        await window.refreshChat?.();
        toast('Contenu refusé. Il ne sera pas publié.');
      });
    reject.disabled = true;
    fields.append(
      el(
        'section',
        { class: 'sources' },
        el('h3', {}, 'Votre retour'),
        reason,
        confirm,
      ),
    );
    reason.focus();
  };
  const footer = el(
    'div',
    { class: 'review-footer' },
    error,
    el(
      'p',
      { class: 'hint' },
      published
        ? 'Ce contenu a été publié.'
        : state.data.paused
          ? 'Le studio est suspendu. Une approbation sera conservée, sans lancer de publication pendant la pause.'
          : 'Toute modification annule l’approbation précédente. Sans approbation de cette version, aucune publication.',
    ),
    el(
      'div',
      { class: 'dialog-footer' },
      el(
        'button',
        { class: 'button secondary', type: 'button', onclick: closeReview },
        'Fermer',
      ),
      ...(!published
        ? [
            reject,
            ...(['failed', 'blocked', 'rejected'].includes(item.status)
              ? [retry]
              : []),
            save,
            approve,
          ]
        : []),
    ),
  );
  root.append(
    heading,
    el('div', { class: 'review-grid' }, media, fields),
    footer,
  );
  if (!dialog.open) dialog.showModal();
}
function closeReview() {
  if (
    state.dirty &&
    !window.confirm('Fermer sans enregistrer vos modifications ?')
  )
    return;
  state.dirty = false;
  state.item = null;
  $('item-dialog').close();
  render();
}
function openRequest() {
  $('request-dialog').querySelector('.dialog-error').hidden = true;
  $('request-dialog').showModal();
}
$('request-open').onclick = openRequest;
$('request-open-bottom').onclick = openRequest;
document
  .querySelectorAll('.close-dialog')
  .forEach((b) => (b.onclick = () => b.closest('dialog').close()));
$('price-mode').onchange = () => {
  $('custom-price').hidden = $('price-mode').value !== 'custom';
  $('custom-price').querySelector('input').required =
    $('price-mode').value === 'custom';
};
$('request-form').onsubmit = (e) => {
  e.preventDefault();
  const button = e.submitter;
  action(button, async () => {
    const form = new FormData(e.target);
    const body = Object.fromEntries(form.entries());
    if (body.price_mode === 'custom') body.price = Number(body.price);
    else delete body.price;
    await api('/requests', body);
    $('request-dialog').close();
    e.target.reset();
    $('custom-price').hidden = true;
    $('custom-price').querySelector('input').required = false;
    await refresh();
    toast('Demande ajoutée aux prochains plans.');
  });
};
$('prepare').onclick = (e) =>
  action(e.currentTarget, async () => {
    if (state.dirty)
      throw new Error(
        'Enregistrez vos modifications du plan avant de préparer une semaine.',
      );
    const prepared = await api('/prepare', {});
    if (prepared.id) state.weekId = prepared.id;
    await refresh(true);
    toast('Préparation du plan lancée.');
  });
$('pause').onclick = (e) =>
  action(e.currentTarget, async () => {
    await api('/pause', { paused: !state.data.paused });
    await refresh();
    toast(state.data.paused ? 'Studio suspendu.' : 'Studio repris.');
  });
$('weeks').onchange = (e) => {
  if (
    state.dirty &&
    !window.confirm('Changer de semaine sans enregistrer vos modifications ?')
  ) {
    e.target.value = state.weekId;
    return;
  }
  state.dirty = false;
  state.weekId = e.target.value;
  render();
};
$('item-dialog').addEventListener('cancel', (e) => {
  e.preventDefault();
  closeReview();
});
window.addEventListener('beforeunload', (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});
refresh();
setInterval(() => {
  if (!document.hidden) refresh();
}, 15000);

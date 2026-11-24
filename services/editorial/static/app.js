'use strict';
const $ = (id) => document.getElementById(id);
const storefrontOrigin = 'https://planetelaser.fr';
const state = {
  data: null,
  weekId: null,
  dirty: false,
  pending: false,
  item: null,
  queue: [],
  queueIndex: -1,
  loading: false,
};
const labels = {
  plan_review: 'Plan à valider',
  revising: 'Modification d’un sujet',
  preparing: 'Préparation du plan',
  publishing: 'Publication en cours',
  scheduled: 'Programmé dans Postiz',
  managed: 'Géré dans le calendrier Postiz',
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
function safeUrl(value, base = location.origin) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const u = new URL(value, base);
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
      if (item) {
        state.itemLinkOpened = true;
        api('/contents/' + encodeURIComponent(item.id))
          .then((full) => openItem(full))
          .catch(() => openItem(item));
      }
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
      out.append(el('div', { class: 'content-grid' }, ...items.map((it) => itemCard(it, items))));
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
      'Ajustez un titre, un angle ou une date (heure de Paris) avec « Ajuster », ou demandez une autre proposition à l’IA. Valider le plan lance la création ; aucune publication ne part sans votre accord.',
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
  function dateField(brief, dayLabel) {
    const value = field(
      'Publication · heure de Paris',
      'input',
      parisInput(brief.scheduled_at),
      { type: 'datetime-local', required: true },
    );
    dates.push({ brief, input: value.input });
    value.input.addEventListener('input', () => {
      markDirty();
      if (dayLabel) {
        try {
          dayLabel.textContent = dateLabel(parisIso(value.input.value));
        } catch {}
      }
    });
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
  const list = el('div', { class: 'plan-grid-v2' });
  for (const subject of plan.subjects || []) {
    const product = (plan.products || state.data.products || []).find(
      (p) => p.id === subject.product_id,
    );
    const title = field('Sujet', 'input', subject.title, { maxlength: 160 });
    const angle = field('Angle éditorial', 'textarea', subject.angle, {
      rows: 2,
      maxlength: 2000,
    });
    const scene = field('Mise en scène', 'textarea', subject.scene, {
      rows: 2,
      maxlength: 800,
    });
    const dayLabel = el('span', { class: 'plan-day-label' }, dateLabel(subject.scheduled_at));
    const slotPill = el('span', { class: 'v2-pill accent' }, `${Number(subject.slot) + 1} · ${kinds[subject.kind] || subject.kind}`);
    const pills = product ? el(
      'div',
      { class: 'pill-row plan-card-pills' },
      product
        ? el('span', { class: 'v2-pill' }, product.title.slice(0, 32))
        : null,
      product
        ? el(
            'span',
            { class: 'v2-pill ' + (product.price_mode === 'hide' ? '' : 'ok') },
            product.price_mode === 'catalogue'
              ? 'Prix catalogue'
              : product.price_mode === 'custom'
                ? `${product.custom_price} €`
                : 'Sans prix',
          )
        : null,
    ) : null;
    const titleHeading = el('h4', { class: 'plan-card-title' }, subject.title || 'Sujet à nommer');
    const angleSummary = el('p', { class: 'plan-card-angle' }, subject.angle || '');
    const details = el(
      'details',
      { class: 'plan-card-edit' },
      el('summary', {}, 'Ajuster'),
      title.label,
      angle.label,
      scene.label,
      dateField(subject, dayLabel),
    );
    const card = el(
      'article',
      { class: 'plan-card-v2' },
      el('div', { class: 'plan-card-head' }, dayLabel, slotPill),
      pills,
      titleHeading,
      angleSummary,
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
      titleHeading.textContent = title.input.value || 'Sujet à nommer';
      markDirty();
    });
    angle.input.addEventListener('input', () => {
      subject.angle = angle.input.value;
      angleSummary.textContent = angle.input.value;
      markDirty();
    });
    scene.input.addEventListener('input', () => {
      subject.scene = scene.input.value;
      markDirty();
    });
    card.append(
      el(
        'div',
        { class: 'plan-card-footer' },
        details,
        el(
          'button',
          {
            class: 'button secondary',
            type: 'button',
            onclick: () => openSubjectRevision(w, subject.slot),
          },
          'Modifier avec l’IA',
        ),
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
    const dayLabel = el('span', { class: 'plan-day-label' }, dateLabel(a.scheduled_at));
    const articleHeading = el('h4', { class: 'plan-card-title' }, a.title || 'Article de blog hebdomadaire');
    const articleAngle = el('p', { class: 'plan-card-angle' }, a.angle || '');
    list.append(
      el(
        'article',
        { class: 'plan-card-v2 is-blog' },
        el(
          'div',
          { class: 'plan-card-head' },
          dayLabel,
          el('span', { class: 'v2-pill accent' }, 'Article de blog'),
        ),
        articleHeading,
        articleAngle,
        el(
          'div',
          { class: 'plan-card-footer' },
          el(
            'details',
            { class: 'plan-card-edit' },
            el('summary', {}, 'Ajuster'),
            title.label,
            angle.label,
            dateField(a, dayLabel),
          ),
        ),
      ),
    );
    title.input.addEventListener('input', () => {
      a.title = title.input.value;
      articleHeading.textContent = title.input.value || 'Article de blog hebdomadaire';
      markDirty();
    });
    angle.input.addEventListener('input', () => {
      a.angle = angle.input.value;
      articleAngle.textContent = angle.input.value;
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
const itemTemplateLabels = { classic: 'Classique', minimal: 'Plein cadre', raw: 'Photo brute', tip_card: 'Carte conseil' };
function itemCard(item, queue = null) {
  const c = item.content || {};
  const w = currentWeek();
  const subject = w?.plan?.subjects?.find((s) => s.slot === item.slot);
  const image = safeUrl(item.media_url || item.blog_media_url);
  const tpl = c.template || item.template || 'classic';
  const slideCount = Number(item.slide_count || (Array.isArray(c.carousel_slides) ? c.carousel_slides.length : 0));
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
  const reviewBtn = el(
    'button',
    {
      class: 'button secondary',
      type: 'button',
      onclick: async () => {
        reviewBtn.disabled = true;
        try {
          const full = await api(`/contents/${encodeURIComponent(item.id)}`);
          openItem(full, queue || w?.items || []);
        } catch {
          openItem(item, queue || w?.items || []);
        } finally {
          reviewBtn.disabled = false;
        }
      },
    },
    item.status === 'review' ? 'Relire et valider' : 'Voir le contenu',
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
      (item.kind === 'social' && tpl !== 'classic') || slideCount >= 2
        ? el(
            'div',
            { class: 'pill-row' },
            item.kind === 'social' && tpl !== 'classic'
              ? el('span', { class: 'v2-pill' }, itemTemplateLabels[tpl] || tpl)
              : null,
            slideCount >= 2
              ? el('span', { class: 'v2-pill accent' }, `Carrousel · ${slideCount} pages`)
              : null,
          )
        : null,
      el('p', { class: 'card-date' }, item.status === 'managed' ? 'Horaire à consulter dans Postiz' : dateLabel(item.scheduled_at)),
      el(
        'p',
        { class: 'card-excerpt' },
        item.error ||
          (item.status === 'scheduled' ? 'Programmé dans le calendrier Postiz pour Facebook et Instagram. Gérez les changements de date ou l’annulation dans Postiz.' : '') ||
          c.excerpt ||
          c.facebook ||
          'Le studio prépare ce contenu.',
      ),
      reviewBtn,
    ),
  );
  return card;
}
function renderRequests() {
  const rows = (state.data.requests || []).map((r) => {
    const actions = el('div', { class: 'pill-row' });
    if (r.status === 'pending' && currentWeek()?.status === 'plan_review') {
      actions.append(
        el(
          'button',
          {
            class: 'button secondary',
            type: 'button',
            onclick: () => openSubjectRevision(currentWeek(), null, r),
          },
          'Utiliser dans cette semaine',
        ),
      );
    }
    if (r.status === 'pending') {
      const delBtn = el('button', { class: 'button danger', type: 'button' }, 'Supprimer');
      let armTimer = null;
      delBtn.onclick = () => {
        if (!delBtn.dataset.armed) {
          delBtn.dataset.armed = '1';
          delBtn.textContent = 'Confirmer ?';
          armTimer = setTimeout(() => {
            delete delBtn.dataset.armed;
            delBtn.textContent = 'Supprimer';
          }, 4000);
          return;
        }
        clearTimeout(armTimer);
        action(delBtn, async () => {
          await api(`/requests/${encodeURIComponent(r.id)}/delete`, {});
          await refresh(true);
          toast('Demande supprimée.');
        });
      };
      actions.append(delBtn);
    }
    return el(
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
      actions.childElementCount ? actions : null,
    );
  });
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
  const re = /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/(?![/\\])[^\s)\\]*)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  for (const match of text.matchAll(re)) {
    parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[1]) {
      const url = safeUrl(match[2], storefrontOrigin);
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
  if (window.StudioReview?.renderMarkdownV2)
    return window.StudioReview.renderMarkdownV2(text);
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
function openItem(item, queue = null) {
  if (window._reviewKeyHandler) {
    document.removeEventListener('keydown', window._reviewKeyHandler);
    window._reviewKeyHandler = null;
  }
  if (window._reviewPollTimer) {
    clearInterval(window._reviewPollTimer);
    window._reviewPollTimer = null;
  }
  state.item = item;
  state.dirty = false;
  if (Array.isArray(queue) && queue.length) state.queue = queue;
  else if (!Array.isArray(state.queue) || !state.queue.some((q) => q.id === item.id))
    state.queue = [item];
  state.queueIndex = state.queue.findIndex((q) => q.id === item.id);

  const content = structuredClone(item.content || {});
  const dialog = $('item-dialog');
  const root = $('review-content');
  root.replaceChildren();
  const published = item.status === 'published';
  const publishedBlog = published && item.kind === 'blog';
  const inCalendar = ['scheduled', 'managed'].includes(item.status);
  const deletable = ['review', 'rejected', 'blocked', 'failed', 'draft'].includes(item.status);
  const blogUrl = publishedBlog && content.slug
    ? `${storefrontOrigin}/blog/${encodeURIComponent(content.slug)}`
    : null;
  const immutable = ![
    'review',
    'approved',
    'rejected',
    'blocked',
    'failed',
  ].includes(item.status);

  async function reloadReviewItem(msg) {
    const [fresh] = await Promise.all([
      api(`/contents/${encodeURIComponent(item.id)}`),
      refresh(true),
      window.refreshChat?.(),
      window.refreshContents?.(true),
    ]);
    state.dirty = false;
    openItem(fresh, state.queue);
    if (msg) toast(msg);
  }

  let navPrev = null;
  let navNext = null;
  async function navigateQueue(delta) {
    if (state.pending || state.queueIndex < 0) return;
    const nextIdx = state.queueIndex + delta;
    if (nextIdx < 0 || nextIdx >= state.queue.length) return;
    if (state.dirty && !window.confirm('Changer de contenu sans enregistrer vos modifications ?'))
      return;
    const nextEntry = state.queue[nextIdx];
    if (!nextEntry) return;
    if (navPrev) navPrev.disabled = true;
    if (navNext) navNext.disabled = true;
    try {
      const full = await api(`/contents/${encodeURIComponent(nextEntry.id)}`);
      state.dirty = false;
      openItem(full, state.queue);
    } catch (e) {
      toast(e.message || 'Impossible de charger ce contenu.');
    }
  }

  const headingActions = el('div', { class: 'review-heading-actions' });
  if (state.queue.length > 1 && state.queueIndex >= 0) {
    navPrev = el(
      'button',
      {
        type: 'button',
        disabled: state.queueIndex === 0,
        'aria-label': 'Contenu précédent (Alt+Gauche)',
        onclick: () => navigateQueue(-1),
      },
      '← Préc.',
    );
    navNext = el(
      'button',
      {
        type: 'button',
        disabled: state.queueIndex >= state.queue.length - 1,
        'aria-label': 'Contenu suivant (Alt+Droite)',
        onclick: () => navigateQueue(1),
      },
      'Suiv. →',
    );
    headingActions.append(
      el(
        'div',
        { class: 'review-queue-nav' },
        navPrev,
        el('span', { class: 'review-queue-count' }, `${state.queueIndex + 1} / ${state.queue.length}`),
        navNext,
      ),
    );
  }
  headingActions.append(
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

  const heading = el(
    'div',
    { class: 'dialog-heading review-heading' },
    el(
      'div',
      {},
      el(
        'p',
        { class: 'eyebrow' },
        item.kind === 'blog'
          ? 'ARTICLE DE BLOG'
          : 'FACEBOOK + INSTAGRAM',
      ),
      el(
        'h2',
        { id: 'review-title', title: content.title || 'Contenu en préparation' },
        content.title || 'Contenu en préparation',
      ),
      el('div', { class: 'review-meta' }, badge(item.status),
        el('span', {}, item.status === 'managed' ? 'Horaire dans le calendrier Postiz' : dateLabel(item.scheduled_at))),
    ),
    headingActions,
  );

  const media = el('div', { class: 'review-media' });
  const primaryLabel = item.kind === 'blog' ? 'Couverture du blog' : 'Visuel social';
  const primaryUrl = safeUrl(item.kind === 'blog' ? item.blog_media_url : item.media_url);
  function imagePreview(label, url, primary = false) {
    return el('figure', { class: primary ? 'review-primary-image' : 'review-reference-image' },
      el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': `${label} · ouvrir en grand` },
        el('img', { src: url, alt: primary ? content.alt || label : label, loading: primary ? 'eager' : 'lazy' })),
      el('figcaption', {}, el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, `${label} · agrandir ↗`)));
  }

  if (window.StudioReview?.buildVisualStudioPanel) {
    media.append(
      window.StudioReview.buildVisualStudioPanel(item, {
        onTemplateSwitch: (tpl, btn) =>
          action(btn, async () => {
            const res = await api(`/items/${encodeURIComponent(item.id)}/visual`, {
              revision: state.item.revision,
              template: tpl,
              recomposite_only: Boolean(
                item.has_background ||
                item.media?.provenance?.background_file ||
                (tpl === 'tip_card' && !content.product_id && !item.brief?.product_id),
              ),
            });
            await reloadReviewItem(
              res.result?.recomposited
                ? 'Gabarit visuel appliqué.'
                : 'Génération avec ce gabarit lancée…',
            );
          }),
        onRegenerateVisual: (instructions, btn, choice = {}) =>
          action(btn, async () => {
            await api(`/items/${encodeURIComponent(item.id)}/visual`, {
              revision: state.item.revision,
              visual_instructions: instructions || undefined,
              template: content.template,
              recomposite_only: false,
              staging: choice.staging,
              store_scene_id: choice.store_scene_id,
            });
            await reloadReviewItem('Génération du nouveau visuel lancée…');
          }),
        onUploadImage: (file, purpose, btn) =>
          action(btn, async () => {
            const bytes = await file.arrayBuffer();
            const response = await fetch(`/editorial/api/items/${encodeURIComponent(item.id)}/upload-image`, {
              method: 'POST',
              credentials: 'same-origin',
              headers: {
                'Content-Type': file.type || 'application/octet-stream',
                'X-Editorial-Action': '1',
                'X-Item-Revision': String(state.item.revision),
                'X-Image-Purpose': purpose,
                'X-File-Name': file.name || 'image.png',
              },
              body: bytes,
            });
            if (response.status === 401) {
              $('login').hidden = false;
              $('workspace').hidden = true;
              throw new Error('Votre session a expiré. Connectez-vous à Postiz.');
            }
            let data = {};
            try { data = await response.json(); } catch {}
            if (!response.ok) {
              const detail = data.detail || data.error || 'Importation impossible.';
              throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
            }
            await reloadReviewItem(
              purpose === 'final'
                ? 'Visuel final importé.'
                : 'Photo de référence importée et mise en scène.',
            );
          }),
      }),
    );
  } else if (primaryUrl) {
    media.append(imagePreview(primaryLabel, primaryUrl, true));
  } else {
    media.append(el('div', { class: 'empty' }, 'Le visuel n’est pas encore disponible.'));
  }

  const references = el('details', { class: 'review-references' },
    el('summary', {}, 'Références et autres formats'));
  for (const [label, value] of [
    [item.kind === 'blog' ? 'Visuel social' : 'Couverture du blog', item.kind === 'blog' ? item.media_url : item.blog_media_url],
    ['Photo du produit à comparer', item.source_media_url],
    ['Deuxième référence produit', item.source_media_2_url],
    ['Troisième référence produit', item.source_media_3_url],
  ]) {
    const url = safeUrl(value);
    if (url) references.append(imagePreview(label, url));
  }
  references.append(
    el(
      'p',
      { class: 'hint' },
      'Comparez le modèle, la couleur et les proportions avec les photos de référence.',
    ),
  );
  const provenance = item.media?.provenance || item.provenance;
  if (provenance) {
    const sourceUrl = safeUrl(provenance.source_url);
    references.append(
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
  if (references.querySelector('img') || provenance) media.append(references);

  const fields = el('div', { class: 'review-fields' });
  const qualityPanel = window.StudioReview?.buildQualityPanel?.(item, (instruction, btn) =>
    action(btn, async () => {
      await api(`/items/${encodeURIComponent(item.id)}/ai-revise`, {
        revision: state.item.revision,
        instruction,
        scope: 'text',
        template: content.template,
      });
      await reloadReviewItem('Correction lancée… Le texte se mettra à jour dès que c’est prêt.');
    }));
  if (qualityPanel) fields.append(qualityPanel);
  if (window.StudioReview?.buildAiCopilotBar) {
    const copilot = window.StudioReview.buildAiCopilotBar(item, (instruction, scope, btn) => {
      if (!instruction) {
        toast('Décrivez la retouche ou cliquez sur un raccourci.');
        return;
      }
      action(btn, async () => {
        await api(`/items/${encodeURIComponent(item.id)}/ai-revise`, {
          revision: state.item.revision,
          instruction,
          scope,
          template: content.template,
        });
        await reloadReviewItem('Retouche IA lancée… Le brouillon se mettra à jour dès que c’est prêt.');
      });
    });
    if (copilot) fields.append(copilot);
  }
  fields.append(
    el(
      'p',
      { class: 'hint' },
      item.kind === 'blog'
        ? 'Destination : blog Planète Laser.'
        : 'Destinations : Facebook · Planète Laser et Instagram · @planete_laser.',
    ),
  );

  const tabsBar = el('div', { class: 'review-tabs', role: 'tablist', 'aria-label': 'Vues du contenu' });
  const editPane = el('div', { role: 'tabpanel' });
  const previewPaneA = el('div', { role: 'tabpanel', hidden: true });
  const previewPaneB = el('div', { role: 'tabpanel', hidden: true });
  fields.append(tabsBar, editPane, previewPaneA, previewPaneB);

  const inputs = {};
  let savedPublishedState = null;
  let updateMarkdownPreview = () => {};
  function formatTags(val) {
    return Array.isArray(val) ? val.join(', ') : String(val || '');
  }
  function parseTags(val) {
    return String(val || '').split(',').map((s) => s.trim()).filter(Boolean);
  }
  function add(key, label, tag = 'input', attrs = {}) {
    const initial = key === 'tags' ? formatTags(content[key]) : (content[key] || '');
    const f = field(label, tag, initial, {
      disabled: immutable && !publishedBlog,
      ...attrs,
    });
    inputs[key] = f.input;
    f.input.addEventListener('input', markDirty);
    editPane.append(f.label);
    return f;
  }

  add('title', 'Titre du contenu');
  if (item.kind !== 'blog')
    add('headline', 'Accroche du visuel', 'input', { maxlength: 90 });

  if (item.kind === 'blog') {
    if (!publishedBlog) add('slug', 'Adresse de l’article (slug)');
    const category = add('category', 'Rubrique', 'select');
    category.input.append(
      ...[
        ['guides', 'Conseils et guides'],
        ['actualites', 'Actualités'],
        ['produits', 'Produits'],
      ].map(([value, label]) => el('option', { value }, label)),
    );
    category.input.value = content.category || 'guides';
    add('seo_title', 'Titre SEO Google (max. 60 car.)', 'input', { maxlength: 90 });
    add('seo_description', 'Meta description Google (130–160 car.)', 'textarea', { rows: 2, maxlength: 220 });
    add('tags', 'Mots-clés / tags (séparés par des virgules)', 'input', { maxlength: 300 });
    add('excerpt', 'Introduction courte', 'textarea', { rows: 3 });

    const mdArea = el('textarea', {
      id: 'review-blog-markdown',
      class: 'blog-editor with-toolbar',
      rows: 18,
      disabled: immutable && !publishedBlog,
      value: content.markdown || '',
    });
    inputs.markdown = mdArea;
    mdArea.addEventListener('input', markDirty);
    const mdWrap = el('div', {}, el('label', { for: 'review-blog-markdown' }, 'Article · Markdown'));
    if (!(immutable && !publishedBlog) && window.StudioReview?.buildMarkdownToolbar) {
      mdWrap.append(window.StudioReview.buildMarkdownToolbar(mdArea, markDirty));
    } else {
      mdArea.classList.remove('with-toolbar');
    }
    mdWrap.append(mdArea);
    editPane.append(mdWrap);

    if (publishedBlog) {
      savedPublishedState = {
        title: inputs.title.value,
        category: inputs.category.value,
        seo_title: inputs.seo_title.value,
        seo_description: inputs.seo_description.value,
        tags: formatTags(parseTags(inputs.tags.value)),
        excerpt: inputs.excerpt.value,
        markdown: inputs.markdown.value,
      };
    }

    function renderBlogPreviews() {
      previewPaneA.replaceChildren(renderMarkdown(inputs.markdown.value));
      if (window.StudioReview?.buildSerpPreview) {
        previewPaneB.replaceChildren(
          window.StudioReview.buildSerpPreview({
            title: inputs.title.value,
            seoTitle: inputs.seo_title.value,
            seoDescription: inputs.seo_description.value,
            excerpt: inputs.excerpt.value,
            slug: inputs.slug?.value || content.slug,
            markdown: inputs.markdown.value,
          }),
        );
      }
    }
    updateMarkdownPreview = renderBlogPreviews;

    const tabSpecs = [
      ['edit', 'Éditer', editPane],
      ['article', 'Aperçu Article', previewPaneA],
      ['serp', 'Aperçu Google', previewPaneB],
    ];
    tabSpecs.forEach(([key, label, pane], index) => {
      const btn = el(
        'button',
        {
          type: 'button',
          class: 'review-tab',
          role: 'tab',
          'aria-selected': index === 0 ? 'true' : 'false',
          onclick: () => {
            tabSpecs.forEach(([, , p], j) => {
              p.hidden = j !== index;
            });
            tabsBar.querySelectorAll('.review-tab').forEach((t, j) => {
              t.setAttribute('aria-selected', j === index ? 'true' : 'false');
            });
            if (key !== 'edit') renderBlogPreviews();
          },
        },
        label,
      );
      tabsBar.append(btn);
    });
  } else {
    add('facebook', 'Texte Facebook', 'textarea', { rows: 7, maxlength: 5000 });
    add('instagram', 'Texte Instagram', 'textarea', {
      rows: 8,
      maxlength: 2200,
    });
    if (!immutable && window.StudioReview?.buildCarouselEditor) {
      editPane.append(
        window.StudioReview.buildCarouselEditor(
          content.carousel_slides,
          (nextSlides) => {
            content.carousel_slides = nextSlides;
            markDirty();
          },
          (nextSlides, btn) =>
            action(btn, async () => {
              content.carousel_slides = nextSlides;
              await api(`/items/${encodeURIComponent(item.id)}/visual`, {
                revision: state.item.revision,
                template: content.template,
                carousel_slides: nextSlides,
                recomposite_only: Boolean(item.has_background || item.media?.provenance?.background_file),
              });
              await reloadReviewItem('Carrousel mis à jour.');
            }),
          Boolean(item.has_background || item.media?.provenance?.background_file),
        ),
      );
    }
    function renderSocialPreviewPane(platform, pane) {
      if (!window.StudioReview?.buildSocialPreview) return;
      pane.replaceChildren(
        window.StudioReview.buildSocialPreview(platform, {
          instagram: inputs.instagram.value,
          facebook: inputs.facebook.value,
          slides: Array.isArray(item.carousel_media_urls) && item.carousel_media_urls.length >= 2
            ? item.carousel_media_urls
            : undefined,
          imageUrl: item.media_url,
        }),
      );
    }
    const tabSpecs = [
      ['edit', 'Éditer', editPane],
      ['instagram', 'Aperçu Instagram', previewPaneA],
      ['facebook', 'Aperçu Facebook', previewPaneB],
    ];
    tabSpecs.forEach(([key, label, pane], index) => {
      const btn = el(
        'button',
        {
          type: 'button',
          class: 'review-tab',
          role: 'tab',
          'aria-selected': index === 0 ? 'true' : 'false',
          onclick: () => {
            tabSpecs.forEach(([, , p], j) => {
              p.hidden = j !== index;
            });
            tabsBar.querySelectorAll('.review-tab').forEach((t, j) => {
              t.setAttribute('aria-selected', j === index ? 'true' : 'false');
            });
            if (key === 'instagram' || key === 'facebook') renderSocialPreviewPane(key, pane);
          },
        },
        label,
      );
      tabsBar.append(btn);
    });
  }

  if (!publishedBlog) add('alt', 'Description accessible du visuel', 'textarea', { rows: 2 });
  const when = field(
    'Publication · heure de Paris',
    'input',
    parisInput(item.scheduled_at),
    { type: 'datetime-local', disabled: immutable, required: true },
  );
  when.input.addEventListener('input', markDirty);
  when.input.id = 'review-scheduled-at';
  const timingWarning = el('div', { class: 'notice review-timing-warning', role: 'status', hidden: true },
    el('div', {}, el('strong', {}, 'Horaire à actualiser'),
      el('p', {}, 'Choisissez un horaire au moins cinq minutes dans le futur avant de valider.')),
    el('button', { type: 'button', class: 'button secondary', onclick: () => {
      when.input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      when.input.focus({ preventScroll: true });
    } }, 'Changer l’horaire'));
  function updateTimingWarning() {
    let scheduled = NaN;
    try { scheduled = new Date(parisIso(when.input.value)).getTime(); } catch {}
    timingWarning.hidden = immutable || item.status === 'approved' || scheduled > Date.now() + 300000;
  }
  when.input.addEventListener('input', updateTimingWarning);
  updateTimingWarning();
  if (item.status !== 'managed' && !publishedBlog) editPane.append(when.label);
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
  editPane.append(sources);
  const notes = (content.editorial_notes || []).filter((note) => !(item.quality && note.startsWith('Qualité : ')));
  if (notes.length) editPane.append(el('details', { class: 'sources' },
    el('summary', {}, 'Remarques de rédaction · sans blocage'),
    el('ul', {}, notes.map((note) => el('li', {}, note))),
  ));
  if (item.error)
    editPane.append(el('div', { class: 'notice error' }, item.error));
  if (item.deliveries?.length)
    editPane.append(
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
    if (linkedArticle) editPane.append(el('section', { class: 'sources' },
      el('h3', {}, 'Article associé'),
      el('p', { class: 'hint' }, labels[linkedArticle.status] || linkedArticle.status),
      linkedArticle.error ? el('p', { class: 'notice error' }, linkedArticle.error) : null,
      el('a', { href: `/editorial/?conversation=${encodeURIComponent(linkedArticle.conversation_id)}&item=${encodeURIComponent(linkedArticle.article_id)}#discussion` }, 'Ouvrir l’article')));
    if (linkedArticle?.status !== 'published') editPane.append(el('section', { class: 'sources' },
      el('label', { class: 'review-check' }, createBlog, 'Créer aussi un article de blog'),
      el('p', { class: 'hint' }, 'En validant ce post avec cette case cochée, j’autorise la rédaction et la publication de l’article associé sur planetelaser.fr, sans deuxième validation. L’article sera publié dès qu’il sera rédigé et illustré, même si le post est programmé plus tard.')));
  }
  if (item.derived_from_post && !publishedBlog) editPane.append(el('p', { class: 'notice' }, 'Article associé à un post. Sa publication automatique dépend de la validation de cette version du post ; une modification demande une nouvelle validation.'));

  const save = el(
    'button',
    { class: 'button secondary review-save', type: 'button', disabled: true },
    'Enregistrer',
  );
  const approve = el(
    'button',
    { class: 'button primary review-approve', type: 'button', disabled: true },
    item.kind === 'blog' ? 'Valider l’article' : 'Valider et programmer',
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
  const delDraft = el(
    'button',
    {
      class: 'button danger',
      type: 'button',
    },
    'Supprimer',
  );
  const error = el('div', {
    class: 'dialog-error notice error',
    role: 'alert',
    hidden: true,
  });
  const updatePublished = el(
    'button',
    { class: 'button primary', type: 'button', disabled: true },
    'Mettre à jour sur le site',
  );
  const publishedHint = 'Modifiez le texte, le titre ou les balises SEO. La mise à jour sera publiée sur la même page.';
  const publishedStatus = el('p', { class: 'hint', role: 'status' }, publishedHint);
  function currentPublishedState() {
    return {
      title: inputs.title.value,
      category: inputs.category.value,
      seo_title: inputs.seo_title.value,
      seo_description: inputs.seo_description.value,
      tags: formatTags(parseTags(inputs.tags.value)),
      excerpt: inputs.excerpt.value,
      markdown: inputs.markdown.value,
    };
  }
  function syncPublishedEditor() {
    const cur = currentPublishedState();
    state.dirty = Boolean(
      savedPublishedState &&
      Object.keys(savedPublishedState).some((k) => cur[k] !== savedPublishedState[k]),
    );
    updatePublished.disabled = state.pending || !state.dirty || !cur.markdown.trim();
  }
  function markDirty() {
    if (publishedBlog) {
      publishedStatus.textContent = publishedHint;
      syncPublishedEditor();
      return;
    }
    state.dirty = true;
    approve.disabled = true;
    save.disabled = false;
    save.textContent = 'Enregistrer';
    footer.classList.add('has-changes');
  }
  // The approval click is the owner's confirmation; image loading is not a gate.
  approve.disabled = state.dirty || item.status !== 'review';

  updatePublished.onclick = async () => {
    if (state.pending || updatePublished.disabled) return;
    const editableKeys = ['title', 'category', 'seo_title', 'seo_description', 'tags', 'excerpt', 'markdown'];
    error.hidden = true;
    editableKeys.forEach((k) => { if (inputs[k]) inputs[k].disabled = true; });
    try {
      await action(updatePublished, async () => {
        const { item: updated } = await api(`/items/${encodeURIComponent(item.id)}/update-published`, {
          revision: state.item.revision,
          markdown: inputs.markdown.value,
          title: inputs.title.value,
          category: inputs.category.value,
          seo_title: inputs.seo_title.value,
          seo_description: inputs.seo_description.value,
          tags: parseTags(inputs.tags.value),
          excerpt: inputs.excerpt.value,
        });
        state.item = updated;
        inputs.title.value = updated.content.title || '';
        inputs.category.value = updated.content.category || 'guides';
        inputs.seo_title.value = updated.content.seo_title || '';
        inputs.seo_description.value = updated.content.seo_description || '';
        inputs.tags.value = formatTags(updated.content.tags);
        inputs.excerpt.value = updated.content.excerpt || '';
        inputs.markdown.value = updated.content.markdown || '';
        savedPublishedState = currentPublishedState();
        updateMarkdownPreview();
        publishedStatus.textContent = 'Correction enregistrée. Le site peut prendre une minute pour afficher la nouvelle version.';
        await refresh(true);
      });
    } finally {
      editableKeys.forEach((k) => { if (inputs[k]) inputs[k].disabled = false; });
      syncPublishedEditor();
    }
  };
  save.onclick = () =>
    action(save, async () => {
      Object.entries(inputs).forEach(([k, v]) => {
        content[k] = k === 'tags' ? parseTags(v.value) : v.value;
      });
      await api(`/items/${encodeURIComponent(item.id)}/save`, {
        revision: state.item.revision,
        content,
        scheduled_at: parisIso(when.input.value),
      });
      await reloadReviewItem('Modifications enregistrées. Relisez cette nouvelle version avant de l’approuver.');
    });
  approve.onclick = () =>
    action(approve, async () => {
      if (state.dirty || item.status !== 'review')
        throw new Error('Enregistrez les modifications avant de valider cette version.');
      if (new Date(item.scheduled_at).getTime() <= Date.now() + 300000)
        throw new Error(
          'Choisissez une date au moins cinq minutes dans le futur, enregistrez puis validez cette nouvelle version.',
        );
      await api(`/items/${encodeURIComponent(item.id)}/approve`, {
        revision: state.item.revision,
        create_blog: item.kind === 'social' && createBlog.checked,
      });
      state.dirty = false;
      closeReview();
      await refresh(true);
      await window.refreshChat?.();
      await window.refreshContents?.(true);
      toast('Version approuvée pour la date affichée.');
    });
  retry.onclick = () =>
    action(retry, async () => {
      await api(`/items/${encodeURIComponent(item.id)}/retry`, {
        revision: state.item.revision,
      });
      state.dirty = false;
      closeReview();
      await refresh(true);
      await window.refreshChat?.();
      await window.refreshContents?.(true);
      toast('La préparation de ce contenu est relancée.');
    });
  let delArmTimer = null;
  delDraft.onclick = () => {
    if (!delDraft.dataset.armed) {
      delDraft.dataset.armed = '1';
      delDraft.textContent = 'Confirmer suppression ?';
      delArmTimer = setTimeout(() => {
        delete delDraft.dataset.armed;
        delDraft.textContent = 'Supprimer';
      }, 4000);
      return;
    }
    clearTimeout(delArmTimer);
    action(delDraft, async () => {
      await api(`/items/${encodeURIComponent(item.id)}/delete`, {
        revision: state.item.revision,
      });
      state.dirty = false;
      closeReview();
      await refresh(true);
      await window.refreshChat?.();
      await window.refreshContents?.(true);
      toast('Brouillon supprimé.');
    });
  };
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
          revision: state.item.revision,
          note: reason.value,
        });
        state.dirty = false;
        closeReview();
        await refresh(true);
        await window.refreshChat?.();
        await window.refreshContents?.(true);
        toast('Contenu refusé. Il ne sera pas publié.');
      });
    reject.disabled = true;
    editPane.append(
      el(
        'section',
        { class: 'sources' },
        el('h3', {}, 'Votre retour'),
        reason,
        confirm,
      ),
    );
    tabsBar.querySelector('.review-tab')?.click();
    reason.focus();
  };
  const footer = el(
    'div',
    { class: 'review-footer' },
    error,
    publishedBlog ? publishedStatus : el(
      'p',
      { class: 'hint' },
      inCalendar
        ? 'Modifiez le contenu et l’horaire dans le calendrier Postiz.'
        : published
          ? 'Ce contenu a été publié.'
          : state.data?.paused
            ? 'Studio suspendu : la validation sera conservée.'
            : item.status === 'review'
              ? 'Votre validation autorise la publication de cette version.'
              : labels[item.status] || 'La préparation de ce contenu est en cours.',
    ),
    el(
      'div',
      { class: 'dialog-footer' },
      el(
        'button',
        { class: 'button secondary review-close', type: 'button', onclick: closeReview },
        'Fermer',
      ),
      ...(inCalendar ? [el('a', { href: '/launches', class: 'button primary' }, 'Ouvrir le calendrier')] : []),
      ...(blogUrl ? [el('a', { href: blogUrl, target: '_blank', rel: 'noopener noreferrer', class: 'button secondary' }, 'Voir l’article publié ↗')] : []),
      ...(publishedBlog ? [updatePublished] : []),
      ...(deletable ? [delDraft] : []),
      ...(!immutable
        ? [
            ...(item.status !== 'rejected' ? [reject] : []),
            ...(['failed', 'blocked', 'rejected'].includes(item.status)
              ? [retry]
              : []),
            save,
            ...(item.status === 'review' ? [approve] : []),
          ]
        : []),
    ),
  );
  root.append(
    heading,
    timingWarning,
    el('div', { class: 'review-grid' }, media, fields),
    footer,
  );
  window._reviewKeyHandler = (ev) => {
    if (!dialog.open) return;
    if (ev.altKey && ev.key === 'ArrowLeft') { ev.preventDefault(); navigateQueue(-1); }
    else if (ev.altKey && ev.key === 'ArrowRight') { ev.preventDefault(); navigateQueue(1); }
    else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
      ev.preventDefault();
      if (publishedBlog && !updatePublished.disabled) updatePublished.click();
      else if (!immutable && !save.disabled) save.click();
    }
  };
  document.addEventListener('keydown', window._reviewKeyHandler);
  if (['queued', 'generating', 'rendering'].includes(item.status)) {
    window._reviewPollTimer = setInterval(async () => {
      if (!dialog.open || state.pending || state.item?.id !== item.id) return;
      try {
        const fresh = await api(`/contents/${encodeURIComponent(item.id)}`);
        if (
          dialog.open &&
          state.item?.id === item.id &&
          (fresh.status !== item.status || fresh.revision !== item.revision)
        ) {
          await refresh(true);
          await window.refreshChat?.();
          await window.refreshContents?.(true);
          state.dirty = false;
          openItem(fresh, state.queue);
          toast('Contenu mis à jour.');
        }
      } catch {}
    }, 4000);
  }
  if (!dialog.open) dialog.showModal();
}
function closeReview() {
  if (state.pending && state.item?.status === 'published' && state.item.kind === 'blog') return;
  if (
    state.dirty &&
    !window.confirm('Fermer sans enregistrer vos modifications ?')
  )
    return;
  if (window._reviewKeyHandler) {
    document.removeEventListener('keydown', window._reviewKeyHandler);
    window._reviewKeyHandler = null;
  }
  if (window._reviewPollTimer) {
    clearInterval(window._reviewPollTimer);
    window._reviewPollTimer = null;
  }
  state.dirty = false;
  state.item = null;
  $('item-dialog').close();
  render();
}
function openRequest() {
  $('request-dialog').querySelector('.dialog-error').hidden = true;
  if ($('catalogue-search')) $('catalogue-search').value = '';
  if ($('catalogue-results')) {
    $('catalogue-results').replaceChildren();
    $('catalogue-results').hidden = true;
  }
  $('request-dialog').showModal();
}
let catalogueTimer = null;
let catalogueSeq = 0;
$('catalogue-search')?.addEventListener('input', (e) => {
  clearTimeout(catalogueTimer);
  const q = e.target.value.trim();
  const box = $('catalogue-results');
  if (!box) return;
  if (q.length < 2) {
    box.replaceChildren();
    box.hidden = true;
    return;
  }
  catalogueTimer = setTimeout(async () => {
    const seq = ++catalogueSeq;
    try {
      const data = await api(`/catalogue?q=${encodeURIComponent(q)}&limit=8`);
      if (seq !== catalogueSeq) return;
      const products = Array.isArray(data.products) ? data.products : [];
      if (!products.length) {
        box.replaceChildren(el('p', { class: 'hint' }, 'Aucun produit correspondant dans le catalogue.'));
        box.hidden = false;
        return;
      }
      box.replaceChildren(
        ...products.map((p) => {
          const thumb = safeUrl(p.thumbnail);
          const priceLabel = p.price != null ? `${p.price} €` : (p.price_from != null ? `Dès ${p.price_from} €` : 'Prix N/C');
          const stockLabel = p.available ? 'En stock' : 'Rupture';
          return el(
            'button',
            {
              type: 'button',
              class: 'catalogue-item',
              onclick: () => {
                const form = $('request-form');
                form.elements.query.value = p.ean ? `${p.title} (${p.ean})` : p.title;
                form.elements.price_mode.value = 'catalogue';
                $('price-mode').onchange();
                box.replaceChildren();
                box.hidden = true;
                $('catalogue-search').value = '';
                form.elements.note.focus();
              },
            },
            thumb ? el('img', { src: thumb, alt: '', loading: 'lazy' }) : null,
            el(
              'div',
              { class: 'catalogue-item-info' },
              el('div', { class: 'catalogue-item-title' }, p.title),
              el(
                'div',
                { class: 'catalogue-item-meta' },
                p.ean ? el('span', {}, `EAN ${p.ean}`) : null,
                p.category ? el('span', {}, p.category) : null,
                el('span', {}, `${priceLabel} · ${stockLabel}`),
              ),
            ),
          );
        }),
      );
      box.hidden = false;
    } catch {
      if (seq === catalogueSeq) {
        box.replaceChildren();
        box.hidden = true;
      }
    }
  }, 240);
});
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
    if ($('catalogue-search')) $('catalogue-search').value = '';
    if ($('catalogue-results')) {
      $('catalogue-results').replaceChildren();
      $('catalogue-results').hidden = true;
    }
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

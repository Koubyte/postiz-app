'use strict';
// Strategy proposes and prepares drafts. Publication stays in the existing review flow.
const strategy = {
  tab: 'watch', data: null, loading: false, signature: {}, lastFetch: 0, refreshDone: null,
  pending: new Set(), requests: new Map(), ideaDrafts: new Map(),
};
const strategyBusy = (entry) => ['queued', 'running', 'preparing'].includes(entry?.status);
const strategyProvider = (provider) => ({facebook: 'Facebook', instagram: 'Instagram', 'instagram-standalone': 'Instagram'}[provider] || provider || '');
const strategyLabels = {
  queued: 'En attente', running: 'Plan en préparation', ready: 'Brouillons demandés', failed: 'À reprendre',
  plan_review: 'Plan proposé', preparing: 'Brouillons en préparation', prepared: 'Brouillon demandé',
};
function strategyError(text = '', transient = false) {
  strategy.fetchError = transient;
  $('strategy-error').textContent = text;
  $('strategy-error').hidden = !text;
}
function strategyStatus(entry, runningLabel) {
  if (!entry) return null;
  const box = el('div', {class: 'strategy-status', role: 'status'});
  if (strategyBusy(entry)) box.append(el('span', {class: 'strategy-progress', 'aria-hidden': 'true'}), el('span', {}, entry.status === 'queued' ? 'En attente de préparation…' : runningLabel));
  else if (entry.generated_at) box.append(el('span', {class: 'hint'}, 'Mis à jour le ' + dateLabel(entry.generated_at)));
  if (entry.error) box.append(el('p', {class: 'notice error'}, entry.error));
  return box;
}
function strategyEmpty(title, text) {
  return el('div', {class: 'strategy-empty'}, el('h3', {}, title), el('p', {}, text));
}
function strategyAction(key, label, primary, callback, disabled = false) {
  const button = el('button', {type: 'button', class: 'button ' + (primary ? 'primary' : 'secondary'), 'data-strategy-action': key, disabled: disabled || strategy.pending.has(key)}, label);
  button.onclick = callback;
  return button;
}
function strategyActionButtons() {
  $('strategy-watch-refresh').disabled = strategy.pending.has('watch') || strategyBusy(strategy.data?.watch);
  $('strategy-performance-refresh').disabled = strategy.pending.has('report') || strategyBusy(strategy.data?.performance);
  $('strategy-campaign-create').disabled = strategy.pending.has('campaign-new');
  document.querySelectorAll('[data-strategy-action]').forEach(button => {
    button.disabled = strategy.pending.has(button.dataset.strategyAction);
  });
}
async function strategyMutation(key, path, body, success) {
  if (strategy.pending.has(key)) return false;
  const fingerprint = JSON.stringify(body);
  let request = strategy.requests.get(key);
  // A lost network response can be retried without creating another job or draft.
  if (!request || request.fingerprint !== fingerprint) {
    request = {fingerprint, id: crypto.randomUUID()};
    strategy.requests.set(key, request);
  }
  strategy.pending.add(key);
  strategyActionButtons();
  strategyError();
  try {
    await api(path, {...body, request_id: request.id});
    strategy.requests.delete(key);
    if (success) success();
    await refreshStrategy(true);
    return true;
  } catch (error) {
    strategyError(error.message);
    return false;
  } finally {
    strategy.pending.delete(key);
    strategyActionButtons();
  }
}
async function strategyOpenItem(id, button) {
  button.disabled = true;
  try { openItem(await api(`/contents/${encodeURIComponent(id)}`)); }
  catch (error) { strategyError(error.message); }
  finally { button.disabled = false; }
}
function strategyReviewButton(item, label) {
  const id = item.item_id || item.id;
  if (id) {
    const button = el('button', {type: 'button', class: 'button secondary'}, label);
    button.onclick = () => strategyOpenItem(id, button);
    return button;
  }
  const url = safeUrl(item.review_url);
  return url ? el('a', {href: url, class: 'button secondary'}, label) : null;
}
function strategySources(sources) {
  if (!Array.isArray(sources) || !sources.length) return null;
  const list = el('ul', {class: 'strategy-sources'});
  for (const source of sources) {
    const url = safeUrl(source.url);
    if (!url) continue;
    let date = '';
    if (source.published_at && !Number.isNaN(new Date(source.published_at).getTime())) date = ' · ' + new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', dateStyle: 'medium'}).format(new Date(source.published_at));
    list.append(el('li', {}, el('a', {href: url, target: '_blank', rel: 'noopener noreferrer'}, source.title || new URL(url).hostname), date));
  }
  return list.childElementCount ? el('details', {class: 'strategy-details'}, el('summary', {}, 'Voir les sources (' + list.childElementCount + ')'), list) : null;
}
function strategyIdea(idea) {
  const card = el('article', {class: 'strategy-card', 'data-strategy-idea': idea.id},
    el('p', {class: 'strategy-kicker'}, kinds[idea.kind] || 'Idée de publication'),
    el('h3', {}, idea.title), el('p', {}, idea.angle));
  if (idea.reason) card.append(el('p', {class: 'muted'}, idea.reason));
  if (idea.product_query) card.append(el('p', {class: 'hint'}, 'Produit : ' + idea.product_query));
  const sources = strategySources(idea.sources);
  if (sources) card.append(sources);
  if (idea.status === 'prepared' || idea.item_id) {
    card.append(el('p', {class: 'hint'}, 'La préparation de ce contenu a été demandée.'));
    const review = strategyReviewButton(idea, 'Voir le brouillon');
    if (review) card.append(review);
    return card;
  }
  const saved = strategy.ideaDrafts.get(idea.id) || {create_blog: false, when: '', open: false};
  const when = el('input', {type: 'datetime-local', value: saved.when, 'aria-label': 'Horaire souhaité en heure de Paris pour ' + idea.title});
  const blog = el('input', {type: 'checkbox', checked: saved.create_blog});
  const options = el('details', {class: 'strategy-details'}, el('summary', {}, 'Options du brouillon'),
    el('label', {}, 'Horaire souhaité · Paris', when, el('span', {class: 'hint'}, 'Facultatif. Un créneau sera proposé si vous laissez ce champ vide.')),
    el('label', {class: 'strategy-check'}, blog, 'Créer aussi un article de blog'),
    el('p', {class: 'hint'}, 'L’article sera rédigé et publié après votre validation du post associé.'));
  options.open = saved.open;
  const save = () => strategy.ideaDrafts.set(idea.id, {create_blog: blog.checked, when: when.value, open: options.open});
  when.oninput = save; blog.onchange = save; options.ontoggle = save;
  const key = 'idea-' + idea.id;
  const prepare = strategyAction(key, 'Préparer ce sujet', true, async () => {
    let scheduled = null;
    try {
      if (!when.checkValidity()) { options.open = true; when.reportValidity(); return; }
      if (when.value) scheduled = parisIso(when.value);
    } catch (error) { options.open = true; strategyError(error.message); return; }
    await strategyMutation(key, `/strategy/ideas/${encodeURIComponent(idea.id)}/prepare`, {create_blog: blog.checked, scheduled_at: scheduled}, () => toast('Préparation lancée. Le brouillon attendra votre validation.'));
  });
  card.append(options, prepare);
  return card;
}
function renderStrategyWatch(entry) {
  const body = $('strategy-watch-body');
  body.replaceChildren();
  if (!entry) {
    body.append(strategyEmpty('La prochaine idée commence ici', 'La veille cherche des nouveautés et des conseils utiles à Planète Laser. Lancez une première recherche ou laissez le prochain passage automatique la préparer.'));
    return;
  }
  body.append(strategyStatus(entry, 'Recherche de sujets et vérification des sources…'));
  if (entry.summary) body.append(el('p', {class: 'strategy-summary'}, entry.summary));
  if (entry.ideas?.length) body.append(el('div', {class: 'strategy-stack'}, ...entry.ideas.map(strategyIdea)));
  else if (!strategyBusy(entry) && !entry.error) body.append(strategyEmpty('Aucune idée retenue pour le moment', 'Une prochaine veille pourra faire apparaître de nouvelles propositions.'));
}
function strategyList(title, values, className = '') {
  if (!Array.isArray(values) || !values.length) return null;
  return el('section', {class: 'strategy-card ' + className}, el('h3', {}, title), el('ul', {class: 'strategy-text-list'}, ...values.map(value => el('li', {}, typeof value === 'string' ? value : value.text || value.recommendation || value.title || ''))));
}
function strategyMetrics(metrics, notes = true) {
  if (!metrics) return null;
  const list = el('dl', {class: 'strategy-metrics'});
  const entries = Array.isArray(metrics) ? metrics : Object.entries(metrics).map(([label, value]) => ({label, value}));
  for (const metric of entries) {
    if (metric.value === null || metric.value === undefined || typeof metric.value === 'object') continue;
    const value = typeof metric.value === 'number' ? new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(metric.value) : String(metric.value);
    list.append(el('div', {}, el('dt', {}, metric.label || metric.name || metric.key || 'Mesure', notes && metric.note ? el('span', {class: 'strategy-metric-note'}, metric.note) : null), el('dd', {}, value + (metric.unit ? ' ' + metric.unit : ''))));
  }
  return list.childElementCount ? list : null;
}
function renderStrategyPerformance(report) {
  const body = $('strategy-performance-body');
  body.replaceChildren();
  if (!report) {
    body.append(strategyEmpty('Votre premier bilan', 'Le bilan rassemble les statistiques disponibles sur Facebook et Instagram et propose des pistes pour les prochains contenus.'));
    return;
  }
  body.append(strategyStatus(report, 'Collecte des statistiques et préparation du bilan…'));
  if (report.period?.label) body.append(el('p', {class: 'hint'}, report.period.label));
  if (report.summary) body.append(el('p', {class: 'strategy-summary'}, report.summary));
  const recommendations = strategyList('À essayer ensuite', report.recommendations);
  if (recommendations) body.append(recommendations);
  if (report.channels?.length) {
    const channels = el('div', {class: 'strategy-channel-grid'});
    for (const channel of report.channels) {
      const card = el('section', {class: 'strategy-card'}, el('h3', {}, channel.name || channel.channel_name || channel.provider || 'Canal'));
      if (channel.provider && channel.provider !== channel.name) card.append(el('p', {class: 'hint'}, strategyProvider(channel.provider)));
      if (channel.period?.label) card.append(el('p', {class: 'hint'}, channel.period.label));
      if (Number.isFinite(channel.published_count)) card.append(el('p', {class: 'hint'}, `${channel.published_count} publication${channel.published_count === 1 ? '' : 's'} sur la semaine du bilan`));
      if (channel.summary) card.append(el('p', {}, channel.summary));
      const metrics = strategyMetrics(channel.metrics);
      if (metrics) card.append(metrics);
      else card.append(el('p', {class: 'hint'}, 'Aucune mesure disponible pour ce canal sur cette période.'));
      if (channel.error) card.append(el('p', {class: 'strategy-warning'}, channel.error));
      if (channel.status === 'disconnected') card.append(el('p', {class: 'strategy-warning'}, 'Compte à reconnecter dans les réglages Postiz.'));
      else if (channel.status === 'partial') card.append(el('p', {class: 'hint'}, 'Certaines mesures ne sont pas disponibles.'));
      channels.append(card);
    }
    body.append(channels);
  }
  if (report.posts?.length) {
    const posts = el('section', {class: 'strategy-card'}, el('h3', {}, 'Les publications analysées'), el('p', {class: 'hint'}, 'Les chiffres ci-dessous sont les cumuls depuis la publication de chaque post, relevés pour ce bilan. Ils ne mesurent pas uniquement la semaine écoulée.'));
    const list = el('div', {class: 'strategy-post-list'});
    for (const post of report.posts) {
      const row = el('article', {}, el('h4', {}, post.title || post.content || 'Publication'), el('p', {class: 'hint'}, [strategyProvider(post.provider), post.channel_name, post.published_at ? dateLabel(post.published_at) : null].filter(Boolean).join(' · ')));
      if (post.summary) row.append(el('p', {}, post.summary));
      const metrics = strategyMetrics(post.metrics, false);
      if (metrics) row.append(metrics);
      else row.append(el('p', {class: 'hint'}, 'Les statistiques de cette publication ne sont pas disponibles.'));
      const url = safeUrl(post.url || post.release_url);
      if (url) row.append(el('a', {href: url, target: '_blank', rel: 'noopener noreferrer'}, 'Voir la publication'));
      list.append(row);
    }
    posts.append(list); body.append(posts);
  }
  const limitations = strategyList('À savoir sur ces résultats', report.limitations, 'strategy-limitations');
  if (limitations) body.append(limitations);
  if (!strategyBusy(report) && !report.error && !report.summary && !report.channels?.length && !report.posts?.length) body.append(strategyEmpty('Pas encore assez de données', 'Le bilan évoluera lorsque les réseaux sociaux renverront des statistiques.'));
}
function strategyCalendarDate(value) {
  if (!value) return '';
  const date = new Date(value + 'T12:00:00Z');
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', dateStyle: 'medium'}).format(date);
}
function strategyCampaign(campaign) {
  const card = el('article', {class: 'strategy-card', 'data-campaign-id': campaign.id},
    el('div', {class: 'strategy-card-heading'}, el('h3', {}, campaign.plan?.title || campaign.brief), el('span', {class: 'badge'}, strategyLabels[campaign.status] || campaign.status)),
    el('p', {class: 'hint'}, `${strategyCalendarDate(campaign.start_date)} – ${strategyCalendarDate(campaign.end_date)} · ${campaign.post_count} posts${campaign.create_blog ? ' + un article' : ''}`));
  if (campaign.plan?.summary) card.append(el('p', {}, campaign.plan.summary));
  else card.append(el('p', {}, campaign.brief));
  if (campaign.error) card.append(el('p', {class: 'notice error'}, campaign.error));
  if (strategyBusy(campaign)) card.append(el('p', {class: 'hint', role: 'status'}, campaign.status === 'preparing' ? 'Les textes et les visuels sont en préparation. Vous pourrez valider chaque brouillon.' : 'Le studio propose les sujets et recherche des créneaux disponibles…'));
  if (campaign.plan?.steps?.length) {
    const steps = el('ol', {class: 'strategy-campaign-steps'});
    for (const step of campaign.plan.steps) {
      steps.append(el('li', {}, el('h4', {}, step.title), el('p', {class: 'hint'}, dateLabel(step.scheduled_at) + (step.create_blog ? ' · Article associé' : '')), el('p', {}, step.brief)));
    }
    if (campaign.status === 'plan_review') card.append(steps);
    else card.append(el('details', {class: 'strategy-details'}, el('summary', {}, 'Voir le plan de campagne'), steps));
  }
  if (campaign.status === 'plan_review') {
    card.append(el('p', {class: 'hint'}, 'Ces créneaux sont proposés. Chaque post sera programmé seulement après votre validation de son texte, de son visuel et de sa date.'));
    card.append(strategyAction('campaign-' + campaign.id, 'Préparer les brouillons', true, () => strategyMutation('campaign-' + campaign.id, `/strategy/campaigns/${encodeURIComponent(campaign.id)}/prepare`, {revision: campaign.revision}, () => toast('Préparation de la campagne lancée. Chaque post restera à valider.'))));
  }
  if (campaign.status === 'failed') card.append(strategyAction('campaign-retry-' + campaign.id, 'Réessayer', false, () => strategyMutation('campaign-retry-' + campaign.id, `/strategy/campaigns/${encodeURIComponent(campaign.id)}/retry`, {revision: campaign.revision}, () => toast('La reprise de la campagne est demandée.'))));
  if (campaign.items?.length) {
    const items = el('div', {class: 'strategy-campaign-items'});
    campaign.items.forEach((item, index) => {
      const title = item.title || campaign.plan?.steps?.[index]?.title || 'Post ' + (index + 1);
      const row = el('div', {}, el('div', {}, el('p', {}, title), badge(item.status), el('p', {class: 'hint'}, item.status === 'managed' ? 'Horaire à consulter dans Postiz' : dateLabel(item.scheduled_at))), strategyReviewButton(item, item.status === 'review' ? 'Relire et valider' : 'Voir le contenu'));
      items.append(row);
    });
    card.append(items);
  }
  return card;
}
function renderStrategyCampaigns(campaigns) {
  $('strategy-campaign-list').replaceChildren(...(campaigns?.length ? campaigns.map(strategyCampaign) : [strategyEmpty('Votre première campagne', 'Un objectif et une période suffisent pour proposer une série cohérente, en plus de votre programme habituel.')]));
}
function setStrategyTab(tab, focus = false) {
  strategy.tab = tab;
  for (const button of document.querySelectorAll('[data-strategy-tab]')) {
    const active = button.dataset.strategyTab === tab;
    button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
    $('strategy-' + button.dataset.strategyTab).hidden = !active;
    if (focus && active) button.focus();
  }
}
async function refreshStrategy(force = false) {
  if (!force && (document.hidden || $('strategy-panel').hidden || strategy.loading)) return;
  if (strategy.loading) { await strategy.refreshDone; return refreshStrategy(force); }
  strategy.loading = true;
  let done;
  strategy.refreshDone = new Promise(resolve => { done = resolve; });
  $('strategy-panel').setAttribute('aria-busy', 'true');
  try {
    const data = await api('/strategy');
    strategy.data = data; strategy.lastFetch = Date.now();
    if (strategy.fetchError) strategyError();
    $('strategy-loading').hidden = true;
    $('strategy-watch-cadence').textContent = data.cadence?.watch || '';
    $('strategy-performance-cadence').textContent = data.cadence?.performance || '';
    for (const [key, render] of [['watch', renderStrategyWatch], ['performance', renderStrategyPerformance], ['campaigns', renderStrategyCampaigns]]) {
      const signature = JSON.stringify(data[key]);
      // Polling must not discard the owner's in-progress input or keyboard focus.
      const editing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || '') && document.activeElement?.closest(key === 'watch' ? '#strategy-watch-body' : key === 'campaigns' ? '#strategy-campaign-list' : '#strategy-performance-body');
      if (signature !== strategy.signature[key] && !editing) {
        strategy.signature[key] = signature; render(data[key]);
      }
    }
    strategyActionButtons();
  } catch (error) {
    strategyError(error.message + (strategy.data ? ' La dernière vue reste affichée.' : ''), true);
    $('strategy-loading').hidden = true;
  } finally {
    strategy.loading = false;
    done();
    $('strategy-panel').setAttribute('aria-busy', 'false');
  }
}
window.refreshStrategy = refreshStrategy;
for (const button of document.querySelectorAll('[data-strategy-tab]')) {
  button.onclick = () => setStrategyTab(button.dataset.strategyTab);
  button.onkeydown = event => {
    const tabs = ['watch', 'performance', 'campaigns'];
    let index = tabs.indexOf(strategy.tab);
    if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    else return;
    event.preventDefault(); setStrategyTab(tabs[index], true);
  };
}
$('strategy-watch-refresh').onclick = () => strategyMutation('watch', '/strategy/watch', {}, () => toast('La veille est lancée. Les idées apparaîtront ici.'));
$('strategy-performance-refresh').onclick = () => strategyMutation('report', '/strategy/report', {}, () => toast('Le bilan est en préparation.'));
const strategyToday = parisInput(new Date().toISOString()).slice(0, 10);
$('strategy-campaign-start').value = strategyToday;
$('strategy-campaign-start').min = strategyToday;
$('strategy-campaign-end').value = new Date(new Date(strategyToday + 'T12:00:00Z').getTime() + 7 * 86400000).toISOString().slice(0, 10);
$('strategy-campaign-end').min = strategyToday;
$('strategy-campaign-start').onchange = () => { $('strategy-campaign-end').min = $('strategy-campaign-start').value || strategyToday; };
$('strategy-campaign-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const brief = $('strategy-campaign-brief').value.trim();
  if (!brief) { strategyError('Décrivez l’objectif de votre campagne.'); $('strategy-campaign-brief').focus(); return; }
  const payload = {brief, start_date: $('strategy-campaign-start').value, end_date: $('strategy-campaign-end').value, post_count: Number($('strategy-campaign-count').value), create_blog: $('strategy-campaign-blog').checked};
  await strategyMutation('campaign-new', '/strategy/campaigns', payload, () => {
    // Keep any newer edits made while the request was in flight.
    if ($('strategy-campaign-brief').value.trim() === brief) $('strategy-campaign-brief').value = '';
    toast('Le plan de campagne est en préparation.');
  });
};
if (location.hash === '#strategie') refreshStrategy();
document.addEventListener('visibilitychange', () => { if (!document.hidden && location.hash === '#strategie') refreshStrategy(); });
setInterval(() => {
  const active = strategyBusy(strategy.data?.watch) || strategyBusy(strategy.data?.performance) || strategy.data?.campaigns?.some(strategyBusy);
  if (Date.now() - strategy.lastFetch > (active ? 5000 : 30000)) refreshStrategy();
}, 6000);

'use strict';
const byId = id => document.getElementById(id);
let connected = false;
let keyCreationPending = false;
let rulesDirty = false;
let rulesPending = false;

async function jsonApi(url, data) {
  const response = await fetch(url, {
    method: data ? 'POST' : 'GET',
    credentials: 'same-origin',
    headers: data ? { 'Content-Type': 'application/json', 'X-Editorial-Action': '1' } : {},
    body: data ? JSON.stringify(data) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || result.detail || 'Connexion indisponible.');
  return result;
}
const connectionApi = data => jsonApi('/editorial/api/agent-connection', data);
const rulesApi = data => jsonApi('/editorial/api/rules', data);
const activityApi = () => jsonApi('/editorial/api/agent-activity');

function fail(error) {
  byId('connection-error').textContent = error.message;
  byId('connection-error').hidden = false;
}

function applyRulesToForm(rules) {
  if (!rules || rulesDirty) return;
  if (byId('rules-custom-instructions')) byId('rules-custom-instructions').value = rules.custom_instructions || '';
  if (byId('rules-default-template')) byId('rules-default-template').value = rules.default_template || 'classic';
  if (byId('rules-signature-note')) byId('rules-signature-note').value = rules.signature_note || '';
  if (byId('rules-weekly-blog-link')) byId('rules-weekly-blog-link').checked = Boolean(rules.weekly_blog_link);
}

const weekStatusLabels = {preparing:'plan en préparation',plan_review:'plan à valider',revising:'sujet en modification',generating:'contenus en création',review:'contenus à relire',failed:'à reprendre'};
async function refreshActivity() {
  const statsBox = byId('activity-stats');
  const listBox = byId('activity-list');
  if (!statsBox || !listBox) return;
  try {
    const data = await activityApi();
    const stats = data.stats || {};
    statsBox.replaceChildren(
      ...[['À relire : ' + (stats.review ?? 0), stats.review > 0 ? 'warn' : ''],
          ['En préparation : ' + (stats.queued ?? 0), ''],
          ['Publiés : ' + (stats.published ?? 0), 'ok'],
          ['Semaine : ' + (weekStatusLabels[stats.week_status] || stats.week_status || 'aucune'), 'accent']].map(([text, cls]) => {
        const pill = document.createElement('span');
        pill.className = 'v2-pill' + (cls ? ' ' + cls : '');
        pill.textContent = text;
        return pill;
      }),
    );
    const events = Array.isArray(data.events) ? data.events : [];
    if (!events.length) {
      const p = document.createElement('p');
      p.className = 'hint';
      p.textContent = 'Aucune activité récente enregistrée.';
      listBox.replaceChildren(p);
      return;
    }
    listBox.replaceChildren(...events.slice(0, 20).map(ev => {
      const row = document.createElement('div');
      row.className = 'connect-activity-row';
      const time = document.createElement('time');
      const d = ev.created ? new Date(ev.created) : null;
      time.textContent = d && !Number.isNaN(d.getTime())
        ? d.toLocaleString('fr-FR', { timeZone: 'Europe/Paris' }) + (ev.actor ? ' · ' + ev.actor : '')
        : (ev.actor || '');
      const msg = document.createElement('span');
      msg.textContent = ev.message || '';
      row.append(time, msg);
      return row;
    }));
  } catch {}
}

async function refresh() {
  const result = await connectionApi();
  connected = result.connected;
  byId('mcp-url').value = result.url;
  byId('bot-instructions').value = result.instructions;
  applyRulesToForm(result.rules);
  byId('connection-state').textContent = result.last_used_at
    ? 'Connecteur utilisé le ' + new Date(result.last_used_at).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' }) + ' (Paris).'
    : connected
      ? 'Clé créée. Ajoutez-la dans Grok Bot pour terminer la connexion.'
      : 'Aucune clé active.';
  byId('rotate-key').textContent = connected ? 'Remplacer la clé de connexion' : 'Créer une clé de connexion';
  ['copy-url', 'copy-instructions', 'rotate-key'].forEach(id => (byId(id).disabled = false));
  byId('revoke-key').disabled = !connected;
  byId('create-agent-key').disabled = keyCreationPending;
  const list = byId('agent-key-list');
  list.replaceChildren();
  for (const key of result.keys || []) {
    const row = document.createElement('p');
    const label = document.createElement('span');
    label.textContent = key.label + ' · accès complet ';
    const revoke = document.createElement('button');
    revoke.type = 'button';
    revoke.className = 'button secondary';
    revoke.textContent = 'Révoquer cette clé';
    revoke.onclick = async () => {
      if (!confirm('Révoquer uniquement la clé de cet agent ?')) return;
      revoke.disabled = true;
      try { await connectionApi({ action: 'revoke_key', id: key.id }); await refresh(); }
      catch (error) { fail(error); revoke.disabled = false; }
    };
    row.append(label, revoke);
    list.append(row);
  }
}

for (const id of ['rules-custom-instructions', 'rules-default-template', 'rules-signature-note', 'rules-weekly-blog-link']) {
  byId(id)?.addEventListener('input', () => {
    rulesDirty = true;
    if (byId('rules-status')) byId('rules-status').textContent = 'Modifications non enregistrées.';
  });
  byId(id)?.addEventListener('change', () => {
    rulesDirty = true;
    if (byId('rules-status')) byId('rules-status').textContent = 'Modifications non enregistrées.';
  });
}

byId('save-rules')?.addEventListener('click', async () => {
  if (rulesPending) return;
  rulesPending = true;
  const btn = byId('save-rules');
  btn.disabled = true;
  byId('connection-error').hidden = true;
  try {
    const updated = await rulesApi({
      custom_instructions: byId('rules-custom-instructions').value,
      default_template: byId('rules-default-template').value,
      signature_note: byId('rules-signature-note').value,
      weekly_blog_link: byId('rules-weekly-blog-link').checked,
    });
    rulesDirty = false;
    applyRulesToForm(updated);
    if (byId('rules-status')) byId('rules-status').textContent = 'Règles enregistrées.';
    await refresh();
  } catch (error) {
    fail(error);
  } finally {
    rulesPending = false;
    btn.disabled = false;
  }
});

for (const [button, input] of [['copy-url', 'mcp-url'], ['copy-key', 'mcp-key'], ['copy-new-key', 'new-mcp-key'], ['copy-instructions', 'bot-instructions']]) {
  byId(button).onclick = async () => {
    try {
      await navigator.clipboard.writeText(byId(input).value);
      const previous = byId(button).textContent;
      byId(button).textContent = 'Copié';
      setTimeout(() => (byId(button).textContent = previous), 1800);
    } catch {
      fail(new Error('Copie automatique indisponible : sélectionnez et copiez le champ.'));
    }
  };
}
byId('rotate-key').onclick = async () => {
  if (connected && !confirm('Remplacer la clé ? Il faudra mettre à jour le connecteur dans Grok Bot.')) return;
  byId('rotate-key').disabled = true;
  byId('connection-error').hidden = true;
  try {
    const result = await connectionApi({ action: 'rotate' });
    byId('mcp-key').value = 'Bearer ' + result.token;
    byId('key-result').hidden = false;
    await refresh();
  } catch (e) { fail(e); } finally { byId('rotate-key').disabled = false; }
};
byId('create-agent-key').onclick = async () => {
  if (keyCreationPending) return;
  keyCreationPending = true;
  byId('create-agent-key').disabled = true;
  byId('connection-error').hidden = true;
  try {
    const result = await connectionApi({ action: 'create_key', label: byId('new-key-label').value });
    byId('new-mcp-key').value = 'Bearer ' + result.token;
    byId('new-key-result').hidden = false;
    await refresh();
  } catch (error) { fail(error); } finally { keyCreationPending = false; byId('create-agent-key').disabled = false; }
};
byId('revoke-key').onclick = async () => {
  if (!confirm('Révoquer l’accès de Grok Bot ?')) return;
  byId('revoke-key').disabled = true;
  try {
    await connectionApi({ action: 'revoke' });
    byId('mcp-key').value = '';
    byId('key-result').hidden = true;
    await refresh();
  } catch (e) { fail(e); byId('revoke-key').disabled = false; }
};
window.addEventListener('pagehide', () => {
  byId('mcp-key').value = '';
  byId('key-result').hidden = true;
  byId('new-mcp-key').value = '';
  byId('new-key-result').hidden = true;
});
refresh().catch(fail);
refreshActivity();
setInterval(() => {
  if (!document.hidden) {
    refresh().catch(fail);
    refreshActivity();
  }
}, 15000);

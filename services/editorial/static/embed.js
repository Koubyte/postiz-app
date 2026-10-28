'use strict';

// The native Postiz layout owns navigation. This document owns only its content.
(() => {
  const namespace = 'postiz-studio';
  const studioPaths = new Set(['/editorial', '/editorial/', '/editorial/connect']);
  const studioLinkPaths = new Set([...studioPaths, '/studio', '/studio/', '/studio/connect', '/studio/connect/']);
  const nativePaths = new Set(['/launches', '/media', '/settings', '/auth/login']);
  const url = new URL(location.href);
  const embedded = url.searchParams.get('embedded') === '1' && window.parent !== window;
  function nativeStudioPath(value) {
    const next = new URL(value, location.href);
    next.searchParams.delete('embedded');
    next.pathname = ['/editorial/connect', '/studio/connect', '/studio/connect/'].includes(next.pathname) ? '/studio/connect' : '/studio';
    return next.pathname + next.search + next.hash;
  }
  if (!embedded) {
    // Keep links from Grok, saved bookmarks and approval emails working.
    if (window.parent === window && studioPaths.has(url.pathname)) location.replace(nativeStudioPath(url.href));
    return;
  }
  document.documentElement.classList.add('postiz-embedded');
  const send = (type, values = {}) => window.parent.postMessage({namespace, type, ...values}, location.origin);
  const reportRoute = () => send('route', {path: nativeStudioPath(location.href)});
  window.postizStudioRouteChanged = reportRoute;

  const themeTokens = new Set([
    '--new-bgColor', '--new-bgColorInner', '--new-bgLineColor', '--new-border',
    '--new-textColor', '--new-textItemBlur', '--new-btn-primary', '--new-btn-simple',
    '--new-btn-text', '--new-box-hover', '--new-boxFocused', '--new-textItemFocused',
  ]);
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== location.origin || event.data?.namespace !== namespace) return;
    const message = event.data;
    if (message.type === 'theme') {
      document.documentElement.dataset.theme = message.theme === 'light' ? 'light' : 'dark';
      for (const [name, value] of Object.entries(message.tokens || {})) {
        if (themeTokens.has(name) && typeof value === 'string' && value.length < 200) document.documentElement.style.setProperty(name, value);
      }
    }
    if (message.type === 'route' && typeof message.path === 'string' && message.path.length < 8192) {
      let next;
      try { next = new URL(message.path, location.origin); } catch { return; }
      if (next.origin !== location.origin || !studioPaths.has(next.pathname)) return;
      next.searchParams.set('embedded', '1');
      // A query change can select a different discussion or review item. Reload
      // so the ordinary authenticated loaders resolve that exact deep link.
      const current = new URL(location.href);
      current.searchParams.sort();
      next.searchParams.sort();
      if (next.pathname !== current.pathname || next.search !== current.search) {
        location.replace(next.pathname + next.search + next.hash);
      } else if (next.hash !== location.hash) {
        const previous = location.href;
        history.replaceState(history.state, '', next.pathname + next.search + next.hash);
        window.dispatchEvent(new HashChangeEvent('hashchange', {oldURL: previous, newURL: location.href}));
      }
    }
    if (message.type === 'action') {
      const menu = document.getElementById('studio-menu');
      if (!menu) return;
      if (message.action === 'new') document.getElementById('chat-new')?.click();
      if (message.action === 'history' || message.action === 'settings') {
        const history = message.action === 'history';
        menu.dataset.mode = message.action;
        document.getElementById('studio-menu-title').textContent = history ? 'Vos discussions' : 'Réglages du studio';
        document.getElementById(history ? 'chat-history-open' : 'studio-menu-open')?.click();
        if (!history) {
          const settings = menu.querySelector('.studio-menu-settings');
          if (settings) settings.open = true;
        }
      }
    }
  });
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || link.hasAttribute('download')) return;
    const next = new URL(link.href, location.href);
    if (next.origin !== location.origin) return;
    const studio = studioLinkPaths.has(next.pathname);
    if (!studio && !nativePaths.has(next.pathname)) return;
    if (link.getAttribute('href') === '#main') {
      event.preventDefault();
      const main = document.getElementById('main');
      if (main) { main.tabIndex = -1; main.focus(); }
      return;
    }
    // The parent owns the history entry. Its route message updates hash-only
    // views in place, retaining the unsent brief and open conversation.
    const path = studio ? nativeStudioPath(next.href) : next.pathname + next.search + next.hash;
    if (link.target === '_blank' || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      if (studio) {
        const original = link.getAttribute('href');
        link.href = path;
        // Let the browser open the native URL, then retain relative anchors for
        // later clicks after the selected conversation has changed.
        const rewritten = link.href;
        setTimeout(() => { if (link.href === rewritten) link.setAttribute('href', original); }, 0);
      }
      return;
    }
    event.preventDefault();
    send('navigate', {path});
  });
  window.addEventListener('hashchange', reportRoute);
  window.addEventListener('popstate', reportRoute);
  document.addEventListener('DOMContentLoaded', () => send('ready', {path: nativeStudioPath(location.href)}));
})();

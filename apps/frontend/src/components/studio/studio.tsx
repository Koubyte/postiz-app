'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { embeddedPath, nativePath, studioPath } from './studio-navigation';
import styles from './studio.module.css';

const namespace = 'postiz-studio';
const tabs = [
  { hash: '#discussion', label: 'Discussion' },
  { hash: '#contenus', label: 'Contenus' },
  { hash: '#semaine', label: 'Semaine' },
  { hash: '#strategie', label: 'Idées' },
];
const themeTokens = [
  '--new-bgColor', '--new-bgColorInner', '--new-bgLineColor', '--new-border',
  '--new-textColor', '--new-textItemBlur', '--new-btn-primary', '--new-btn-simple',
  '--new-btn-text', '--new-box-hover', '--new-boxFocused', '--new-textItemFocused',
  '--new-back-drop', '--new-blockSeparator', '--new-table-header', '--new-table-border',
];

export function Studio({ connection = false }: { connection?: boolean }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const host = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [route, setRoute] = useState(connection ? '/studio/connect' : '/studio#discussion');
  const [frameSrc, setFrameSrc] = useState<string>();
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false);
  const [retry, setRetry] = useState(0);

  const send = useCallback((message: Record<string, unknown>) => {
    frame.current?.contentWindow?.postMessage({ namespace, ...message }, window.location.origin);
  }, []);

  const sendTheme = useCallback(() => {
    const computed = getComputedStyle(host.current || document.body);
    send({
      type: 'theme',
      theme: document.body.classList.contains('light') ? 'light' : 'dark',
      tokens: Object.fromEntries(themeTokens.map(name => [name, computed.getPropertyValue(name).trim()])),
      fontFamily: computed.fontFamily,
    });
  }, [send]);

  const syncRoute = useCallback(() => {
    const path = studioPath(window.location.pathname + window.location.search + window.location.hash, window.location.origin);
    if (!path) return;
    setRoute(path);
    send({ type: 'route', path: embeddedPath(path, window.location.origin) });
  }, [send]);

  const navigate = useCallback((path: string, fromFrame = false) => {
    const normalized = studioPath(path, window.location.origin);
    if (!normalized) return;
    const target = new URL(normalized, window.location.origin);
    if (target.pathname !== window.location.pathname.replace(/\/$/, '')) {
      router.push(normalized);
      return;
    }
    const current = studioPath(window.location.pathname + window.location.search + window.location.hash, window.location.origin);
    if (current !== normalized) window.history.pushState(null, '', normalized);
    setRoute(normalized);
    if (!fromFrame) send({ type: 'route', path: embeddedPath(normalized, window.location.origin) });
  }, [router, send]);

  useEffect(() => {
    setReady(false);
    setSlow(false);
    setFrameSrc(embeddedPath(window.location.pathname + window.location.search + window.location.hash, window.location.origin));
    syncRoute();
  }, [connection, syncRoute]);

  // Next navigation, browser back/forward and hash links all update the same frame.
  useEffect(() => { syncRoute(); }, [searchParams, syncRoute]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      const message = event.data;
      if (!message || typeof message !== 'object' || message.namespace !== namespace) return;
      if (message.type === 'ready') {
        setReady(true);
        setSlow(false);
        sendTheme();
        syncRoute();
      } else if (message.type === 'route') {
        const path = studioPath(message.path, window.location.origin);
        if (path) navigate(path, true);
      } else if (message.type === 'navigate') {
        const studio = studioPath(message.path, window.location.origin);
        if (studio) { navigate(studio); return; }
        const path = nativePath(message.path, window.location.origin);
        if (path) router.push(path);
      }
    };
    window.addEventListener('message', receive);
    window.addEventListener('popstate', syncRoute);
    window.addEventListener('hashchange', syncRoute);
    const observer = new MutationObserver(sendTheme);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => {
      window.removeEventListener('message', receive);
      window.removeEventListener('popstate', syncRoute);
      window.removeEventListener('hashchange', syncRoute);
      observer.disconnect();
    };
  }, [navigate, router, sendTheme, syncRoute]);

  useEffect(() => {
    if (ready) return;
    const timeout = window.setTimeout(() => setSlow(true), 12000);
    return () => window.clearTimeout(timeout);
  }, [ready, frameSrc, retry]);

  // Let the composer stay above the phone keyboard, without a second page scrollbar.
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () => document.documentElement.style.setProperty('--studio-viewport-height', `${viewport?.height || window.innerHeight}px`);
    resize();
    viewport?.addEventListener('resize', resize);
    window.addEventListener('resize', resize);
    return () => {
      viewport?.removeEventListener('resize', resize);
      window.removeEventListener('resize', resize);
      document.documentElement.style.removeProperty('--studio-viewport-height');
    };
  }, []);

  const query = route.split('#')[0].split('?')[1];
  const active = connection ? '' : route.split('#')[1] || 'discussion';

  return (
    <div ref={host} className={styles.studio}>
      <div className={styles.toolbar}>
        <nav className={styles.tabs} aria-label="Studio IA">
          {tabs.map(tab => {
            const href = `/studio${query ? `?${query}` : ''}${tab.hash}`;
            return <Link key={tab.hash} className={styles.tab} href={href} scroll={false}
              aria-current={`#${active}` === tab.hash ? 'page' : undefined}
              onNavigate={event => { event.preventDefault(); navigate(href); }}>
              {tab.label}
            </Link>;
          })}
        </nav>
        <div className={styles.actions}>
          {!connection && active === 'discussion' && <button type="button" className={styles.action}
            aria-label="Historique des discussions" title="Historique des discussions" disabled={!ready}
            onClick={() => send({ type: 'action', action: 'history' })}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 11a9 9 0 1 1 2.7 7M3 4v7h7M12 7v5l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>}
          {!connection && <button type="button" className={styles.action}
            aria-label="Réglages du studio" title="Réglages du studio" disabled={!ready}
            onClick={() => send({ type: 'action', action: 'settings' })}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M4 17h16M8 4v6M16 14v6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          </button>}
        </div>
      </div>
      <div className={styles.content}>
        {frameSrc && <iframe key={retry} ref={frame} src={frameSrc} className={styles.frame}
          title={connection ? 'Connexion de Grok Bot au Studio IA' : 'Contenus du Studio IA'}
          allow="microphone; clipboard-write" referrerPolicy="same-origin"
          onLoad={() => { sendTheme(); syncRoute(); }} />}
        {!ready && <div className={styles.loading} role="status">
          <p>{slow ? 'Le studio met plus de temps à répondre.' : 'Chargement du studio…'}</p>
          {slow && <button type="button" className={styles.retry} onClick={() => {
            setSlow(false);
            setFrameSrc(embeddedPath(route, window.location.origin));
            setRetry(value => value + 1);
          }}>Réessayer</button>}
        </div>}
      </div>
    </div>
  );
}

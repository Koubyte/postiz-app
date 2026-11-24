const studioPaths = new Set(['/studio', '/studio/', '/studio/connect', '/studio/connect/']);
const views = new Set(['#discussion', '#contenus', '#semaine', '#strategie']);
const nativePaths = new Set(['/launches', '/media', '/settings', '/auth/login']);

/** Keep frame messages within the studio, even when they contain a URL-like value. */
export function studioPath(value: unknown, origin: string): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || !studioPaths.has(url.pathname)) return null;
    const connection = url.pathname.replace(/\/$/, '') === '/studio/connect';
    url.searchParams.delete('embedded');
    url.searchParams.sort();
    return `${connection ? '/studio/connect' : '/studio'}${url.search}${connection ? '' : views.has(url.hash) ? url.hash : '#discussion'}`;
  } catch {
    return null;
  }
}

export function embeddedPath(value: string, origin: string): string {
  const safe = studioPath(value, origin) || '/studio#discussion';
  const url = new URL(safe, origin);
  url.searchParams.set('embedded', '1');
  return `${url.pathname === '/studio/connect' ? '/editorial/connect' : '/editorial/'}${url.search}${url.hash}`;
}

/** Native page links may leave the frame, but never navigate to arbitrary destinations. */
export function nativePath(value: unknown, origin: string): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null;
  try {
    const url = new URL(value, origin);
    return url.origin === origin && nativePaths.has(url.pathname)
      ? `${url.pathname}${url.search}${url.hash}`
      : null;
  } catch {
    return null;
  }
}

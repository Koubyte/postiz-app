import { BridgeError } from './protocol.mjs';

// A bounded FIFO absorbs Postiz's Promise.all bursts without spawning one
// Codex process per post. Images have a separate slot from text requests.
export function createLimiter(capacity, maxQueued = 8, waitMs = 120000) {
  let active = 0;
  const queue = [];
  function release() {
    active--;
    const next = queue.shift();
    if (next) { next.cleanup(); active++; next.resolve(release); }
  }
  return function acquire(signal) {
    if (signal?.aborted) return Promise.reject(new BridgeError(499, 'cancelled', 'Request cancelled.'));
    if (active < capacity) { active++; return Promise.resolve(release); }
    if (queue.length >= maxQueued) return Promise.reject(new BridgeError(429, 'busy', 'Codex is busy. Please retry shortly.'));
    return new Promise((resolve, reject) => {
      const entry = { resolve, cleanup: () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); } };
      const remove = error => {
        const i = queue.indexOf(entry); if (i < 0) return;
        queue.splice(i, 1); entry.cleanup(); reject(error);
      };
      const abort = () => remove(new BridgeError(499, 'cancelled', 'Request cancelled.'));
      const timer = setTimeout(() => remove(new BridgeError(429, 'busy', 'Codex queue timed out. Please retry.')), waitMs);
      signal?.addEventListener('abort', abort, { once: true });
      queue.push(entry);
    });
  };
}

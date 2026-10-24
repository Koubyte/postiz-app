import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BridgeError } from './protocol.mjs';

export function webSearchMode(config = process.env) {
  const mode = config.CODEX_WEB_SEARCH || 'live';
  if (!['live', 'cached', 'disabled'].includes(mode)) {
    throw new BridgeError(503, 'invalid_configuration', 'Invalid Codex web search configuration.');
  }
  return mode;
}

export function codexArgs(directory, model, searchMode = 'live') {
  const mode = webSearchMode({ CODEX_WEB_SEARCH: searchMode });
  return ['exec', '--skip-git-repo-check', '--ephemeral', '--sandbox', 'read-only',
    '--ignore-user-config', '--ignore-rules', '--json', '--color', 'never',
    '-c', 'approval_policy="never"',
    '-c', 'forced_login_method="chatgpt"', '-c', 'cli_auth_credentials_store="file"',
    '-c', 'features.shell_tool=false', '-c', 'features.unified_exec=false',
    '-c', 'features.apps=false', '-c', 'features.plugins=false',
    '-c', 'features.multi_agent=false', '-c', 'features.image_generation=false',
    '-c', 'features.view_image=false', '-c', `web_search="${mode}"`,
    '--output-schema', join(directory, 'schema.json'),
    '--output-last-message', join(directory, 'result.json'),
    ...(model ? ['--model', model] : []), '-'];
}

export async function runCodex({ prompt, schema, signal }, config = process.env) {
  const searchMode = webSearchMode(config);
  const directory = await mkdtemp(join(tmpdir(), 'postiz-codex-'));
  try {
    await writeFile(join(directory, 'schema.json'), JSON.stringify(schema), { mode: 0o600 });
    return await new Promise((resolve, reject) => {
      let buffer = '', usage = {}, failed = false, bytes = 0, timedOut = false;
      // Never inherit Postiz secrets, API keys, bridge token or arbitrary Codex config.
      const child = spawn(config.CODEX_BIN || '/bridge/node_modules/.bin/codex', codexArgs(directory, config.CODEX_MODEL, searchMode), {
        cwd: directory, detached: true, stdio: ['pipe', 'pipe', 'ignore'],
        env: { PATH: config.PATH || '/usr/local/bin:/usr/bin:/bin', HOME: '/home/node', CODEX_HOME: config.CODEX_HOME || '/home/node/.codex' }
      });
      const stop = () => { if (child.pid) { try { process.kill(-child.pid, 'SIGKILL'); } catch {} } };
      const timeout = setTimeout(() => { timedOut = true; stop(); }, Number(config.CODEX_TIMEOUT_MS || 180000));
      signal?.addEventListener('abort', stop, { once: true });
      if (signal?.aborted) stop();
      const cleanup = () => { clearTimeout(timeout); signal?.removeEventListener('abort', stop); };
      child.on('error', () => { cleanup(); reject(new BridgeError(503, 'codex_unavailable', 'Codex could not start.')); });
      child.stdout.on('data', data => {
        bytes += data.length;
        if (bytes > 4 * 1024 * 1024) { failed = true; stop(); return; }
        buffer += data.toString();
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
          try {
            const event = JSON.parse(line);
            if (event.type === 'turn.completed') usage = event.usage ?? {};
            if (event.type === 'turn.failed' || event.type === 'error') failed = true;
          } catch {}
        }
      });
      child.stdin.on('error', () => {});
      child.stdin.end(prompt);
      child.on('close', async code => {
        cleanup();
        if (timedOut) return reject(new BridgeError(504, 'codex_timeout', 'Codex timed out. Please retry.'));
        if (signal?.aborted) return reject(new BridgeError(499, 'cancelled', 'Request cancelled.'));
        if (code !== 0 || failed) return reject(new BridgeError(503, 'codex_unavailable', 'Codex is unavailable. Check the server login status or account limits.'));
        try { resolve({ output: await readFile(join(directory, 'result.json'), 'utf8'), usage }); }
        catch { reject(new BridgeError(502, 'empty_codex_response', 'Codex did not return a response.')); }
      });
    });
  } finally { await rm(directory, { recursive: true, force: true }); }
}

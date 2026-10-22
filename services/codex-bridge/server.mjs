import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { BridgeError, prepare, streamChunks } from './protocol.mjs';
import { runCodex } from './runner.mjs';
import { prepareImage, runImage } from './images.mjs';
import { createLimiter } from './limiter.mjs';

export function createBridge({ token, runner = runCodex, imageRunner = runImage, maxActive = 2, maxQueued = 8 } = {}) {
  if (!token || token.length < 32) throw new Error('CODEX_BRIDGE_TOKEN must contain at least 32 characters.');
  const acquireText = createLimiter(maxActive, maxQueued);
  const acquireImage = createLimiter(1, maxQueued);
  const expected = Buffer.from(`Bearer ${token}`);
  const server = createServer(async (req, res) => {
    const json = (status, value) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
    if (req.method === 'GET' && req.url === '/health') return json(200, { status: 'ok' });
    const auth = Buffer.from(req.headers.authorization || '');
    if (auth.length !== expected.length || !timingSafeEqual(auth, expected)) return json(401, { error: { message: 'Unauthorized', type: 'authentication_error' } });
    const isImage = req.url === '/v1/images/generations';
    if (req.method !== 'POST' || (!isImage && req.url !== '/v1/chat/completions')) return json(404, { error: { message: 'Supported endpoints: chat/completions and images/generations.', type: 'unsupported_endpoint' } });

    const controller = new AbortController();
    res.on('close', () => { if (!res.writableEnded) controller.abort(); });
    let keepalive, release;
    try {
      let size = 0, chunks = [];
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 1024 * 1024) throw new BridgeError(413, 'request_too_large', 'Request exceeds 1 MiB.');
        chunks.push(chunk);
      }
      let body;
      try { body = JSON.parse(Buffer.concat(chunks).toString()); }
      catch { throw new BridgeError(400, 'invalid_json', 'Invalid JSON request.'); }
      if (isImage) {
        const prompt = prepareImage(body);
        release = await acquireImage(controller.signal);
        const result = await imageRunner({ prompt, signal: controller.signal });
        if (!controller.signal.aborted) json(200, result);
        return;
      }
      const plan = prepare(body);
      if (body.stream) {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' });
        res.write(': generating\n\n');
        keepalive = setInterval(() => res.write(': waiting\n\n'), 10000);
      }
      release = await acquireText(controller.signal);
      const result = await runner({ prompt: plan.prompt, schema: plan.schema, signal: controller.signal });
      if (controller.signal.aborted) return;
      const completion = plan.decode(result.output, result.usage);
      if (!body.stream) return json(200, completion);
      for (const chunk of streamChunks(completion, body.stream_options?.include_usage)) res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      res.end('data: [DONE]\n\n');
    } catch (error) {
      if (controller.signal.aborted) return;
      const known = error instanceof BridgeError;
      const payload = { error: { message: known ? error.message : 'Codex bridge request failed.', type: known ? error.code : 'server_error' } };
      // Do not log request content, generated text, subprocess output or credentials.
      if (res.headersSent) res.end(`data: ${JSON.stringify(payload)}\n\ndata: [DONE]\n\n`);
      else json(known ? error.status : 500, payload);
    } finally { clearInterval(keepalive); release?.(); }
  });
  server.requestTimeout = 360000;
  server.headersTimeout = 15000;
  return server;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  createBridge({ token: process.env.CODEX_BRIDGE_TOKEN }).listen(8787, '0.0.0.0', () => console.log('Postiz Codex bridge listening on 8787'));
}

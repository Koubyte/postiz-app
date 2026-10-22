import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import OpenAI from 'openai';
import { prepare } from './protocol.mjs';
import { createBridge } from './server.mjs';
import { codexArgs } from './runner.mjs';
import { prepareImage, imageResponse } from './images.mjs';

const messages = [{ role: 'user', content: 'Write a short French post.' }];
const output = (content, tool_calls = []) => JSON.stringify({ choices: [{ content, tool_calls }] });
const tool = { type: 'function', function: { name: 'listPosts', parameters: { type: 'object', properties: { limit: { type: 'integer', minimum: 1 } }, required: ['limit'], additionalProperties: false } } };
const token = 'test-secret-'.repeat(4);
async function fixture(t, options = {}) {
  const server = createBridge({ token, ...options });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const baseURL = `http://127.0.0.1:${server.address().port}/v1`;
  return { baseURL, client: new OpenAI({ baseURL, apiKey: token, maxRetries: 0 }) };
}

test('plain text works through the real OpenAI SDK', async t => {
  const { client } = await fixture(t, { runner: async () => ({ output: output('Bonjour !'), usage: { input_tokens: 10, output_tokens: 3 } }) });
  const result = await client.chat.completions.create({ model: 'codex', messages });
  assert.equal(result.choices[0].message.content, 'Bonjour !');
  assert.equal(result.usage.total_tokens, 13);
});

test('structured JSON is parsed by the OpenAI SDK and validated by the bridge', async t => {
  const schema = { type: 'object', properties: { post: { type: 'string' } }, required: ['post'], additionalProperties: false };
  const { client } = await fixture(t, { runner: async () => ({ output: output('{"post":"Bonjour"}') }) });
  const r = await client.chat.completions.parse({ model: 'codex', messages, response_format: { type: 'json_schema', json_schema: { name: 'post', strict: true, schema } } });
  assert.deepEqual(r.choices[0].message.parsed, { post: 'Bonjour' });
  assert.throws(() => prepare({ messages, response_format: { type: 'json_schema', json_schema: { schema } } }).decode(output('{"post":4}')), /invalid response/);
});

test('tool calls stream with ids, arguments and usage through the SDK', async t => {
  const { client } = await fixture(t, { runner: async () => ({ output: output(null, [{ name: 'listPosts', arguments: '{"limit":2}' }]) }) });
  const stream = await client.chat.completions.create({ model: 'codex', messages, tools: [tool], tool_choice: 'required', stream: true, stream_options: { include_usage: true } });
  const events = []; for await (const chunk of stream) events.push(chunk);
  const call = events.find(e => e.choices[0]?.delta.tool_calls)?.choices[0].delta.tool_calls[0];
  assert.equal(call.function.name, 'listPosts'); assert.equal(call.function.arguments, '{"limit":2}'); assert.ok(call.id);
  assert.ok(events.some(e => e.choices[0]?.finish_reason === 'tool_calls'));
  assert.deepEqual(events.at(-1).choices, []);
});

test('unknown tools, wrong arguments and prohibited tool choices are rejected', () => {
  const plan = prepare({ messages, tools: [tool], tool_choice: 'required' });
  assert.throws(() => plan.decode(output(null, [{ name: 'shell', arguments: '{}' }])));
  assert.throws(() => plan.decode(output(null, [{ name: 'listPosts', arguments: '{"limit":"all"}' }])));
  assert.throws(() => plan.decode(output('No call')));
  assert.throws(() => prepare({ messages, tools: [tool], tool_choice: 'none' }).decode(output(null, [{ name: 'listPosts', arguments: '{"limit":1}' }])));
});

test('multiple alternatives remain separate, missing alternatives are rejected', () => {
  const plan = prepare({ messages, n: 2 });
  assert.equal(plan.decode(JSON.stringify({ choices: [{ content: 'A', tool_calls: [] }, { content: 'B', tool_calls: [] }] })).choices.length, 2);
  assert.throws(() => plan.decode(output('A')));
});

test('text endpoint rejects image inputs and malformed requests', () => {
  for (const body of [{}, { messages, n: 20 }, { messages, tools: 'bad' }, { messages, stream: 'true' }, { messages: [{ role: 'user', content: [{ type: 'image_url', image_url: { url: 'https://example.com' } }] }] }]) assert.throws(() => prepare(body));
});

test('authentication is required and never reaches the runner', async t => {
  let called = false;
  const { baseURL } = await fixture(t, { runner: async () => { called = true; } });
  const response = await fetch(baseURL + '/chat/completions', { method: 'POST', body: JSON.stringify({ messages }) });
  assert.equal(response.status, 401); assert.equal(called, false);
});

test('raw runner errors and credentials are not returned', async t => {
  const { client } = await fixture(t, { runner: async () => { throw new Error('oauth-secret-token'); } });
  await assert.rejects(client.chat.completions.create({ model: 'codex', messages }), e => e.status === 500 && !e.message.includes('oauth-secret-token'));
});

test('stream errors propagate to the SDK instead of succeeding silently', async t => {
  const { client } = await fixture(t, { runner: async () => { throw new Error('private failure'); } });
  const stream = await client.chat.completions.create({ model: 'codex', messages, stream: true });
  await assert.rejects(async () => { for await (const chunk of stream) {} }, /bridge request failed/);
});

test('concurrency limit rejects excess work', async t => {
  let release, started;
  const start = new Promise(r => { started = r; });
  const { client } = await fixture(t, { maxActive: 1, runner: async () => { started(); await new Promise(r => { release = r; }); return { output: output('ok') }; } });
  const first = client.chat.completions.create({ model: 'codex', messages }).then(r => r);
  await start;
  await assert.rejects(client.chat.completions.create({ model: 'codex', messages }), e => e.status === 429);
  release(); await first;
});

test('disconnect cancels the underlying work', async t => {
  let cancelled;
  const wasCancelled = new Promise(r => { cancelled = r; });
  const { baseURL } = await fixture(t, { runner: ({ signal }) => new Promise((resolve, reject) => { signal.addEventListener('abort', () => { cancelled(); reject(new Error('cancelled')); }); }) });
  const controller = new AbortController();
  const response = await fetch(baseURL + '/chat/completions', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ messages, stream: true }), signal: controller.signal });
  assert.equal(response.status, 200); controller.abort();
  await Promise.race([wasCancelled, new Promise((_, reject) => setTimeout(() => reject(new Error('not cancelled')), 2000).unref())]);
});

test('Codex native text tools and API authentication are disabled', () => {
  const args = codexArgs('/tmp/test', undefined);
  assert.ok(args.includes('forced_login_method="chatgpt"'));
  assert.ok(args.includes('features.shell_tool=false'));
  assert.ok(args.includes('features.image_generation=false'));
  assert.ok(args.includes('--ignore-user-config'));
  assert.ok(!args.includes('--dangerously-bypass-approvals-and-sandbox'));
});

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==';
test('native Codex images reach the OpenAI image client as base64', async t => {
  const { client } = await fixture(t, { imageRunner: async () => imageResponse({ status: 'completed', result: png }) });
  const result = await client.images.generate({ model: 'codex', prompt: 'A blue square', size: '1024x1024' });
  assert.equal(result.data[0].b64_json, png);
});

test('images reject missing prompts, batches, URL responses, errors and non-images', () => {
  for (const body of [{}, { prompt: 'x', n: 2 }, { prompt: 'x', response_format: 'url' }]) assert.throws(() => prepareImage(body));
  assert.throws(() => imageResponse({ status: 'failed', result: png }));
  assert.throws(() => imageResponse({ status: 'completed', result: Buffer.from('secret text').toString('base64') }));
});

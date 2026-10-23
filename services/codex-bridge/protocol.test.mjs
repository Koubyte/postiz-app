import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import OpenAI from 'openai';
import { prepare } from './protocol.mjs';
import { createBridge } from './server.mjs';
import { codexArgs, runCodex, webSearchMode } from './runner.mjs';
import { mkdtemp, writeFile, readFile, stat, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { prepareImage, prepareReferenceImage, imageResponse, runImage, MAX_REFERENCE_BYTES } from './images.mjs';

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
  const { client } = await fixture(t, { maxActive: 1, maxQueued: 0, runner: async () => { started(); await new Promise(r => { release = r; }); return { output: output('ok') }; } });
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

test('only native web research is enabled for text; local tools and API authentication remain disabled', () => {
  const args = codexArgs('/tmp/test', undefined);
  assert.ok(args.includes('forced_login_method="chatgpt"'));
  assert.ok(args.includes('features.shell_tool=false'));
  assert.ok(args.includes('features.image_generation=false'));
  assert.ok(args.includes('features.apps=false'));
  assert.ok(args.includes('features.plugins=false'));
  assert.ok(args.includes('features.multi_agent=false'));
  assert.ok(args.includes('approval_policy="never"'));
  assert.ok(args.includes('web_search="live"'));
  assert.ok(args.includes('--ignore-user-config'));
  assert.ok(!args.includes('--dangerously-bypass-approvals-and-sandbox'));
});

test('web research is server-controlled and invalid configuration fails closed', () => {
  assert.equal(webSearchMode({}), 'live');
  assert.ok(codexArgs('/tmp/test', undefined, 'disabled').includes('web_search="disabled"'));
  assert.throws(() => webSearchMode({ CODEX_WEB_SEARCH: 'live;secret-value' }), e => e.code === 'invalid_configuration' && !e.message.includes('secret-value'));
  const plan = prepare({ messages, web_search: 'disabled' });
  assert.match(plan.prompt, /native read-only web search/);
  assert.doesNotMatch(prepare({ messages }, { webSearch: 'disabled' }).prompt, /You may use ONLY/);
});

test('sourced research and uncertainty survive structured responses without changing the schema', async t => {
  const research = { product: 'Example Model', eanVerified: false, evidence: 'The model matches; this source does not confirm the supplied EAN.', sources: [{ url: 'https://example.com/product', title: 'Manufacturer specifications' }] };
  const schema = { type: 'object', additionalProperties: false, required: ['product', 'eanVerified', 'evidence', 'sources'], properties: { product: { type: 'string' }, eanVerified: { type: 'boolean' }, evidence: { type: 'string' }, sources: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['url', 'title'], properties: { url: { type: 'string' }, title: { type: 'string' } } } } } };
  const { client } = await fixture(t, { runner: async () => ({ output: output(JSON.stringify(research)) }) });
  const result = await client.chat.completions.parse({ model: 'codex', messages, response_format: { type: 'json_schema', json_schema: { name: 'research', strict: true, schema } } });
  assert.deepEqual(result.choices[0].message.parsed, research);
});

test('sources stay in assistant content alongside function calls and out of publication arguments', async t => {
  const evidence = 'Model confirmed: [Manufacturer](https://example.com/product). EAN not confirmed.';
  const { client } = await fixture(t, { runner: async () => ({ output: output(evidence, [{ name: 'listPosts', arguments: '{"limit":2}' }]) }) });
  const stream = await client.chat.completions.create({ model: 'codex', messages, tools: [tool], stream: true });
  const chunks = []; for await (const chunk of stream) chunks.push(chunk);
  const delta = chunks.find(c => c.choices[0]?.delta.tool_calls).choices[0].delta;
  assert.equal(delta.content, evidence);
  assert.equal(delta.tool_calls[0].function.arguments, '{"limit":2}');
});

test('text subprocess enables hosted search without inheriting credentials or arbitrary environment', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'postiz-runner-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const executable = join(directory, 'fake-codex');
  await writeFile(executable, `#!${process.execPath}
import fs from 'node:fs';
const args = process.argv.slice(2);
const resultPath = args[args.indexOf('--output-last-message') + 1];
const result = { args, apiKeyInherited: !!process.env.OPENAI_API_KEY, bridgeTokenInherited: !!process.env.CODEX_BRIDGE_TOKEN, customInherited: !!process.env.PRIVATE_CUSTOM };
process.stdin.resume();
process.stdin.on('end', () => {
  console.log(JSON.stringify({type:'item.completed',item:{type:'web_search',id:'search_1'}}));
  console.log(JSON.stringify({type:'turn.completed',usage:{input_tokens:10,output_tokens:5}}));
  fs.writeFileSync(resultPath, JSON.stringify(result));
});
`, { mode: 0o700 });
  const result = await runCodex({ prompt: 'Research this product', schema: { type: 'object' } }, { CODEX_BIN: executable, CODEX_HOME: directory, CODEX_WEB_SEARCH: 'live', OPENAI_API_KEY: 'must-not-pass', CODEX_BRIDGE_TOKEN: 'must-not-pass', PRIVATE_CUSTOM: 'must-not-pass' });
  const actual = JSON.parse(result.output);
  assert.ok(actual.args.includes('web_search="live"'));
  assert.equal(actual.apiKeyInherited, false);
  assert.equal(actual.bridgeTokenInherited, false);
  assert.equal(actual.customInherited, false);
  assert.deepEqual(result.usage, { input_tokens: 10, output_tokens: 5 });
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

test('one reference photo is validated by encoding, MIME, signature and decoded size', () => {
  const reference = prepareReferenceImage({ mime_type: 'image/png', b64_json: png });
  assert.equal(reference.extension, 'png');
  assert.equal(reference.bytes.toString('base64'), png);
  assert.equal(reference.sha256, createHash('sha256').update(Buffer.from(png, 'base64')).digest('hex'));
  const webp = 'UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA';
  assert.equal(prepareReferenceImage({ mime_type: 'image/webp', b64_json: webp }).extension, 'webp');
  assert.equal(prepareReferenceImage(undefined), undefined);
  for (const value of [null, [], [{ mime_type: 'image/png', b64_json: png }], {}, { mime_type: 'image/jpeg', b64_json: png }, { mime_type: 'image/svg+xml', b64_json: png }, { mime_type: 'image/png', b64_json: 'data:image/png;base64,' + png }, { mime_type: 'image/png', b64_json: png + '\n' }, { mime_type: 'image/png', b64_json: '!!!!' }, { mime_type: 'image/png', b64_json: png, path: '/private/file' }, { mime_type: 'image/webp', b64_json: Buffer.from('RIFF----WEBPwrong').toString('base64') }]) {
    assert.throws(() => prepareImage({ prompt: 'Scene', reference_image: value }), e => e.code === 'invalid_reference_image');
  }
  assert.throws(() => prepareReferenceImage({ mime_type: 'image/png', b64_json: Buffer.alloc(MAX_REFERENCE_BYTES + 1).toString('base64') }), e => e.status === 413);
});

test('image endpoint forwards a validated reference while invalid inputs never reach the runner', async t => {
  let calls = 0;
  const { baseURL } = await fixture(t, { imageRunner: async ({ prompt, referenceImage }) => {
    calls++;
    assert.equal(referenceImage.bytes.toString('base64'), png);
    assert.match(prompt, /actual image input/);
    assert.match(prompt, /Do not perform a cutout/);
    return imageResponse({ status: 'completed', result: png });
  } });
  const post = reference_image => fetch(baseURL + '/images/generations', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: 'A faithful product in a studio', reference_image }) });
  assert.equal((await post({ mime_type: 'image/png', b64_json: png })).status, 200);
  assert.equal((await post({ mime_type: 'image/jpeg', b64_json: png })).status, 400);
  assert.equal(calls, 1);
});

test('app-server receives the reference as a private localImage, returns its hash and cleans it', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'postiz-image-rpc-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const capturePath = join(directory, 'capture.json');
  const executable = join(directory, 'fake-codex');
  await writeFile(executable, `#!${process.execPath}
import fs from 'node:fs';
import readline from 'node:readline';
const lines=readline.createInterface({input:process.stdin});
const reply=(id,result)=>console.log(JSON.stringify({id,result}));
lines.on('line',line=>{
  const call=JSON.parse(line);
  if(call.method==='initialize')reply(call.id,{});
  if(call.method==='thread/start')reply(call.id,{thread:{id:'image-thread'}});
  if(call.method==='turn/start'){
    const ref=call.params.input.find(part=>part.type==='localImage');
    fs.writeFileSync(${JSON.stringify(capturePath)},JSON.stringify({input:call.params.input,args:process.argv.slice(2),reference:ref?fs.readFileSync(ref.path).toString('base64'):null,mode:ref?(fs.statSync(ref.path).mode&0o777):null,apiKeyInherited:!!process.env.OPENAI_API_KEY}));
    reply(call.id,{turn:{id:'image-turn'}});
    console.log(JSON.stringify({method:'item/completed',params:{item:{type:'imageGeneration',status:'completed',result:${JSON.stringify(png)}}}}));
  }
});
`, { mode: 0o700 });
  const referenceImage = prepareReferenceImage({ mime_type: 'image/png', b64_json: png });
  const result = await runImage({ prompt: prepareImage({ prompt: 'Product in a beautiful studio', reference_image: { mime_type: 'image/png', b64_json: png } }), referenceImage }, { CODEX_BIN: executable, CODEX_HOME: directory, OPENAI_API_KEY: 'must-not-pass' });
  const actual = JSON.parse(await readFile(capturePath, 'utf8'));
  const ref = actual.input.find(part => part.type === 'localImage');
  assert.equal(actual.reference, png);
  assert.equal(actual.mode, 0o600);
  assert.equal(actual.apiKeyInherited, false);
  assert.equal(result.reference_image_sha256, referenceImage.sha256);
  assert.equal(result.data[0].b64_json, png);
  assert.match(actual.input[0].text, /referenced_image_paths/);
  assert.ok(actual.input[0].text.includes(JSON.stringify([ref.path])));
  for (const disabled of ['features.shell_tool=false', 'features.unified_exec=false', 'features.multi_agent=false', 'features.apps=false', 'features.plugins=false', 'features.view_image=false', 'web_search="disabled"']) assert.ok(actual.args.includes(disabled));
  await assert.rejects(stat(ref.path), e => e.code === 'ENOENT');
  const withoutReference = await runImage({ prompt: prepareImage({ prompt: 'Empty studio' }) }, { CODEX_BIN: executable, CODEX_HOME: directory });
  assert.equal(Object.hasOwn(withoutReference, 'reference_image_sha256'), false);
  assert.equal(JSON.parse(await readFile(capturePath, 'utf8')).input.length, 1);
});

test('image-only request budget supports photos above 1 MiB; text keeps its existing limit', async t => {
  let calls = 0;
  const { baseURL } = await fixture(t, { imageRunner: async () => { calls++; return imageResponse({status:'completed',result:png}); } });
  const payload = Buffer.concat([Buffer.from(png,'base64'),Buffer.alloc(1024*1024)]).toString('base64');
  const headers={Authorization:`Bearer ${token}`,'Content-Type':'application/json'};
  const photo = await fetch(baseURL+'/images/generations',{method:'POST',headers,body:JSON.stringify({prompt:'Scene',reference_image:{mime_type:'image/png',b64_json:payload}})});
  assert.equal(photo.status,200);
  const text = await fetch(baseURL+'/chat/completions',{method:'POST',headers,body:JSON.stringify({messages:[{role:'user',content:'a'.repeat(1024*1024)}]})});
  assert.equal(text.status,413);
  assert.equal(calls,1);
});


test('queued calls run after a slot is released and can be cancelled', async () => {
  const { createLimiter } = await import('./limiter.mjs');
  const acquire = createLimiter(1, 2, 1000);
  const release = await acquire();
  const controller = new AbortController();
  const cancelled = acquire(controller.signal);
  const next = acquire();
  controller.abort();
  await assert.rejects(cancelled, /cancelled/);
  release();
  const releaseNext = await next; releaseNext();
  const releaseLast = await acquire(); releaseLast();
});

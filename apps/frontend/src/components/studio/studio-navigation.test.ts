import assert from 'node:assert/strict';
import { test } from 'node:test';
import { embeddedPath, nativePath, studioPath } from './studio-navigation.ts';

const origin = 'https://postiz.example.test';

test('studio deep links preserve the selected content and conversation', () => {
  const path = '/studio?conversation=chat%20one&item=post-2#contenus';
  assert.equal(studioPath(path, origin), '/studio?conversation=chat+one&item=post-2#contenus');
  assert.equal(studioPath('/studio?item=post-2&conversation=chat+one#contenus', origin), studioPath(path, origin));
  assert.equal(embeddedPath(path, origin), '/editorial/?conversation=chat+one&item=post-2&embedded=1#contenus');
});

test('only the iframe receives the embedded parameter', () => {
  assert.equal(studioPath('/studio/?embedded=1&item=post-2#semaine', origin), '/studio?item=post-2#semaine');
  assert.equal(embeddedPath('/studio/connect?item=post-2', origin), '/editorial/connect?item=post-2&embedded=1');
  assert.equal(studioPath('/studio', origin), '/studio#discussion');
  assert.equal(studioPath('/studio#unknown', origin), '/studio#discussion');
});

test('frame messages cannot escape the explicit studio and native route lists', () => {
  for (const path of [null, {}, '//evil.test/studio', 'https://evil.test/studio', '/\\evil.test/studio', '/studio/other', '/api/user', '/editorial/agent/mcp', 'javascript:alert(1)']) {
    assert.equal(studioPath(path, origin), null);
    assert.equal(nativePath(path, origin), null);
  }
  assert.equal(nativePath('/settings?section=accounts#connected', origin), '/settings?section=accounts#connected');
  assert.equal(nativePath('/auth/login', origin), '/auth/login');
  assert.equal(nativePath('/settings/other', origin), null);
});

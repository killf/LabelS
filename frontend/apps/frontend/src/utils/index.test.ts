import assert from 'node:assert/strict';
import test from 'node:test';

import { compare, jsonParse, jsonStringify } from './index.ts';

test('JSON keeps ordinary nested values intact', () => {
  const value = { name: 'a/b', values: [1, null, true, '%bad-escape'] };
  assert.deepEqual(jsonParse(JSON.stringify(value)), value);
});

test('regular expressions survive the supported JSON round trip', () => {
  const value = { rule: /a\/b\d+/gi, empty: /(?:)/, plain: 'new RegExp("x")' };
  assert.deepEqual(jsonParse(jsonStringify(value)), value);
});

test('invalid expressions and encoded text remain strings', () => {
  const value = { invalid: '/[/g', flags: '/x/gg', text: encodeURIComponent('a/b') };
  assert.deepEqual(jsonParse(JSON.stringify(value)), value);
});

test('code-like JSON strings are never executed', () => {
  const marker = globalThis as typeof globalThis & { labelsParserExecuted?: boolean };
  delete marker.labelsParserExecuted;
  const value = { text: '(globalThis.labelsParserExecuted = true)' };
  assert.deepEqual(jsonParse(JSON.stringify(value)), value);
  assert.equal(marker.labelsParserExecuted, undefined);
});

test('malformed JSON still reports the parse error', () => {
  assert.throws(() => jsonParse('{invalid}'), SyntaxError);
});

test('deep comparison handles primitives, null and nested arrays', () => {
  assert.equal(compare({ items: [1, null, { done: true }] }, { items: [1, null, { done: true }] }), true);
  assert.equal(compare({ items: [1, 2] }, { items: [2, 1] }), false);
  assert.equal(compare(null, {}), false);
});

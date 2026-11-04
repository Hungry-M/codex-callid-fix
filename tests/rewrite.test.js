'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { outputToText, rewriteBody } = require('../backend/rewrite');

test('rewrites a synthetic function_call_output without call_id', () => {
  const body = {
    input: [
      { type: 'message', role: 'user', content: 'hello' },
      {
        type: 'function_call_output',
        name: 'create_thread',
        namespace: 'codex',
        output: 'child thread created',
      },
    ],
  };

  const changed = rewriteBody(body);

  assert.equal(changed, 1);
  assert.equal(body.input.length, 2);
  assert.deepEqual(body.input[0], {
    type: 'message',
    role: 'user',
    content: 'hello',
  });
  assert.equal(body.input[1].type, 'message');
  assert.equal(body.input[1].role, 'user');
  assert.match(body.input[1].content[0].text, /Delegated task delivered by codex\.create_thread/);
  assert.match(body.input[1].content[0].text, /child thread created/);
});

test('keeps a function_call_output that has a call_id', () => {
  const item = {
    type: 'function_call_output',
    call_id: 'call_123',
    output: 'ok',
  };
  const body = { input: [item] };

  assert.equal(rewriteBody(body), 0);
  assert.equal(body.input[0], item);
});

test('treats an empty call_id as synthetic', () => {
  const body = {
    input: [{ type: 'function_call_output', call_id: '', output: 'x' }],
  };

  assert.equal(rewriteBody(body), 1);
  assert.equal(body.input[0].type, 'message');
});

test('joins array output parts and drops empty parts', () => {
  const body = {
    input: [
      {
        type: 'function_call_output',
        output: [{ text: 'a' }, { text: '' }, 'b'],
      },
    ],
  };

  assert.equal(rewriteBody(body), 1);
  assert.match(body.input[0].content[0].text, /a\nb/);
});

test('serializes object output instead of dropping it', () => {
  const body = {
    input: [
      {
        type: 'function_call_output',
        output: { status: 'done', count: 2 },
      },
    ],
  };

  assert.equal(rewriteBody(body), 1);
  assert.match(body.input[0].content[0].text, /"status":"done"/);
});

test('does nothing when input is not an array', () => {
  const body = { input: 'not-an-array' };
  assert.equal(rewriteBody(body), 0);
  assert.equal(body.input, 'not-an-array');
});

test('preserves order and rewrites multiple items', () => {
  const body = {
    input: [
      { type: 'function_call_output', output: 'first' },
      { type: 'message', role: 'user', content: 'middle' },
      { type: 'function_call_output', call_id: null, output: 'last' },
    ],
  };

  assert.equal(rewriteBody(body), 2);
  assert.equal(body.input[0].content[0].text.includes('first'), true);
  assert.equal(body.input[1].content, 'middle');
  assert.equal(body.input[2].content[0].text.includes('last'), true);
});

test('outputToText handles strings, objects, and null', () => {
  assert.equal(outputToText('x'), 'x');
  assert.equal(outputToText({ text: 'y' }), 'y');
  assert.equal(outputToText(null), '');
});

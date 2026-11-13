import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const vite = await createServer({ appType: 'custom', logLevel: 'silent',
  root: fileURLToPath(new URL('../', import.meta.url)), server: { middlewareMode: true } });
const { openSpeechMicrophone } = await vite.ssrLoadModule('/src/features/desktop-shell/model/desktopMicrophone.ts');
after(() => vite.close());
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; };

function host() {
  const requests = [], replies = [];
  const stream = {};
  global.window = { pywebview: { api: { respond_microphone_permission: async (id, allow) => {
    replies.push([id, allow]);
    const pending = requests[Number(id)];
    if (allow) pending.resolve(stream);
    else pending.reject(new Error('permission denied'));
    return true;
  } } } };
  Object.defineProperty(global, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: () => {
    const pending = deferred(); requests.push(pending); return pending.promise;
  } } } });
  return { requests, replies, stream };
}

test('permission is shown inline and only an explicit answer grants access', async () => {
  const ctx = host(); let answer;
  const result = openSpeechMicrophone(new AbortController().signal, reply => { answer = reply; });
  await tick();
  assert.equal(window.__tianceMicrophonePermissionRequest('0'), true);
  assert.equal(ctx.replies.length, 0);
  await answer(true);
  assert.equal(await result, ctx.stream);
  assert.equal(window.__tianceMicrophonePermissionRequest, undefined);
  assert.deepEqual(ctx.replies, [['0', true]]);
});

test('switch/cancel before native event arrives denies the late request', async () => {
  const ctx = host(), abort = new AbortController();
  let shown = 0;
  const result = openSpeechMicrophone(abort.signal, () => shown++);
  const rejected = assert.rejects(result, /permission denied/);
  await tick(); abort.abort();
  window.__tianceMicrophonePermissionRequest('0');
  await rejected;
  assert.equal(shown, 0);
  assert.deepEqual(ctx.replies, [['0', false]]);
});

test('cancellation clears permission before a different composer can ask', async () => {
  const ctx = host(), abort = new AbortController();
  let oldAnswer, newAnswer;
  const first = openSpeechMicrophone(abort.signal, reply => { oldAnswer = reply; });
  const rejected = assert.rejects(first, /permission denied/);
  await tick(); window.__tianceMicrophonePermissionRequest('0');
  const second = openSpeechMicrophone(new AbortController().signal, reply => { newAnswer = reply; });
  assert.equal(ctx.requests.length, 1);
  abort.abort(); await rejected; await tick();
  assert.equal(ctx.requests.length, 2);
  window.__tianceMicrophonePermissionRequest('1');
  await oldAnswer(true); // A stale click cannot grant permission to the new capture.
  assert.deepEqual(ctx.replies, [['0', false]]);
  await newAnswer(true); await second;
  assert.deepEqual(ctx.replies, [['0', false], ['1', true]]);
});

test('already granted native permissions need no inline prompt', async () => {
  const ctx = host();
  const result = openSpeechMicrophone(new AbortController().signal, () => assert.fail('unneeded prompt'));
  await tick(); ctx.requests[0].resolve(ctx.stream);
  assert.equal(await result, ctx.stream);
  assert.equal(window.__tianceMicrophonePermissionRequest, undefined);
});

test('ordinary browsers retain the browser permission flow', async () => {
  const ctx = host(); delete window.pywebview;
  const result = openSpeechMicrophone(new AbortController().signal, () => assert.fail('native-only UI'));
  ctx.requests[0].resolve(ctx.stream);
  assert.equal(await result, ctx.stream);
  assert.equal(window.__tianceMicrophonePermissionRequest, undefined);
});

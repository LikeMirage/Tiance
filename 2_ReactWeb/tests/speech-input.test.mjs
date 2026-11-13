import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { createServer as createHttpServer } from 'node:http';

const vite = await createServer({ appType: 'custom', logLevel: 'silent',
  root: fileURLToPath(new URL('../', import.meta.url)), server: { middlewareMode: true } });
const { SpeechCapture } = await vite.ssrLoadModule('/src/features/ai-panel/model/speechCapture.ts');
const { insertSpeechText } = await vite.ssrLoadModule('/src/features/ai-panel/model/speechDraft.ts');
const { conversationSpeech, speechEndpoint } = await vite.ssrLoadModule('/src/services/project/conversationSpeech.ts');
const { env } = await vite.ssrLoadModule('/src/shared/config/env.ts');
after(() => vite.close());
const origin = { projectId: 'p', sessionId: 'a', draft: '前后', caret: 1 };
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { promise, resolve }; };

function setup(overrides = {}, mediaOverride) {
  const delivered = [], cancelled = [], uploads = [], recorders = [];
  let closed = 0;
  const stream = { getTracks: () => [{ stop: () => closed++ }] };
  const api = {
    create: async () => ({ id: 'job' }),
    upload: async (path, blob) => { uploads.push({ path, blob }); },
    start: async () => {},
    status: async () => ({ status: 'completed', text: '中间' }),
    cancel: async path => { cancelled.push(path); }, ...overrides,
  };
  const manager = new SpeechCapture((...args) => delivered.push(args), api,
    mediaOverride ?? (async () => stream), () => {
      const recorder = { state: 'inactive', mimeType: 'audio/webm;codecs=opus',
        start() { this.state = 'recording'; },
        stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(['audio']) }); this.onstop(); },
      };
      recorders.push(recorder);
      return recorder;
    });
  return { manager, stream, delivered, cancelled, uploads, recorders, closed: () => closed };
}

test('focused caret inserts, blurred or changed drafts append without replacing content', () => {
  assert.equal(insertSpeechText('前后', origin, '语音'), '前语音后');
  assert.equal(insertSpeechText('前后', { ...origin, caret: null }, '语音'), '前后语音');
  assert.equal(insertSpeechText('用户新内容', origin, '语音'), '用户新内容语音');
});

test('recording lifecycle uses the /api prefix over HTTP, including upload and cancellation', async () => {
  const requests = [];
  const base = '/api/projects/project-a/conversations/session-a/recordings';
  const server = createHttpServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    requests.push({ method: req.method, path: req.url, body: Buffer.concat(chunks).toString(), type: req.headers['content-type'] });
    if (!req.url.startsWith(base)) { res.writeHead(404); res.end('Not Found'); return; }
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ id: 'job', status: 'ready' }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const previousBase = env.apiBaseUrl;
  env.apiBaseUrl = `http://127.0.0.1:${server.address().port}`;
  try {
    const endpoint = speechEndpoint('project-a', 'session-a');
    const { id } = await conversationSpeech.create(endpoint);
    const path = `${endpoint}/${id}`;
    const signal = new AbortController().signal;
    await conversationSpeech.upload(path, new Blob(['recorded bytes'], { type: 'audio/webm' }));
    await conversationSpeech.start(path, signal);
    await conversationSpeech.status(path, signal);
    await conversationSpeech.cancel(path);
    assert.deepEqual(requests.map(({ method, path }) => [method, path]), [
      ['POST', base], ['PUT', `${base}/job/audio`], ['POST', `${base}/job/recognize`],
      ['GET', `${base}/job`], ['DELETE', `${base}/job`],
    ]);
    assert.equal(requests[1].body, 'recorded bytes');
    assert.equal(requests[1].type, 'audio/webm');
  } finally {
    env.apiBaseUrl = previousBase;
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('switching conversation stops recording and delivers only to its origin', async () => {
  const ctx = setup();
  await ctx.manager.start(origin);
  assert.equal(ctx.manager.get('p', 'a').stream, ctx.stream);
  ctx.manager.leave('p', 'b');
  await tick();
  assert.equal(ctx.recorders[0].state, 'inactive');
  assert.ok(ctx.closed());
  assert.deepEqual(ctx.delivered, [[origin, '中间']]);
  assert.match(ctx.uploads[0].path, /conversations\/a\/recordings\/job$/);
  assert.equal(ctx.manager.get('p', 'b'), null);
  assert.equal(ctx.manager.get('p', 'a'), null);
});

test('cancelled recognition cannot insert a late completed response', async () => {
  const pending = deferred();
  const ctx = setup({ status: () => pending.promise });
  await ctx.manager.start(origin);
  ctx.manager.stop('p', 'a');
  await tick();
  await ctx.manager.cancel('p', 'a');
  pending.resolve({ status: 'completed', text: 'late' });
  await tick();
  assert.equal(ctx.delivered.length, 0);
  assert.equal(ctx.cancelled.length, 1);
  assert.equal(ctx.manager.get('p', 'a'), null);
});

test('cancel racing creation saves the original recording without starting recognition', async () => {
  const pending = deferred();
  let started = 0;
  const ctx = setup({ create: () => pending.promise, start: async () => { started++; } });
  await ctx.manager.start(origin);
  ctx.manager.stop('p', 'a');
  await ctx.manager.cancel('p', 'a');
  pending.resolve({ id: 'created-late' });
  await tick();
  assert.equal(ctx.delivered.length, 0);
  assert.equal(ctx.uploads.length, 1);
  assert.equal(started, 0);
  assert.match(ctx.cancelled[0], /created-late$/);
});

test('cancel during saving keeps the whole source but never submits it for recognition', async () => {
  const pending = deferred();
  let started = 0;
  const ctx = setup({ upload: () => pending.promise, start: async () => { started++; } });
  await ctx.manager.start(origin);
  ctx.manager.stop('p', 'a');
  await tick();
  await ctx.manager.cancel('p', 'a');
  assert.equal(ctx.cancelled.length, 0);
  pending.resolve();
  await tick();
  assert.equal(started, 0);
  assert.equal(ctx.cancelled.length, 1);
  assert.equal(ctx.delivered.length, 0);
});

test('leaving while permission dialog is open closes the late microphone', async () => {
  const permission = deferred();
  const ctx = setup({}, () => permission.promise);
  const start = ctx.manager.start(origin);
  ctx.manager.leave('p', 'b');
  permission.resolve(ctx.stream);
  await start;
  assert.ok(ctx.closed());
  assert.equal(ctx.recorders.length, 0);
  assert.equal(ctx.manager.get('p', 'a'), null);
});

test('network error cancels remote work and preserves a visible error', async () => {
  const ctx = setup({ status: async () => { throw new Error('network down'); } });
  await ctx.manager.start(origin);
  ctx.manager.stop('p', 'a');
  await tick();
  assert.equal(ctx.cancelled.length, 1);
  assert.equal(ctx.manager.get('p', 'a').phase, 'error');
  assert.equal(ctx.delivered.length, 0);
});

test('inline permission switches to recording only after approval', async () => {
  const permission = deferred(); let grants = 0;
  const ctx = setup({}, (_signal, show) => {
    show(async allow => { if (allow) { grants++; permission.resolve(ctx.stream); } });
    return permission.promise;
  });
  const started = ctx.manager.start(origin);
  assert.equal(ctx.manager.get('p', 'a').phase, 'permission');
  assert.equal(ctx.recorders.length, 0);
  await ctx.manager.allowMicrophone('p', 'a'); await started;
  assert.equal(grants, 1);
  assert.equal(ctx.manager.get('p', 'a').phase, 'recording');
  await ctx.manager.cancel('p', 'a');
});

test('switching away from inline permission cancels without recording or recognition', async () => {
  const permission = deferred(); let aborted = false;
  const ctx = setup({}, (signal, show) => {
    signal.addEventListener('abort', () => { aborted = true; permission.resolve(ctx.stream); });
    show(async () => assert.fail('must not grant after switch'));
    return permission.promise;
  });
  const started = ctx.manager.start(origin);
  ctx.manager.leave('p', 'b');
  await ctx.manager.allowMicrophone('p', 'a'); await started;
  assert.equal(aborted, true);
  assert.equal(ctx.recorders.length, 0);
  assert.equal(ctx.uploads.length, 0);
  assert.equal(ctx.manager.get('p', 'a'), null);
});

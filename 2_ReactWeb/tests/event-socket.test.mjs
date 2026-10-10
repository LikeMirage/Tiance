import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { watchEventSocket, EVENT_SOCKET_RECONNECT_DELAY_MS } = await vite.ssrLoadModule("/src/services/http/watchEventSocket.ts");
const { watchProjectFileEvents } = await vite.ssrLoadModule("/src/services/project/watchProjectFileEvents.ts");
const { watchProjectWorkspaceEvents } = await vite.ssrLoadModule("/src/services/project/watchProjectWorkspaceEvents.ts");
const { watchThemeWorkspaceEvents } = await vite.ssrLoadModule("/src/services/theme/watchThemeWorkspaceEvents.ts");
after(() => vite.close());

class Socket {
  static instances = [];
  constructor(url) { this.url = url; this.closed = false; Socket.instances.push(this); }
  open() { this.onopen?.(); }
  message(payload) { this.onmessage?.({ data: JSON.stringify(payload) }); }
  disconnect() { this.onclose?.(); }
  close() { this.closed = true; this.disconnect(); }
}
function setup(t) {
  Socket.instances = [];
  t.mock.property(globalThis, "WebSocket", Socket);
  t.mock.timers.enable({ apis: ["setTimeout"] });
}

test("通知使用独立 WebSocket；HTTPS 保持 WSS，关闭后拒收晚到消息", (t) => {
  setup(t);
  const messages = [];
  const stop = watchEventSocket("https://example.test/api/projects/events", {onMessage: m => messages.push(m)});
  t.after(stop);
  const socket = Socket.instances[0];
  assert.equal(socket.url, "wss://example.test/api/projects/events");
  socket.open(); socket.message({kind: "ready"});
  stop(); socket.message({kind: "changed"});
  t.mock.timers.tick(EVENT_SOCKET_RECONNECT_DELAY_MS * 2);
  assert.equal(messages.length, 1);
  assert.equal(Socket.instances.length, 1);
  assert.equal(socket.closed, true);
});

test("断线按明确间隔重连，关闭订阅后取消等待中的重连", (t) => {
  setup(t);
  const stop = watchEventSocket("http://localhost/api/themes/events", {onMessage: () => {}});
  t.after(stop);
  Socket.instances[0].disconnect();
  t.mock.timers.tick(EVENT_SOCKET_RECONNECT_DELAY_MS - 1);
  assert.equal(Socket.instances.length, 1);
  t.mock.timers.tick(1);
  assert.equal(Socket.instances.length, 2);
  Socket.instances[1].disconnect(); stop();
  t.mock.timers.tick(EVENT_SOCKET_RECONNECT_DELAY_MS);
  assert.equal(Socket.instances.length, 2);
});

test("同项目共享连接，重连 ready 后核对文件，保活不刷新图片", (t) => {
  setup(t);
  const changed = [], statuses = []; let reconciled = 0;
  const stopA = watchProjectFileEvents("png-project", {
    onChanged: paths => changed.push(paths), onOverflow: () => reconciled++,
    onStatusChanged: available => statuses.push(available),
  });
  const stopB = watchProjectFileEvents("png-project", {onChanged: () => {}});
  t.after(() => { stopA(); stopB(); });
  assert.equal(Socket.instances.length, 1);
  const first = Socket.instances[0]; first.open(); first.message({kind: "ready"});
  first.message({kind: "heartbeat"});
  assert.equal(reconciled, 0); assert.deepEqual(statuses, [true]);
  first.disconnect();
  t.mock.timers.tick(EVENT_SOCKET_RECONNECT_DELAY_MS);
  const second = Socket.instances[1]; second.open();
  assert.equal(reconciled, 0);
  first.message({kind: "changed", paths: ["late.png"]});
  second.message({kind: "ready"});
  second.message({kind: "ready"});
  assert.equal(reconciled, 1);
  second.message({kind: "changed", paths: ["new.png"]});
  assert.deepEqual(changed, [["new.png"]]);
  stopA(); assert.equal(second.closed, false);
  stopB(); assert.equal(second.closed, true);
});

for (const [name, watch] of [["项目集", watchProjectWorkspaceEvents], ["主题", watchThemeWorkspaceEvents]]) {
  test(`${name}首次连接失败后恢复也会核对，正常通知仍只传递原路径`, (t) => {
    setup(t);
    const changes = [];
    const stop = watch(paths => changes.push(paths)); t.after(stop);
    Socket.instances[0].disconnect();
    t.mock.timers.tick(EVENT_SOCKET_RECONNECT_DELAY_MS);
    const second = Socket.instances[1]; second.open();
    assert.deepEqual(changes, []);
    second.message({kind: "heartbeat"});
    second.message({kind: "ready"});
    second.message({kind: "changed", paths: ["catalog.json"]});
    second.message({kind: "ready"});
    assert.deepEqual(changes, [[], ["catalog.json"]]);
  });
}

import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
  plugins: [{
    name: "telegram-panel-test", enforce: "pre",
    transform(_code, id) {
      if (id.replaceAll("\\", "/").endsWith("/src/shared/i18n/index.ts")) {
        return "export const useI18n = () => ({ t: key => key, language: 'zh-CN' });";
      }
      if (id.replaceAll("\\", "/").endsWith("/ui/TelegramGuide.tsx")) {
        return "export const TelegramGuide = () => 'guide';";
      }
    },
  }],
});
after(() => vite.close());
const { TelegramConnectionPanel: TelegramAccessPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/TelegramConnectionPanel.tsx");
const { TelegramAccessPanel: TabbedPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/TelegramAccessPanel.tsx");
const { PlatformConnectionPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/PlatformConnectionPanel.tsx");
const status = {
  connection_id: "telegram:1", connections: [], enabled: true, has_token: true,
  api_base: "https://api.telegram.org", error: null, desktop_online: true,
  pending_deliveries: 0, bot: { first_name: "Test" },
  allowed_collections: ["project"],
  peers: [{ id: "peer", user_id: 1, name: "User", allowed: false, reviewed: false }],
};

async function withPanel(request, verify, Component = TelegramAccessPanel) {
  const previous = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  let scheduled, view;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.fetch = (url, options) => request(String(url), options?.method ?? "GET",
    options?.body ? JSON.parse(options.body) : undefined);
  globalThis.setTimeout = (callback, delay, ...args) => {
    if (delay !== 5000) return previous.setTimeout(callback, delay, ...args);
    scheduled = { callback };
    return scheduled;
  };
  globalThis.clearTimeout = handle => {
    if (handle === scheduled) scheduled = null;
    else previous.clearTimeout(handle);
  };
  try {
    await act(async () => { view = create(React.createElement(Component)); });
    await verify({
      root: () => view.root,
      polling: () => Boolean(scheduled),
      alerts: () => view.root.findAllByProps({ role: "alert" }).map(node => node.children.join("")),
      ready: () => view.root.findAllByType("p").some(node => node.children.includes("telegramAccess.ready")),
      poll: async () => {
        assert.ok(scheduled, "status polling should remain scheduled");
        await act(async () => { await scheduled.callback(); });
      },
      beginPoll: () => scheduled.callback(),
      click: async label => {
        const button = view.root.findAllByType("button").find(node => node.props["aria-label"] === label || node.children.includes(label));
        assert.ok(button);
        assert.equal(button.props.disabled, false);
        await act(async () => { button.props.onClick(); });
      },
    });
  } finally {
    if (view) await act(async () => view.unmount());
    globalThis.fetch = previous.fetch;
    globalThis.setTimeout = previous.setTimeout;
    globalThis.clearTimeout = previous.clearTimeout;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  }
}

test("状态查询短暂 502 后恢复，自动清除旧错误并恢复就绪显示", async () => {
  let calls = 0;
  await withPanel(() => {
    calls++;
    return Promise.resolve(calls === 2 ? new Response(null, { status: 502 }) : Response.json(status));
  }, async ({ alerts, ready, poll }) => {
    assert.equal(ready(), true);
    await poll();
    assert.deepEqual(alerts(), ["Request failed with status 502."]);
    assert.equal(ready(), false);
    await poll();
    assert.deepEqual(alerts(), []);
    assert.equal(ready(), true);
    assert.equal(calls, 3);
  });
});

test("后台查询成功不能清除保存或授权失败，操作成功才清除操作错误", async () => {
  let failOperation = true;
  await withPanel((_url, method) => Promise.resolve(method !== "GET" && failOperation
    ? Response.json({ error: { message: "operation failed" } }, { status: 400 })
    : Response.json(status)), async ({ alerts, click, poll }) => {
    for (const label of ["telegramAccess.enabled", "telegramAccess.allow · User · ID 1"]) {
      failOperation = true;
      await click(label);
      assert.deepEqual(alerts(), ["operation failed"]);
      await poll();
      assert.deepEqual(alerts(), ["operation failed"]);
      failOperation = false;
      await click(label);
      assert.deepEqual(alerts(), []);
    }
  });
});

test("启用开关检查 Token，连接失败保留输入，关闭保留配置，再开启复用已存 Token", async () => {
  let current = { ...status, connection_id: null, enabled: false, has_token: false, bot: null };
  let fail = true;
  const writes = [];
  await withPanel((_url, method, body) => {
    if (method === "PUT") {
      writes.push(body);
      if (fail) return Promise.resolve(Response.json({ error: { message: "connect failed" } }, { status: 400 }));
      current = { ...status, enabled: body.enabled, api_base: body.api_base };
    }
    return Promise.resolve(Response.json(current));
  }, async ({ alerts, click, root, poll }) => {
    const toggle = () => root().findAllByType("button").find(node => node.props.id === "telegram-enabled");
    const tokenInput = () => root().findAllByType("input").find(node => node.props.id === "telegram-token");
    await click("telegramAccess.enabled");
    assert.deepEqual(alerts(), ["telegramAccess.tokenRequired"]);
    assert.equal(writes.length, 0);
    assert.equal(toggle().props["aria-checked"], false);
    await act(async () => tokenInput().props.onChange({ target: { value: "new-token" } }));
    await click("telegramAccess.enabled");
    assert.deepEqual(alerts(), ["connect failed"]);
    assert.equal(toggle().props["aria-checked"], false);
    assert.equal(tokenInput().props.value, "new-token");
    fail = false;
    await click("telegramAccess.enabled");
    assert.equal(toggle().props["aria-checked"], true);
    assert.equal(tokenInput().props.value, "");
    assert.equal(tokenInput().props.disabled, true);
    await click("telegramAccess.enabled");
    assert.equal(toggle().props["aria-checked"], false);
    assert.equal(tokenInput().props.disabled, false);
    assert.deepEqual(writes.at(-1), { token: "", enabled: false, api_base: status.api_base, connection_id: status.connection_id });
    await click("telegramAccess.enabled");
    assert.equal(writes.at(-1).token, "");
    assert.equal(writes.at(-1).enabled, true);
    assert.equal(toggle().props["aria-checked"], true);
    current = { ...current, enabled: false };
    await poll();
    assert.equal(toggle().props["aria-checked"], false, "switch follows the actual backend state");
    assert.ok(root().findAllByType("button").every(node => node.props.role === "switch"));
    const users = root().findByProps({ className: "telegram-access__users" });
    assert.equal(users.findAllByType("p")[0].children[0], "telegramAccess.intro");
  });
});

test("授权开关按后端结果更新，失败不改变原授权", async () => {
  let current = structuredClone(status);
  let fail = true;
  await withPanel((_url, method, body) => {
    if (method === "POST") {
      assert.equal(body.peer, "peer");
      if (fail) return Promise.resolve(Response.json({ error: { message: "authorization failed" } }, { status: 400 }));
      current.peers[0].allowed = body.allowed;
    }
    return Promise.resolve(Response.json(current));
  }, async ({ alerts, click, root }) => {
    const label = "telegramAccess.allow · User · ID 1";
    const toggle = () => root().findAllByType("button").find(node => node.props["aria-label"] === label);
    await click(label);
    assert.equal(toggle().props["aria-checked"], false);
    assert.deepEqual(alerts(), ["authorization failed"]);
    fail = false;
    await click(label);
    assert.equal(toggle().props["aria-checked"], true);
    await click(label);
    assert.equal(toggle().props["aria-checked"], false);
  });
});

test("本地状态查询成功仍保留后端报告的 Telegram 通道故障", async () => {
  let channelError = "Telegram connection failed";
  await withPanel(() => Promise.resolve(Response.json({ ...status, error: channelError })),
    async ({ alerts, ready, poll }) => {
      await poll();
      assert.deepEqual(alerts(), [channelError]);
      assert.equal(ready(), false);
      channelError = null;
      await poll();
      assert.deepEqual(alerts(), []);
      assert.equal(ready(), true);
    });
});

test("帮助标签保留 Token 和地址草稿，停用轮询；日志按连接分页，刷新回到首页", async () => {
  const requests = [];
  await withPanel((url) => {
    requests.push(url);
    if (url.includes('/logs?')) {
      const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'));
      return Promise.resolve(Response.json({ total: 51, retention: 1000, items: [{ id: String(offset),
        event: 'enabled', level: 'info', time: 1000, details: { chat_id: 2 } }] }));
    }
    return Promise.resolve(Response.json({ ...status, enabled: false }));
  }, async ({ root, polling, click }) => {
    const tab = async key => act(async () => {
      root().findAllByProps({ role: 'tab' }).find(item => item.children.includes(`telegramAccess.tabs.${key}`)).props.onClick();
    });
    assert.equal(root().findAllByProps({ role: 'tab' }).length, 5);
    await act(async () => {
      root().findByProps({ id: 'telegram-token' }).props.onChange({ target: { value: 'private-draft' } });
      root().findByProps({ id: 'telegram-api' }).props.onChange({ target: { value: 'http://127.0.0.1:8081' } });
    });
    await tab('quickStart');
    assert.equal(polling(), false);
    await tab('connection');
    assert.equal(polling(), true);
    assert.equal(root().findByProps({ id: 'telegram-token' }).props.value, 'private-draft');
    assert.equal(root().findByProps({ id: 'telegram-api' }).props.value, 'http://127.0.0.1:8081');
    await tab('logs');
    assert.equal(polling(), false);
    assert.match(requests.at(-1), /connection_id=telegram%3A1/);
    assert.match(requests.at(-1), /offset=0/);
    await click('telegramAccess.logs.next');
    assert.match(requests.at(-1), /offset=50/);
    await click('telegramAccess.logs.refresh');
    assert.match(requests.at(-1), /offset=0/);
    assert.ok(requests.every(url => !url.includes('private-draft')));
  }, TabbedPanel);
});

test("访问范围与用户并排，默认只开项目集，按当前连接自动保存", async () => {
  let current = structuredClone(status);
  const writes = [];
  await withPanel((url, method, body) => {
    if (method === "PUT") {
      assert.ok(url.endsWith("/api/mobile/telegram/access-scope"));
      writes.push(body);
      current = { ...current, allowed_collections: body.allowed_collections };
    }
    return Promise.resolve(Response.json(current));
  }, async ({ root, click }) => {
    const layout = root().findByProps({ className: "telegram-access__permissions" });
    assert.equal(layout.findAllByProps({ className: "telegram-access__users" }).length, 1);
    assert.equal(layout.findAllByProps({ className: "telegram-access__scope" }).length, 1);
    const switches = () => root().findAllByType("button").filter(node => node.props["aria-label"]?.startsWith("telegramAccess.scope.title"));
    assert.equal(switches().length, 7);
    assert.deepEqual(switches().map(node => node.props["aria-checked"]), [true, false, false, false, false, false, false]);
    await click("telegramAccess.scope.title · telegramAccess.scope.collections.tool");
    assert.deepEqual(writes[0], { connection_id: "telegram:1", allowed_collections: ["project", "tool"] });
    assert.equal(root().findAllByProps({ className: "telegram-access__scope-summary" }).length, 0);
    await click("telegramAccess.scope.title · telegramAccess.scope.collections.project");
    assert.deepEqual(writes[1].allowed_collections, ["tool"]);
    assert.equal(root().findAllByProps({ className: "telegram-access__scope-summary" }).length, 0);
  });
});

test("范围保存失败保留原开关，全部关闭显示空范围，轮询不掩盖保存失败", async () => {
  let current = structuredClone(status), fail = true;
  await withPanel((_url, method, body) => {
    if (method === "PUT") {
      if (fail) return Promise.resolve(Response.json({ error: { message: "scope failed" } }, { status: 400 }));
      current = { ...current, allowed_collections: body.allowed_collections };
    }
    return Promise.resolve(Response.json(current));
  }, async ({ root, click, poll, alerts }) => {
    const label = "telegramAccess.scope.title · telegramAccess.scope.collections.project";
    const toggle = () => root().findAllByType("button").find(node => node.props["aria-label"] === label);
    await click(label);
    assert.equal(toggle().props["aria-checked"], true);
    await poll();
    assert.deepEqual(alerts(), ["scope failed"]);
    fail = false;
    await click(label);
    assert.equal(toggle().props["aria-checked"], false);
    assert.equal(root().findByProps({ className: "telegram-access__scope-summary" }).children[0], "telegramAccess.scope.empty");
  });
});

test("晚到的状态轮询不能覆盖刚保存的范围", async () => {
  let current = structuredClone(status), resolvePoll, reads = 0;
  await withPanel((_url, method, body) => {
    if (method === "GET" && ++reads === 2) return new Promise(resolve => { resolvePoll = resolve; });
    if (method === "PUT") current = { ...current, allowed_collections: body.allowed_collections };
    return Promise.resolve(Response.json(current));
  }, async ({ root, beginPoll, click }) => {
    let pending;
    await act(async () => { pending = beginPoll(); });
    await click("telegramAccess.scope.title · telegramAccess.scope.collections.tool");
    await act(async () => { resolvePoll(Response.json(status)); await pending; });
    const tool = root().findAllByType("button").find(node => node.props["aria-label"] === "telegramAccess.scope.title · telegramAccess.scope.collections.tool");
    assert.equal(tool.props["aria-checked"], true);
  });
});

test("没有已连接机器人时范围开关禁用", async () => {
  await withPanel(() => Promise.resolve(Response.json({ ...status, connection_id: null })), async ({ root }) => {
    const switches = root().findAllByType("button").filter(node => node.props["aria-label"]?.startsWith("telegramAccess.scope.title"));
    assert.ok(switches.every(node => node.props.disabled));
    assert.equal(root().findByProps({ className: "telegram-access__scope-summary" }).children[0], "telegramAccess.scope.connectFirst");
  });
});

for (const platform of ["wechat", "feishu"]) {
  const Panel = () => React.createElement(PlatformConnectionPanel, { platform, active: true, onConnection: () => {} });
  test(`${platform} 的范围独立自动保存，失败保留原值且不显示冗余说明`, async () => {
    let current = { ...status, connection_id: `${platform}:a`, app_id: "app", enabled: false }, fail = true;
    const writes = [];
    await withPanel((url, method, body) => {
      if (method === "PUT") {
        assert.ok(url.endsWith(`/api/mobile/platform/${platform}/access-scope`));
        assert.equal(body.connection_id, `${platform}:a`);
        writes.push(body);
        if (fail) return Promise.resolve(Response.json({ error: { message: "save failed" } }, { status: 400 }));
        current = { ...current, allowed_collections: body.allowed_collections };
      }
      return Promise.resolve(Response.json(current));
    }, async ({ root, click, alerts }) => {
      assert.equal(root().findByProps({ className: "telegram-access__permissions" }).findAllByProps({ className: "telegram-access__scope" }).length, 1);
      assert.equal(root().findAllByProps({ className: "telegram-access__scope-summary" }).length, 0);
      assert.ok(!root().findAllByType("p").some(node => node.children.includes("telegramAccess.scope.hint")));
      if (platform === "feishu") await act(async () => {
        root().findByProps({ id: "feishu-secret" }).props.onChange({ target: { value: "unsaved-draft" } });
      });
      const label = "telegramAccess.scope.title · telegramAccess.scope.collections.project";
      await click(label);
      assert.deepEqual(alerts(), ["save failed"]);
      assert.equal(root().findAllByType("button").find(node => node.props["aria-label"] === label).props["aria-checked"], true);
      fail = false;
      await click(label);
      assert.deepEqual(writes.at(-1).allowed_collections, []);
      assert.equal(root().findByProps({ className: "telegram-access__scope-summary" }).children[0], "telegramAccess.scope.empty");
      if (platform === "feishu") assert.equal(root().findByProps({ id: "feishu-secret" }).props.value, "unsaved-draft");
    }, Panel);
  });
  test(`${platform} 晚到轮询不会覆盖新范围`, async () => {
    let current = { ...status, connection_id: `${platform}:a` }, reads = 0, resolvePoll;
    await withPanel((_url, method, body) => {
      if (method === "GET" && ++reads === 2) return new Promise(resolve => { resolvePoll = resolve; });
      if (method === "PUT") current = { ...current, allowed_collections: body.allowed_collections };
      return Promise.resolve(Response.json(current));
    }, async ({ root, beginPoll, click }) => {
      let pending;
      await act(async () => { pending = beginPoll(); });
      await click("telegramAccess.scope.title · telegramAccess.scope.collections.tool");
      await act(async () => { resolvePoll(Response.json({ ...current, allowed_collections: ["project"] })); await pending; });
      const tool = root().findAllByType("button").find(node => node.props["aria-label"] === "telegramAccess.scope.title · telegramAccess.scope.collections.tool");
      assert.equal(tool.props["aria-checked"], true);
    }, Panel);
  });
}

test("微信重新扫码切换连接时，旧范围保存响应不能切回旧连接", async () => {
  const Panel = () => React.createElement(PlatformConnectionPanel, { platform: "wechat", active: true, onConnection: () => {} });
  let finishSave, connected = "wechat:a";
  await withPanel((url, method) => {
    if (method === "PUT") return new Promise(resolve => { finishSave = resolve; });
    return Promise.resolve(Response.json({ ...status, connection_id: connected }));
  }, async ({ root, poll }) => {
    const tool = () => root().findAllByType("button").find(node => node.props["aria-label"] === "telegramAccess.scope.title · telegramAccess.scope.collections.tool");
    await act(async () => { tool().props.onClick(); });
    connected = "wechat:b";
    await act(async () => {
      root().find(node => typeof node.type === "function" && node.type.name === "WeChatQr").props.onConnected(connected);
    });
    await act(async () => { finishSave(Response.json({ ...status, connection_id: "wechat:a", allowed_collections: ["project", "tool"] })); });
    await poll();
    assert.equal(tool().props["aria-checked"], false);
  }, Panel);
});

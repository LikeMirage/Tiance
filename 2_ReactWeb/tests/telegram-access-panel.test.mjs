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
      if (id.replaceAll("\\", "/").endsWith("/confirm-modal/ConfirmModal.tsx")) {
        return `import React from 'react'; export const ConfirmModal = props => React.createElement('div', { role: 'dialog' },
          props.message, React.createElement('button', { onClick: props.onCancel, disabled: false }, '取消'),
          React.createElement('button', { onClick: props.onConfirm, disabled: props.confirmDisabled }, '确认删除'));`;
      }
    },
  }],
});
after(() => vite.close());
const { TelegramConnectionPanel: TelegramAccessPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/TelegramConnectionPanel.tsx");
const { TelegramAccessPanel: TabbedPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/TelegramAccessPanel.tsx");
const { PlatformConnectionPanel } = await vite.ssrLoadModule("/src/features/mobile-access/ui/PlatformConnectionPanel.tsx");
const { MobileConnectionSelect } = await vite.ssrLoadModule("/src/features/mobile-access/ui/MobileAccountControls.tsx");
const { FeishuQr } = await vite.ssrLoadModule("/src/features/mobile-access/ui/FeishuQr.tsx");
const status = {
  connection_id: "telegram:1", connections: [], enabled: true, has_token: true,
  api_base: "https://api.telegram.org", error: null, desktop_online: true,
  pending_deliveries: 0, bot: { first_name: "Test" },
  allowed_collections: ["project"],
  peers: [{ id: "peer", user_id: 1, name: "User", allowed: false, reviewed: false }],
};

for (const outcome of ["confirmed", "error", "expired"]) {
  test(`飞书扫码 ${outcome}：仅验证成功通知连接，失败保留明确提示`, async () => {
    const previous = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout,
      clearTimeout: globalThis.clearTimeout, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
    let view, scheduled, failNetwork = true;
    const connected = [], requests = [];
    const waiting = { id: "qr-1", status: "wait", image: "data:image/png;base64,test", error: null };
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.setTimeout = (callback, delay, ...args) => {
      if (delay !== 1500) return previous.setTimeout(callback, delay, ...args);
      scheduled = { callback }; return scheduled;
    };
    globalThis.clearTimeout = handle => {
      if (handle === scheduled) scheduled = null; else previous.clearTimeout(handle);
    };
    globalThis.fetch = async (url, options) => {
      requests.push({ url: String(url), method: options?.method ?? "GET", body: options?.body });
      if (options?.method === "POST") return Response.json(waiting);
      if (failNetwork) { failNetwork = false; throw new Error("暂时断网"); }
      return Response.json({ ...waiting, status: outcome, connection_id: outcome === "confirmed" ? "feishu:new" : undefined,
        error: outcome === "error" ? "飞书拒绝此应用访问（21001：平台策略限制）" : null });
    };
    try {
      await act(async () => { view = create(React.createElement(FeishuQr, { active: true, onConnected: id => connected.push(id) })); });
      await act(async () => { view.root.findByType("button").props.onClick(); });
      assert.equal(view.root.findByType("img").props.alt, "飞书连接二维码");
      await act(async () => { await scheduled.callback(); });
      assert.match(view.root.findByProps({ role: "alert" }).children.join(""), /暂时断网/);
      assert.ok(scheduled, "网络恢复后继续查询本次扫码");
      await act(async () => { await scheduled.callback(); });
      assert.deepEqual(connected, outcome === "confirmed" ? ["feishu:new"] : []);
      assert.equal(view.root.findAllByType("img").length, 0);
      assert.equal(view.root.findByType("button").props.disabled, false);
      if (outcome === "error") assert.match(view.root.findByProps({ role: "alert" }).children.join(""), /21001/);
      assert.ok(requests.every(item => !item.body), "凭据不经浏览器提交");
      assert.equal(requests.filter(item => item.method === "POST").length, 1);
      assert.equal(scheduled, null, "终态停止轮询");
    } finally {
      if (view) await act(async () => view.unmount());
      globalThis.fetch = previous.fetch; globalThis.setTimeout = previous.setTimeout;
      globalThis.clearTimeout = previous.clearTimeout; globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
    }
  });
}

for (const platform of ["wechat", "feishu", "telegram"]) {
  test(`${platform} 消息接收提醒默认开启，切换仅保存当前连接的提醒设置`, async () => {
    const Panel = platform === "telegram" ? TelegramAccessPanel : () => React.createElement(PlatformConnectionPanel, {
      platform, active: true, onConnection: () => {},
    });
    let current = { ...status, connection_id: `${platform}:1`, app_id: "app" };
    const writes = [];
    await withPanel((url, method, body) => {
      if (method !== "GET") {
        writes.push({ url: new URL(url, "http://localhost").pathname, method, body });
        current = { ...current, message_receipt_enabled: body.message_receipt_enabled };
      }
      return Promise.resolve(Response.json(current));
    }, async ({ root, click, poll }) => {
      const toggle = () => root().findAllByType("button").find(node => node.props.id === `${platform}-message-receipt`);
      assert.equal(toggle().props["aria-checked"], true);
      await click("telegramAccess.messageReceipt");
      assert.equal(toggle().props["aria-checked"], false);
      await poll();
      assert.equal(toggle().props["aria-checked"], false);
      assert.deepEqual(writes, [{ url: "/api/mobile/connections/message-receipt", method: "POST", body: {
        platform, connection_id: `${platform}:1`, message_receipt_enabled: false,
      } }]);
      assert.equal(current.enabled, true);
      await click("telegramAccess.messageReceipt");
      assert.equal(toggle().props["aria-checked"], true);
    }, Panel);
  });
  test(`${platform} 提醒设置保存失败时保留原开关状态`, async () => {
    const Panel = platform === "telegram" ? TelegramAccessPanel : () => React.createElement(PlatformConnectionPanel, {
      platform, active: true, onConnection: () => {},
    });
    await withPanel((_url, method) => method === "GET"
      ? Promise.resolve(Response.json({ ...status, connection_id: `${platform}:1`, message_receipt_enabled: false }))
      : Promise.reject(new Error("保存失败")), async ({ root, click, alerts }) => {
        await click("telegramAccess.messageReceipt");
        assert.equal(root().findAllByType("button").find(node => node.props.id === `${platform}-message-receipt`).props["aria-checked"], false);
        assert.ok(alerts().includes("保存失败"));
      }, Panel);
  });
}

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
    assert.ok(!root().findAllByType("button").some(node => node.children.includes("保存并连接")));
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
      if (platform === "feishu") assert.equal(root().findAllByType("input").length, 0);
      const label = "telegramAccess.scope.title · telegramAccess.scope.collections.project";
      await click(label);
      assert.deepEqual(alerts(), ["save failed"]);
      assert.equal(root().findAllByType("button").find(node => node.props["aria-label"] === label).props["aria-checked"], true);
      fail = false;
      await click(label);
      assert.deepEqual(writes.at(-1).allowed_collections, []);
      assert.equal(root().findByProps({ className: "telegram-access__scope-summary" }).children[0], "telegramAccess.scope.empty");
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

for (const platform of ["wechat", "feishu", "telegram"]) {
  test(`${platform} 列出所有连接的用户，修改旧账号不会切走当前连接；删除需确认`, async () => {
    const Panel = platform === "telegram" ? TelegramAccessPanel : () => React.createElement(PlatformConnectionPanel, {
      platform, active: true, onConnection: () => {},
    });
    const selected = `${platform}:new`;
    const old = { id: "old-peer", user_id: "old-user", name: "Old", allowed: true,
      connection_id: `${platform}:old`, connection_name: "旧连接", connection_enabled: true };
    const recent = { ...old, id: "new-peer", name: "New", connection_id: selected };
    let current = { ...status, app_id: "app", connection_id: selected,
      peers: [recent], platform_peers: [old, recent],
      connections: [{ connection_id: old.connection_id, name: "旧连接", enabled: true },
        { connection_id: selected, name: "新连接", enabled: true }] };
    const writes = [];
    await withPanel((url, method, body) => {
      if (method === "POST") {
        writes.push({ url, body });
        if (url.includes("/authorization")) {
          assert.equal(body.peer, "old-peer");
          assert.equal(body.selected_connection_id, selected);
          current = { ...current, platform_peers: [{ ...old, allowed: false }, recent] };
        } else if (url.includes("/peers/remove")) {
          assert.equal(body.peer, "old-peer");
          assert.equal(body.selected_connection_id, selected);
          current = { ...current, platform_peers: [recent] };
        } else if (url.includes("/connections/remove")) {
          assert.equal(body.platform, platform);
          assert.equal(body.connection_id, selected);
          current = { ...current, connection_id: old.connection_id, peers: [], platform_peers: [], connections: current.connections.slice(0, 1) };
        }
      }
      return Promise.resolve(Response.json(current));
    }, async ({ root, click }) => {
      assert.equal(root().findAllByProps({ className: "telegram-access__user" }).length, 2);
      const label = platform === "telegram" ? `telegramAccess.allow · Old · ID old-user · ${old.connection_id}` : `允许 Old · ${old.connection_id}`;
      await click(label);
      assert.equal(root().findByType(MobileConnectionSelect).props.value, selected);
      assert.equal(root().findAllByType("button").find(node => node.props["aria-label"] === label).props["aria-checked"], false);
      await click("删除用户 Old");
      assert.equal(writes.length, 1, "opening confirmation must not delete anything");
      await click("取消");
      assert.equal(writes.length, 1);
      await click("删除用户 Old");
      await click("确认删除");
      assert.equal(root().findAllByProps({ className: "telegram-access__user" }).length, 1);
      await click("删除当前连接");
      await click("确认删除");
      assert.equal(root().findByType(MobileConnectionSelect).props.value, old.connection_id);
      assert.equal(root().findAllByProps({ className: "telegram-access__user" }).length, 0);
    }, Panel);
  });
}

test("删除失败保留账号与当前连接，轮询不能掩盖错误", async () => {
  const Panel = () => React.createElement(PlatformConnectionPanel, { platform: "wechat", active: true, onConnection: () => {} });
  const current = { ...status, connection_id: "wechat:1", connections: [{ connection_id: "wechat:1", name: "bot", enabled: true }] };
  await withPanel((_url, method) => Promise.resolve(method === "POST"
    ? Response.json({ error: { message: "仍有运行中的手机任务" } }, { status: 400 }) : Response.json(current)),
  async ({ root, click, alerts, poll }) => {
    await click("删除当前连接");
    await click("确认删除");
    await poll();
    assert.deepEqual(alerts(), ["仍有运行中的手机任务"]);
    assert.equal(root().findByType(MobileConnectionSelect).props.value, "wechat:1");
    assert.equal(root().findAllByProps({ className: "telegram-access__user" }).length, 1);
  }, Panel);
});

for (const platform of ["wechat", "feishu", "telegram"]) {
  test(`${platform} 两个连接开启但用户全部未授权时显示零授权，切换连接不改用户授权`, async () => {
    const Panel = platform === "telegram" ? TelegramAccessPanel : () => React.createElement(PlatformConnectionPanel, {
      platform, active: true, onConnection: () => {},
    });
    const peers = ["a", "b"].map(id => ({ id, name: id, user_id: id, allowed: false, reviewed: true,
      connection_id: `${platform}:${id}`, connection_enabled: true }));
    let writes = 0;
    await withPanel((url, method) => {
      if (method !== "GET") writes++;
      const selected = new URL(url, "http://localhost").searchParams.get("connection_id") ?? `${platform}:a`;
      return Promise.resolve(Response.json({ ...status, connection_id: selected, platform_peers: peers,
        connections: peers.map(p => ({ connection_id: p.connection_id, name: p.name, enabled: true })) }));
    }, async ({ root, poll }) => {
      const summary = () => root().findByProps({ className: "telegram-access__authorization-summary" }).children.join("");
      assert.equal(summary(), "已授权 0 / 2");
      assert.equal(root().findAllByType("select").length, 0, "use the themed selector rather than a native OS popup");
      const usersBefore = root().findAllByProps({ className: "telegram-access__user" }).map(row => row.findByType("strong").children.join(""));
      await act(async () => root().findByType(MobileConnectionSelect).props.onChange(`${platform}:b`));
      await poll();
      assert.equal(root().findByType(MobileConnectionSelect).props.value, `${platform}:b`);
      assert.equal(summary(), "已授权 0 / 2");
      assert.deepEqual(root().findAllByProps({ className: "telegram-access__user" }).map(row => row.findByType("strong").children.join("")), usersBefore);
      assert.equal(writes, 0);
    }, Panel);
  });
}

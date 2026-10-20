import assert from "node:assert/strict";
import test from "node:test";
import { act, createElement } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({ logLevel: "silent", server: { middlewareMode: true } });
const { ChatPanelErrorNotice } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatPanelErrorNotice.tsx");
const { useChatLocalFileLinks } = await vite.ssrLoadModule("/src/features/ai-panel/model/useChatLocalFileLinks.ts");
const originalWindow = globalThis.window;
const originalActEnvironment = globalThis.IS_REACT_ACT_ENVIRONMENT;
globalThis.window = {
  setTimeout: (...args) => setTimeout(...args),
  clearTimeout: (timer) => clearTimeout(timer),
};
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
test.after(async () => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
  if (originalActEnvironment === undefined) delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  else globalThis.IS_REACT_ACT_ENVIRONMENT = originalActEnvironment;
  await vite.close();
});

async function mountNotice(t, extra = {}) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let props = { message: "文件或文件夹不存在。", scopeKey: "project:session-a", ...extra };
  let renderer;
  await act(async () => { renderer = create(createElement(ChatPanelErrorNotice, props)); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  return {
    renderer,
    tick: async (ms) => { await act(async () => t.mock.timers.tick(ms)); },
    update: async (patch) => {
      props = { ...props, ...patch };
      await act(async () => renderer.update(createElement(ChatPanelErrorNotice, props)));
    },
  };
}

test("操作错误八秒后消失，普通重绘不会延长显示时间", async (t) => {
  const notice = await mountNotice(t);
  await notice.tick(4_000);
  await notice.update({});
  await notice.tick(3_999);
  assert.ok(notice.renderer.toJSON());
  await notice.tick(1);
  assert.equal(notice.renderer.toJSON(), null);
});

test("关闭提示立即生效，同样的操作再次失败仍能提示", async (t) => {
  const notice = await mountNotice(t);
  await act(async () => notice.renderer.root.findByProps({ "aria-label": "关闭提示" }).props.onClick());
  assert.equal(notice.renderer.toJSON(), null);
  await notice.update({});
  assert.equal(notice.renderer.toJSON(), null);
  await notice.update({ message: null });
  await notice.update({ message: "文件或文件夹不存在。" });
  assert.ok(notice.renderer.toJSON());
  await notice.tick(8_000);
  assert.equal(notice.renderer.toJSON(), null);
});

test("新错误有独立的显示时间，旧错误的定时器不能关掉新提示", async (t) => {
  const notice = await mountNotice(t);
  await notice.tick(7_000);
  await notice.update({ message: "复制文件路径失败。" });
  await notice.tick(1_000);
  assert.ok(notice.renderer.toJSON());
  await notice.tick(7_000);
  assert.equal(notice.renderer.toJSON(), null);
});

test("悬停和键盘焦点暂停自动关闭，离开后恢复计时", async (t) => {
  const notice = await mountNotice(t);
  const banner = () => notice.renderer.root.findByProps({ role: "status" });
  await act(async () => banner().props.onMouseEnter());
  await notice.tick(20_000);
  assert.ok(notice.renderer.toJSON());
  await act(async () => {
    banner().props.onFocusCapture();
    banner().props.onMouseLeave();
  });
  await notice.tick(20_000);
  assert.ok(notice.renderer.toJSON());
  // Moving between retry and close keeps the notice open.
  await act(async () => banner().props.onBlurCapture({ currentTarget: { contains: () => true }, relatedTarget: {} }));
  await notice.tick(20_000);
  assert.ok(notice.renderer.toJSON());
  await act(async () => banner().props.onBlurCapture({ currentTarget: { contains: () => false }, relatedTarget: null }));
  await notice.tick(8_000);
  assert.equal(notice.renderer.toJSON(), null);
});

test("切换会话隐藏旧错误，切回来也不会重新显示", async (t) => {
  const notice = await mountNotice(t);
  await notice.update({ scopeKey: "project:session-b" });
  assert.equal(notice.renderer.toJSON(), null);
  await notice.update({ scopeKey: "project:session-a" });
  assert.equal(notice.renderer.toJSON(), null);
  await notice.update({ message: null });
  await notice.update({ message: "文件或文件夹不存在。" });
  assert.ok(notice.renderer.toJSON());
});

test("保留重试入口，关闭提示不会触发重试或清除业务错误", async (t) => {
  const onRetry = t.mock.fn();
  const notice = await mountNotice(t, { onRetry });
  const retry = notice.renderer.root.findAllByType("button").find((node) => node.props.children === "重试");
  await act(async () => retry.props.onClick());
  assert.equal(onRetry.mock.callCount(), 1);
  await act(async () => notice.renderer.root.findByProps({ "aria-label": "关闭提示" }).props.onClick());
  assert.equal(onRetry.mock.callCount(), 1);
  await notice.update({});
  assert.equal(notice.renderer.toJSON(), null);
});

test("切换会话清理文件错误，旧操作的迟到错误不会污染新会话", async (t) => {
  const onError = t.mock.fn();
  let links;
  function Probe({ sessionId }) {
    links = useChatLocalFileLinks({ onError, projectId: "project", projectRootPath: "C:/project", sessionId });
    return null;
  }
  let renderer;
  await act(async () => { renderer = create(createElement(Probe, { sessionId: "a" })); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  const oldActions = links.actions;
  oldActions.onError("旧文件不存在");
  assert.equal(onError.mock.calls.at(-1).arguments[0], "旧文件不存在");
  await act(async () => renderer.update(createElement(Probe, { sessionId: "b" })));
  assert.equal(onError.mock.calls.at(-1).arguments[0], null);
  const count = onError.mock.callCount();
  oldActions.onError("迟到的旧错误");
  assert.equal(onError.mock.callCount(), count);
  links.actions.onError("新操作错误");
  assert.equal(onError.mock.calls.at(-1).arguments[0], "新操作错误");
});

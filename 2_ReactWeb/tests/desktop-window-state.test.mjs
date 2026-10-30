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
    name: "window-chrome-test-environment", enforce: "pre",
    transform(code, id) {
      const path = id.replaceAll("\\", "/");
      if (path.endsWith("/src/shared/i18n/index.ts")) {
        return "export const useI18n = () => ({ t: key => key });";
      }
      if (path.endsWith("/WindowResizeHandles.tsx")) {
        // No DOM in this renderer: preserve the real handles and their state,
        // but render the portal inline.
        return code.replace('import { createPortal } from "react-dom";',
          "const createPortal = (children: any, _target: any) => children;");
      }
    },
  }],
});
const shell = await vite.ssrLoadModule("/src/features/desktop-shell/model/desktopShellStore.ts");
const { DesktopShellProvider } = await vite.ssrLoadModule("/src/features/desktop-shell/model/useDesktopShell.tsx");
const { WindowTitlebar } = await vite.ssrLoadModule("/src/widgets/window-titlebar/ui/WindowTitlebar.tsx");
const { WindowResizeHandles } = await vite.ssrLoadModule("/src/widgets/window-resize-handles/ui/WindowResizeHandles.tsx");
after(() => vite.close());

const turn = () => new Promise(setImmediate);
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function mount(t) {
  const previous = { window: globalThis.window, document: globalThis.document, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  const window = new EventTarget(), document = new EventTarget();
  const classes = new Set();
  document.documentElement = { dataset: {}, classList: {
    add: (...names) => names.forEach(name => classes.add(name)),
    remove: (...names) => names.forEach(name => classes.delete(name)),
    toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
  } };
  document.body = {};
  document.visibilityState = "visible";
  Object.assign(window, { innerWidth: 1920, setTimeout, clearTimeout, setInterval, clearInterval });
  const state = { maximized: true, frameless: true, minWidth: 800, minHeight: 600 };
  const bounds = { x: 50, y: 30, width: 1100, height: 800 };
  const api = {
    get_window_state: async () => ({ ...state }),
    get_window_bounds: async () => ({ ...bounds }),
    get_shell_capabilities: async () => ({ nativeWindowDragSupported: true,
      nativeWindowResizeMode: "none", nativeWindowResizeSupported: false, platform: "win32" }),
    start_window_drag: async () => { state.maximized = false; return true; },
    toggle_maximize_window: async () => { state.maximized = !state.maximized; return { ...state }; },
    restore_window_for_drag: async () => { state.maximized = false; return { ...bounds }; },
  };
  window.pywebview = { api };
  globalThis.window = window;
  globalThis.document = document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  t.mock.method(globalThis, "fetch", async (_url, init) =>
    new Response(JSON.stringify({ ...JSON.parse(init.body), version: 1 })));
  let renderer;
  await act(async () => {
    renderer = create(React.createElement(DesktopShellProvider, null,
      React.createElement(WindowTitlebar), React.createElement(WindowResizeHandles)));
    await turn();
  });
  let mounted = true;
  const unmount = async () => {
    if (mounted) { mounted = false; await act(async () => renderer.unmount()); }
  };
  t.after(async () => {
    await unmount();
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  });
  return {
    api, state, window, unmount,
    control: () => renderer.root.findByProps({ className: "window-titlebar__button window-titlebar__button--maximize" }),
    handles: () => renderer.root.findAll(node => node.type === "div"
      && node.props.className?.startsWith("window-resize-handle ")).map(node => node.props.className),
    drag: () => renderer.root.findByProps({ className: "window-titlebar__drag" }).props.onPointerDown({
      button: 0, pointerId: 1, screenX: 600, screenY: 20, clientX: 600, clientY: 20,
      preventDefault() {}, currentTarget: { setPointerCapture() {}, hasPointerCapture: () => false },
    }),
  };
}

function assertRestored(context) {
  assert.equal(shell.getDesktopShellSnapshot().state.maximized, false);
  assert.equal(context.control().props["aria-label"], "common.windowControls.maximize");
  assert.equal(context.handles().length, 8);
  for (const edge of ["top", "right", "top-right"]) {
    assert.ok(context.handles().includes(`window-resize-handle window-resize-handle--${edge}`));
  }
}

test("原生拖动还原同步按钮和八个缩放边缘，不依赖失焦再聚焦", async t => {
  const context = await mount(t);
  assert.equal(context.control().props["aria-label"], "common.windowControls.restore");
  assert.equal(context.handles().length, 0);
  await act(async () => { context.drag(); await turn(); });
  assertRestored(context);
  await act(async () => { await context.control().props.onClick(); await turn(); });
  assert.equal(context.handles().length, 0);
  await act(async () => { context.drag(); await turn(); });
  assertRestored(context);
});

test("原生拖动返回失败也可能已经还原，读取实际状态", async t => {
  const context = await mount(t);
  context.api.start_window_drag = async () => { context.state.maximized = false; return false; };
  let started;
  await act(async () => { started = await shell.startDesktopShellNativeDrag(600, 20, 0.5, 20); });
  assert.equal(started, false);
  assertRestored(context);
});

test("拖动结束实际仍是最大化时，不凭拖动动作强行改为普通窗口", async t => {
  const context = await mount(t);
  context.api.start_window_drag = async () => true;
  await act(async () => { await shell.startDesktopShellNativeDrag(600, 20, 0.5, 20); });
  assert.equal(context.control().props["aria-label"], "common.windowControls.restore");
  assert.equal(context.handles().length, 0);
});

test("拖动前开始的旧状态查询迟到，不覆盖已还原的状态", async t => {
  const context = await mount(t);
  const pending = deferred();
  const oldState = { ...context.state };
  context.api.get_window_state = () => pending.promise;
  await act(async () => { context.window.dispatchEvent(new Event("focus")); await turn(); });
  context.api.get_window_state = async () => ({ ...context.state });
  await act(async () => { await shell.startDesktopShellNativeDrag(600, 20, 0.5, 20); });
  assertRestored(context);
  await act(async () => { pending.resolve(oldState); await turn(); });
  assertRestored(context);
});

test("原生拖动抛错后仍核对窗口状态，保留原始失败", async t => {
  const context = await mount(t);
  context.api.start_window_drag = async () => { context.state.maximized = false; throw new Error("drag failed"); };
  await act(async () => {
    await assert.rejects(shell.startDesktopShellNativeDrag(600, 20, 0.5, 20), /drag failed/);
  });
  assertRestored(context);
});

test("桥已卸载时迟到的拖动结果不恢复旧界面状态", async t => {
  const context = await mount(t);
  const pending = deferred();
  context.api.start_window_drag = () => pending.promise;
  const drag = shell.startDesktopShellNativeDrag(600, 20, 0.5, 20);
  await context.unmount();
  pending.resolve(true);
  await drag;
  assert.equal(shell.getDesktopShellSnapshot().state.available, false);
});

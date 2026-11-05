import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import React from 'react';
import { act, create } from 'react-test-renderer';
import ts from 'typescript';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);

async function mount(t, { languageReady = true, themeReady = true } = {}) {
  let dismissed = 0, serial = 0, renderer;
  const frames = new Map();
  const oldWindow = globalThis.window;
  globalThis.window = Object.assign(new EventTarget(), {
    requestAnimationFrame: fn => { frames.set(++serial, fn); return serial; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout, clearTimeout,
  });
  const oldDocument = globalThis.document;
  globalThis.document = new EventTarget();
  const passthrough = ({ children }) => children;
  const mocks = {
    '@/shared/i18n': { I18nProvider: ({ children }) => languageReady ? children : null },
    './model/useAppTheme': { useAppTheme: () => ({ isBootstrapping: !themeReady }) },
    './model/useBrowserShellGuards': { useBrowserShellGuards() {} },
    './ui/WorkspaceErrorBoundary': { WorkspaceErrorBoundary: passthrough },
    '../features/desktop-shell/model/useDesktopShell': { DesktopShellProvider: passthrough },
    '../features/software-update/ui/StartupSoftwareUpdatePrompt': { StartupSoftwareUpdatePrompt: () => null },
    '../features/announcements/ui/StartupAnnouncementPrompt': { StartupAnnouncementPrompt: () => null },
    '../features/desktop-shell/model/desktopShellStore': { revealDesktopShellWindow: async () => true },
    // Catalogs never settle: usable frame must still replace the launch cover.
    '../pages/workspace/ui/WorkspacePage': { WorkspacePage: () => React.createElement('div', null, 'catalog loading') },
    '../widgets/app-frame/ui/AppFrame': { AppFrame: passthrough },
    '../shared/model/startup-timing/startupTiming': {
      markFrontendStartup() {}, dismissFrontendBootPlaceholder() { dismissed += 1; },
    },
  };
  const source = ts.transpileModule(readFileSync(new URL('../src/app/App.tsx', import.meta.url), 'utf8'), {
    fileName: 'App.tsx', compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`)(
    name => name in mocks ? mocks[name] : require(name), module, module.exports,
  );
  const render = () => React.createElement(React.StrictMode, null,
    React.createElement(module.exports.App, { initialTheme: {}, initialWorkspaceLayoutPreferences: null }));
  await act(async () => { renderer = create(render()); });
  t.after(async () => {
    if (renderer) await act(async () => renderer.unmount());
    globalThis.window = oldWindow;
    globalThis.document = oldDocument;
  });
  return {
    get dismissed() { return dismissed; },
    get frameCount() { return frames.size; },
    async paint() {
      const pending = [...frames.values()]; frames.clear();
      await act(async () => { for (const fn of pending) fn(); });
    },
    async ready(language, theme) {
      languageReady = language; themeReady = theme;
      await act(async () => renderer.update(render()));
    },
    async unmount() { await act(async () => renderer.unmount()); renderer = null; },
  };
}

test('a painted workspace is usable even while catalog requests remain pending', async t => {
  const h = await mount(t);
  assert.equal(h.dismissed, 0);
  await h.paint(); await h.paint();
  assert.equal(h.dismissed, 1);
});

test('cover stays until localized frame and startup theme are ready', async t => {
  const h = await mount(t, { languageReady: false, themeReady: false });
  await h.paint(); await h.paint();
  assert.equal(h.dismissed, 0);
  await h.ready(true, false);
  await h.paint(); await h.paint();
  assert.equal(h.dismissed, 0);
  await h.ready(true, true);
  await h.paint(); await h.paint();
  assert.equal(h.dismissed, 1);
});

test('unmounted frame cannot later dismiss another startup cover', async t => {
  const h = await mount(t);
  await h.paint();
  await h.unmount();
  assert.equal(h.frameCount, 0);
  await h.paint();
  assert.equal(h.dismissed, 0);
});

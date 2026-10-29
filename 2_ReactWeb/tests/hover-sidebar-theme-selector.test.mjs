import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import { test } from "node:test";
import React, { act } from "react";
import { create } from "react-test-renderer";
import ts from "typescript";

const require = createRequire(import.meta.url);
const file = "src/widgets/hover-sidebar/ui/HoverSidebarThemeSelector.tsx";
const code = ts.transpileModule(readFileSync(new URL("../" + file, import.meta.url), "utf8"), {
  fileName: file,
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;
const labels = { "sidebar.theme.select": "选择主题", "sidebar.theme.search": "搜索主题",
  "sidebar.theme.all": "全部主题", "sidebar.theme.categories": "主题分类", "sidebar.theme.empty": "没有主题" };
const module = { exports: {} };
vm.runInThisContext("(function(require,module,exports){" + code + "\n})", { filename: file })(
  name => name === "../../../shared/i18n" ? { useI18n: () => ({ t: key => labels[key] ?? key }) }
    : name === "@phosphor-icons/react" ? Object.fromEntries(["CaretUp", "Check", "MagnifyingGlass", "Palette"]
      .map(name => [name, props => React.createElement("svg", props)])) : require(name), module, module.exports);
const { HoverSidebarThemeSelector } = module.exports;

async function mount(t) {
  const previous = { window: globalThis.window, document: globalThis.document,
    Node: globalThis.Node, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  const document = new EventTarget(), window = new EventTarget();
  let renderer;
  class Element {
    constructor(parent = null) { this.parent = parent; this.focusVisible = false; }
    contains(node) { for (; node; node = node.parent) if (node === this) return true; return false; }
    matches(selector) { return selector === ":focus-visible" && this.focusVisible; }
    focus() { document.activeElement = this; selector().props.onFocus({ target: this }); }
  }
  const root = new Element(), triggerNode = new Element(root), searchNode = new Element(root), outside = new Element();
  document.activeElement = outside;
  globalThis.window = window;
  globalThis.document = document;
  globalThis.Node = Element;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const calls = { opened: 0, selected: [] };
  let props = {
    categories: [{ category_id: "base", name: "基础主题" }, { category_id: "market", name: "市场主题" }],
    isSidebarExpanded: true,
    themeProjects: [
      { root_path: "C:\\Data\\themes\\dark-gold", category_id: "base" },
      { root_path: "/Data/themes/light", category_id: "base" },
      { root_path: "/Data/themes/remote", category_id: "market" },
    ],
    themeControl: { activeThemeId: "dark-gold", activeThemeName: "暗金", mode: "dark", isLoading: false,
      themes: [{ id: "dark-gold", name: "暗金" }, { id: "light", name: "浅色" }, { id: "remote", name: "远山" }],
      onOpenThemeMenu() { calls.opened++; }, onSelectTheme(id) { calls.selected.push(id); } },
  };
  const selector = () => renderer.root.findAll(node => node.type === "div"
    && node.props.className?.split(" ").includes("hover-sidebar__theme-selector"))[0];
  const trigger = () => renderer.root.findByProps({ className: "hover-sidebar__theme-trigger" });
  const options = () => renderer.root.findAll(node => node.type === "button" && node.props.role === "option");
  const open = () => trigger().props["aria-expanded"];
  const enter = () => act(() => selector().props.onPointerEnter());
  const leave = () => act(() => selector().props.onPointerLeave());
  await act(async () => { renderer = create(React.createElement(HoverSidebarThemeSelector, props), {
    createNodeMock: node => node.props.className?.split(" ").includes("hover-sidebar__theme-selector") ? root
      : node.props.className === "hover-sidebar__theme-trigger" ? triggerNode
      : node.props.className === "hover-sidebar__theme-search-input" ? searchNode : null,
  }); });
  t.after(async () => {
    await act(async () => renderer.unmount());
    for (const [key, value] of Object.entries({ window: previous.window, document: previous.document,
      Node: previous.Node, IS_REACT_ACT_ENVIRONMENT: previous.act })) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  });
  const dispatch = async (target, type, properties = {}) => {
    const event = new Event(type);
    for (const [key, value] of Object.entries(properties)) Object.defineProperty(event, key, { value });
    await act(async () => target.dispatchEvent(event));
  };
  return { calls, document, window, root, outside, triggerNode, searchNode, selector, trigger, options,
    open, enter, leave, dispatch, renderer,
    async update(patch) { props = { ...props, ...patch }; await act(async () => renderer.update(
      React.createElement(HoverSidebarThemeSelector, props))); } };
}

test("悬停打开，移出关闭；点击按钮和搜索框不会固定弹窗", async t => {
  const view = await mount(t);
  assert.equal(view.open(), false);
  await view.enter();
  assert.equal(view.open(), true);
  assert.equal(view.calls.opened, 1);
  let prevented = false;
  await act(async () => {
    view.selector().props.onPointerDownCapture();
    view.trigger().props.onPointerDown({ button: 0, preventDefault() { prevented = true; } });
    view.triggerNode.focus();
  });
  assert.equal(prevented, true);
  await view.leave();
  assert.equal(view.open(), false);
  await view.enter();
  await act(async () => { view.selector().props.onPointerDownCapture(); view.searchNode.focus(); });
  await view.leave();
  assert.equal(view.open(), false);
  assert.equal(view.calls.opened, 2);
});

test("键盘可打开并聚焦搜索，Esc 关闭并返回按钮且不重新打开", async t => {
  const view = await mount(t);
  view.triggerNode.focusVisible = true;
  await act(async () => view.triggerNode.focus());
  assert.equal(view.open(), true);
  await act(async () => view.trigger().props.onKeyDown({ key: "ArrowUp", preventDefault() {} }));
  assert.equal(view.document.activeElement, view.searchNode);
  const panel = view.renderer.root.findByProps({ role: "region" });
  assert.equal(view.trigger().props["aria-controls"], panel.props.id);
  await view.dispatch(view.document, "keydown", { key: "Escape" });
  assert.equal(view.open(), false);
  assert.equal(view.document.activeElement, view.triggerNode);
  // The focused trigger remains usable after an explicit dismissal.
  await act(async () => view.trigger().props.onKeyDown({ key: "Enter", preventDefault() {} }));
  assert.equal(view.open(), true);
  assert.equal(view.document.activeElement, view.searchNode);
});

test("内部切换焦点保持打开，键盘焦点离开后收起", async t => {
  const view = await mount(t);
  view.triggerNode.focusVisible = true;
  await act(async () => view.triggerNode.focus());
  await act(async () => view.selector().props.onBlur({ currentTarget: view.root, relatedTarget: view.searchNode }));
  assert.equal(view.open(), true);
  await act(async () => view.selector().props.onBlur({ currentTarget: view.root, relatedTarget: view.outside }));
  assert.equal(view.open(), false);
});

test("分类、跨分类搜索、主题选择保留，离开后重新打开重置搜索", async t => {
  const view = await mount(t);
  await view.enter();
  assert.equal(view.options().length, 2);
  const category = view.renderer.root.findAll(node => node.type === "button"
    && node.props.className?.startsWith("hover-sidebar__theme-category"))
    .find(node => node.findByProps({ className: "hover-sidebar__theme-category-label" }).children[0] === "市场主题");
  await act(async () => category.props.onClick());
  assert.equal(view.options().length, 1);
  assert.equal(view.options()[0].findByProps({ className: "hover-sidebar__theme-option-label" }).children[0], "远山");
  await act(async () => view.renderer.root.findByType("input").props.onChange({ target: { value: "浅色" } }));
  assert.equal(view.options().length, 1);
  await act(async () => view.options()[0].props.onClick({ preventDefault() {}, stopPropagation() {} }));
  assert.deepEqual(view.calls.selected, ["light"]);
  assert.equal(view.open(), true);
  await view.leave();
  await view.enter();
  assert.equal(view.renderer.root.findByType("input").props.value, "");
  assert.equal(view.options().length, 2);
});

test("点击外部、窗口失焦或侧栏收起都关闭；内部点击不关闭", async t => {
  const view = await mount(t);
  await view.enter();
  await view.dispatch(view.document, "pointerdown", { target: view.searchNode });
  assert.equal(view.open(), true);
  await view.dispatch(view.document, "pointerdown", { target: view.outside });
  assert.equal(view.open(), false);
  await view.enter();
  await view.dispatch(view.window, "blur");
  assert.equal(view.open(), false);
  await view.enter();
  await view.update({ isSidebarExpanded: false });
  assert.equal(view.open(), false);
  await view.update({ isSidebarExpanded: true });
  assert.equal(view.open(), false);
});

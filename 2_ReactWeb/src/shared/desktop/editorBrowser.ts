import { useSyncExternalStore } from "react";
import type { EditorWebAppearanceMode, EditorWebPalette, EditorWebRecordKind, EditorWebRecordsPage, EditorWebState } from "../types/desktopShell";

function onBridgeReady(notify: () => void) {
  window.addEventListener("pywebviewready", notify);
  return () => window.removeEventListener("pywebviewready", notify);
}

export function isEditorBrowserAvailable() {
  return typeof window !== "undefined" && navigator.platform.startsWith("Win") && Boolean(window.pywebview?.api?.editor_web_layout);
}

export function useEditorBrowserAvailable() {
  return useSyncExternalStore(onBridgeReady, isEditorBrowserAvailable);
}

export function watchEditorWebState(id: string, update: (state: EditorWebState) => void,
  preview: (requestId: string, imageUrl: string) => void) {
  const webview = (window as Window & { chrome?: { webview?: EventTarget } }).chrome?.webview;
  function receive(event: Event) {
    const message = (event as MessageEvent).data;
    if (message?.id !== id) return;
    if (message.type === "editor-web-state") update(message.state);
    if (message.type === "editor-web-preview") {
      if (message.png) preview(message.request, "data:image/png;base64," + message.png);
      else if (message.jpeg) preview(message.request, "data:image/jpeg;base64," + message.jpeg);
    }
  }
  webview?.addEventListener("message", receive);
  return () => webview?.removeEventListener("message", receive);
}

// pywebview dispatches each call on a separate thread. Preserve React's hide/show/close order.
let lastCall = Promise.resolve();
function enqueue<T>(call: () => Promise<T> | undefined) {
  const next = lastCall.then(call);
  lastCall = next.then(() => {}, () => {});
  return next;
}

// One reader per open menu. Older shells expose only a snapshot of the last 100 records.
export function createEditorRecordsReader(kind: EditorWebRecordKind) {
  let recent: Promise<EditorWebRecordsPage["items"]> | undefined;
  return async (query: string, cursor: string | null): Promise<EditorWebRecordsPage> => {
    const api = window.pywebview?.api;
    if (kind === "downloads" && query) {
      if (api?.editor_web_search_downloads) return api.editor_web_search_downloads(query, cursor);
    } else if (api?.editor_web_records_page) {
      return api.editor_web_records_page(kind, query, cursor);
    }
    if (!recent) {
      recent = kind === "history"
        ? api?.editor_web_history?.().then(rows => rows.map(r => ({ title: r.title, target: r.url, time: r.visitedAt })))
        : api?.editor_web_downloads?.().then(rows => rows.map(r => ({ title: r.name, target: r.path, time: r.completedAt })));
      if (!recent) throw new Error("请重启天策以读取网页记录。");
      recent.catch(() => { recent = undefined; });
    }
    const rows = await recent;
    const term = query.toLowerCase();
    const matches = term ? rows.filter(r => r.title.toLowerCase().includes(term) || r.target.toLowerCase().includes(term)) : rows;
    const start = Number(cursor);
    const end = start + 25;
    return { items: matches.slice(start, end), nextCursor: end < matches.length ? String(end) : null, recentOnly: rows.length >= 100 };
  };
}

export const editorBrowser = {
  appearance: (mode: EditorWebAppearanceMode, colors: EditorWebPalette) =>
    enqueue(() => window.pywebview?.api?.editor_web_appearance?.(mode, colors)),
  layout: (id: string, url: string, edges: number[] | null, workspaceRoot?: string) => enqueue(() => {
    const layout = window.pywebview?.api?.editor_web_layout;
    // A running desktop shell can be older than the hot-reloaded frontend.
    return workspaceRoot && layout && layout.length >= 4 ? layout(id, url, edges, workspaceRoot) : layout?.(id, url, edges);
  }),
  cover: (id: string, requestId: string) => enqueue(() => {
    const api = window.pywebview?.api;
    if (api?.editor_web_present_cover) return api.editor_web_cover?.(id, requestId, true);
    return api?.editor_web_cover ? api.editor_web_cover(id, requestId) : api?.editor_web_layout?.(id, "", null);
  }),
  presentCover: (id: string, requestId: string) =>
    enqueue(() => window.pywebview?.api?.editor_web_present_cover?.(id, requestId)),
  command: (id: string, action: string, url = "") =>
    enqueue(() => window.pywebview?.api?.editor_web_command?.(id, action, url)),
  close: (id: string) => enqueue(() => window.pywebview?.api?.editor_web_close?.(id)),
};

export function normalizeWebAddress(input: string) {
  const value = input.trim();
  if (!value || /\s/.test(value)) throw new Error("请输入有效网址");
  const local = /^(?:localhost|127\.\d+\.\d+\.\d+|\[::1\])(?=[:/?#]|$)/i.test(value);
  const explicitScheme = /^[a-z][a-z\d+.-]*:/i.test(value) && !/^[\w.-]+:\d+(?:[/?#]|$)/.test(value);
  const url = new URL(explicitScheme ? value : (local ? "http://" : "https://") + value);
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
    throw new Error("请输入 HTTP 或 HTTPS 网址");
  }
  return url.href;
}

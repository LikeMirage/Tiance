import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { getEditorDocumentPath } from "../../../entities/editor/model/editorWorkspaceFileReference";
import { normalizeWebAddress } from "../../../shared/desktop/editorBrowser";
import { webKey } from "../../document-tabs/model/workspaceTabEntries";
import { DocumentRevealError, parseDocumentRevealTarget, type DocumentRevealResult, type DocumentRevealTarget } from "../../../entities/editor/model/documentReveal";
import {
  isPinnedDocumentTab,
  isProjectConversationOverviewTab,
  normalizeWorkspacePath,
} from "../../document-tabs/model/documentTabUtils";
import type {
  ClientToolExecutionResult,
  ClientToolRegistration,
} from "./clientToolBridge";
import { executeBackgroundEditorTabsClientTool, serializeWebTab } from "./backgroundEditorTabsClientTool";

export const EDITOR_TABS_TOOL_NAME = "editor_tabs_manager";
export const EDITOR_TABS_CAPABILITY = Object.freeze({
  name: "editor.tabs",
  version: 4,
});

type EditorTabsClientToolOptions = {
  getEditorTabs: () => EditorTabsCapability;
  getProjectId: () => string | null;
};

export type EditorTabsCapability = {
  closeTab: (tabId: string) => void;
  getSnapshot: () => EditorTabsSnapshot;
  canOpenWebTab: () => boolean;
  openWebTab: (url: string, projectId: string) => string;
  openProjectFile: (projectId: string, path: string) => Promise<void>;
  revealProjectFile: (projectId: string, path: string, target: DocumentRevealTarget, signal: AbortSignal) => Promise<DocumentRevealResult>;
  selectTab: (tabId: string) => void;
};

type EditorTabsSnapshot = {
  activeTabId: string | null;
  tabs: DocumentTab[];
};

export function createEditorTabsClientToolRegistration(
  options: EditorTabsClientToolOptions,
): ClientToolRegistration {
  return {
    capability: EDITOR_TABS_CAPABILITY,
    execute: (request, context) => executeEditorTabsClientTool(request, options, context?.signal ?? new AbortController().signal),
  };
}

async function executeEditorTabsClientTool(
  request: ChatClientToolRequestEvent,
  options: EditorTabsClientToolOptions,
  signal: AbortSignal,
): Promise<ClientToolExecutionResult> {
  const currentProjectId = options.getProjectId();
  const projectId = readString(request.project_id);
  if (!projectId) {
    return fail("工具请求没有指定项目，无法管理编辑器标签页。");
  }

  const args = parseArguments(request.arguments);
  if (!args.ok) return fail(args.error);

  const action = readString(args.value.action);
  if (!action) return fail("缺少 action 参数。");
  const requestedPath = readPath(args.value.path);
  const requestedPaths = readPathList(args.value.paths);
  let url = "";
  const tabId = readString(args.value.tab_id);
  if (action === "open_url") {
    const address = readString(args.value.url);
    try {
      if (!/^https?:\/\//i.test(address)) throw new Error();
      url = normalizeWebAddress(address);
    } catch {
      return fail("open_url 需要完整的 HTTP 或 HTTPS 网址。", { action, error_code: "INVALID_URL" });
    }
  }
  if (action === "focus_web" && !tabId) return fail("focus_web 需要网页标签的 tab_id。", { action });

  if (action === "reveal_file") {
    if (!requestedPath) return fail("reveal_file 需要 path 参数。", { error_code: "INVALID_PATH" });
    try {
      const target = parseDocumentRevealTarget(args.value.target);
      if (projectId !== currentProjectId) {
        return fail("目标项目未在当前编辑器前台打开，请先切换到该项目再定位。", { action, error_code: "PROJECT_NOT_ACTIVE" });
      }
      const documentTabs = options.getEditorTabs();
      const location = await documentTabs.revealProjectFile(projectId, requestedPath, target, signal);
      const snapshot = documentTabs.getSnapshot();
      const tab = findProjectTabByPath(getProjectTabs(snapshot, projectId), requestedPath);
      if (!tab || snapshot.activeTabId !== tab.id || signal.aborted) {
        return fail("定位完成前目标标签已切换或请求已取消。", { action, error_code: "NAVIGATION_INTERRUPTED" });
      }
      return ok({ action, path: requestedPath, displayed: true, location, revealed_tab: serializeTab(tab, snapshot.activeTabId) });
    } catch (error) {
      return fail(error instanceof Error ? error.message : "文件定位失败。", {
        action, path: requestedPath,
        error_code: error instanceof DocumentRevealError ? error.code : "REVEAL_FAILED",
        ...(error instanceof DocumentRevealError ? error.details : {}),
      });
    }
  }

  if (projectId !== currentProjectId) {
    return executeBackgroundEditorTabsClientTool({
      action,
      path: requestedPath,
      paths: requestedPaths,
      projectId,
      url,
      tabId,
    });
  }

  const documentTabs = options.getEditorTabs();
  const initialSnapshot = documentTabs.getSnapshot();
  const projectTabs = getProjectTabs(initialSnapshot, projectId);
  if (action === "list_tabs") {
    const tabs = projectTabs.map(tab => serializeTab(tab, initialSnapshot.activeTabId));
    return ok({
      action,
      tabs,
      active_tab_id: tabs.find(tab => tab.is_active)?.id ?? null,
    });
  }

  if (action === "open_url" || action === "focus_web") {
    if (!documentTabs.canOpenWebTab()) return fail("当前客户端无法在编辑器中显示网页。", { action, error_code: "WEB_VIEW_UNAVAILABLE" });
    const webTabs = projectTabs.filter(tab => tab.kind === "web");
    const matches = action === "focus_web"
      ? webTabs.filter(tab => webKey(tab) === tabId)
      : webTabs.filter(tab => tab.displayPath === url);
    const existing = matches.find(tab => tab.id === initialSnapshot.activeTabId) ?? matches[0];
    if (!existing && action === "focus_web") return fail("当前项目没有这个网页标签。", { action, tab_id: tabId });
    const id = existing?.id ?? documentTabs.openWebTab(url, projectId);
    if (existing) documentTabs.selectTab(id);
    const latest = documentTabs.getSnapshot();
    const tab = getProjectTabs(latest, projectId).find(item => item.id === id);
    if (!tab || latest.activeTabId !== id) return fail("网页标签未能选中。", { action });
    const result = serializeTab(tab, id);
    return action === "open_url" ? ok({ action, opened_tab: result }) : ok({ action, focused_tab: result });
  }

  if (action === "open_file") {
    const filePath = requestedPath;
    if (!filePath) return fail("open_file 需要 path 参数。");
    await documentTabs.openProjectFile(projectId, filePath);
    const latestDocumentTabs = documentTabs.getSnapshot();
    const openedTab = findProjectTabByPath(
      latestDocumentTabs.tabs.filter((tab) => tab.projectId === projectId),
      filePath,
    );
    if (!openedTab) {
      return fail("前端未能打开目标文件，可能是路径不存在或文件类型不支持。", {
        action,
        path: filePath,
      });
    }
    return ok({
      action,
      opened_path: filePath,
      opened_tab: serializeTab(openedTab, latestDocumentTabs.activeTabId),
    });
  }

  if (action === "focus_file") {
    const filePath = requestedPath;
    if (!filePath) return fail("focus_file 需要 path 参数。");
    const tab = findProjectTabByPath(projectTabs, filePath);
    if (!tab) {
      return fail("目标文件当前没有打开。", {
        action,
        path: filePath,
        found: false,
      });
    }
    documentTabs.selectTab(tab.id);
    const latestDocumentTabs = documentTabs.getSnapshot();
    const focusedTab = findProjectTabByPath(
      getProjectTabs(latestDocumentTabs, projectId),
      filePath,
    );
    if (!focusedTab || latestDocumentTabs.activeTabId !== focusedTab.id) {
      return fail("前端未能聚焦目标文件。", {
        action,
        path: filePath,
      });
    }
    return ok({
      action,
      focused_tab: serializeTab(focusedTab, latestDocumentTabs.activeTabId),
    });
  }

  if (action === "close_clean_tabs") {
    const targetTabs = requestedPaths.length > 0
      ? projectTabs.filter((tab) => requestedPaths.includes(tabPath(tab) ?? ""))
      : projectTabs;
    const closeResult = closeCleanTabs(documentTabs, targetTabs);
    const latestDocumentTabs = documentTabs.getSnapshot();
    const stillOpen = findStillOpenTabs(
      latestDocumentTabs,
      projectId,
      closeResult.closed,
    );
    if (stillOpen.length > 0) {
      return fail("前端未能关闭部分标签页。", {
        action,
        ...closeResult,
        still_open: stillOpen,
      });
    }
    return ok({
      action,
      ...closeResult,
    });
  }

  if (action === "close_others_clean") {
    const keepPath = requestedPath;
    const keepTab = keepPath
      ? findProjectTabByPath(projectTabs, keepPath)
      : projectTabs.find((tab) => tab.id === initialSnapshot.activeTabId) ?? null;
    if (!keepTab) {
      return fail("没有找到需要保留的当前项目标签页。", {
        action,
        path: keepPath,
      });
    }
    documentTabs.selectTab(keepTab.id);
    const closeResult = closeCleanTabs(
      documentTabs,
      projectTabs.filter((tab) => tab.id !== keepTab.id),
    );
    const latestDocumentTabs = documentTabs.getSnapshot();
    const latestProjectTabs = getProjectTabs(latestDocumentTabs, projectId);
    const latestKeepTab = keepPath
      ? findProjectTabByPath(latestProjectTabs, keepPath)
      : latestProjectTabs.find((tab) => tab.id === keepTab.id) ?? null;
    const stillOpen = findStillOpenTabs(
      latestDocumentTabs,
      projectId,
      closeResult.closed,
    );
    if (!latestKeepTab) {
      return fail("前端未能保留目标标签页。", {
        action,
        path: keepPath,
        ...closeResult,
      });
    }
    if (stillOpen.length > 0) {
      return fail("前端未能关闭部分其它标签页。", {
        action,
        path: keepPath,
        kept_tab: serializeTab(latestKeepTab, latestDocumentTabs.activeTabId),
        ...closeResult,
        still_open: stillOpen,
      });
    }
    return ok({
      action,
      kept_tab: serializeTab(latestKeepTab, latestDocumentTabs.activeTabId),
      ...closeResult,
    });
  }

  return fail(`不支持的标签页操作：${action}`);
}

function getProjectTabs(
  snapshot: EditorTabsSnapshot,
  projectId: string,
) {
  return snapshot.tabs.filter(
    (tab) => tab.projectId === projectId && !isProjectConversationOverviewTab(tab),
  );
}

function closeCleanTabs(
  documentTabs: EditorTabsCapability,
  tabs: DocumentTab[],
) {
  const activeTabId = documentTabs.getSnapshot().activeTabId;
  const closed: ReturnType<typeof serializeTab>[] = [];
  const skippedDirty: ReturnType<typeof serializeTab>[] = [];
  const skippedPinned: ReturnType<typeof serializeTab>[] = [];
  for (const tab of tabs) {
    const serialized = serializeTab(tab, activeTabId);
    if (tab.isDirty) {
      skippedDirty.push(serialized);
      continue;
    }
    if (isPinnedDocumentTab(tab)) {
      skippedPinned.push(serialized);
      continue;
    }
    documentTabs.closeTab(tab.id);
    closed.push(serialized);
  }
  return {
    closed,
    closed_count: closed.length,
    skipped_dirty: skippedDirty,
    skipped_dirty_count: skippedDirty.length,
    skipped_pinned: skippedPinned,
    skipped_pinned_count: skippedPinned.length,
  };
}

function findStillOpenTabs(
  snapshot: EditorTabsSnapshot,
  projectId: string,
  tabs: ReturnType<typeof serializeTab>[],
) {
  const latestProjectTabs = getProjectTabs(snapshot, projectId);
  const openIds = new Set(latestProjectTabs.map(tab => tab.kind === "web" ? webKey(tab) : tab.id));
  return tabs.filter(tab => openIds.has(tab.id));
}

function findProjectTabByPath(tabs: DocumentTab[], path: string) {
  const normalizedPath = normalizeWorkspacePath(path);
  return tabs.find((tab) => tabPath(tab) === normalizedPath) ?? null;
}

function serializeTab(tab: DocumentTab, activeTabId: string | null) {
  if (tab.kind === "web") {
    return serializeWebTab({ kind: "web", id: webKey(tab), title: tab.title, url: tab.displayPath, active: tab.id === activeTabId });
  }
  return {
    id: tab.id,
    title: tab.title,
    path: tabPath(tab),
    kind: tab.kind,
    is_active: tab.id === activeTabId,
    is_dirty: tab.isDirty,
    is_missing: tab.isMissing,
    save_state: tab.saveState,
  };
}

function tabPath(tab: DocumentTab) {
  if (tab.kind === "web") return null;
  if (tab.fileSource?.kind === "local") return getEditorDocumentPath(tab);
  const path = tab.projectFilePath ?? tab.filePath ?? tab.displayPath;
  return path ? normalizeWorkspacePath(path) : null;
}

function parseArguments(rawArguments: string): {
  ok: true;
  value: Record<string, unknown>;
} | {
  ok: false;
  error: string;
} {
  try {
    const value = rawArguments.trim() ? JSON.parse(rawArguments) : {};
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, error: "工具参数必须是 JSON 对象。" };
    }
    return { ok: true, value: value as Record<string, unknown> };
  } catch {
    return { ok: false, error: "工具参数不是合法 JSON。" };
  }
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readPath(value: unknown): string {
  return normalizeWorkspacePath(readString(value));
}

function readPathList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(readPath)
    .filter(Boolean);
}

function ok(content: Record<string, unknown>): ClientToolExecutionResult {
  return { ok: true, content };
}

function fail(error: string, content: Record<string, unknown> = {}): ClientToolExecutionResult {
  return { ok: false, content, error };
}

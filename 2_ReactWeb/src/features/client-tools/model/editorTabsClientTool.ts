import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { useDocumentTabs } from "../../document-tabs/model/useDocumentTabs";
import {
  getPathName,
  isPinnedDocumentTab,
  isProjectConversationOverviewTab,
  normalizeWorkspacePath,
} from "../../document-tabs/model/documentTabUtils";
import type {
  ClientToolExecutionResult,
  ClientToolRegistration,
} from "./clientToolBridge";
import { executeBackgroundEditorTabsClientTool } from "./backgroundEditorTabsClientTool";

export const EDITOR_TABS_TOOL_NAME = "editor_tabs_manager";

type EditorTabsClientToolOptions = {
  getDocumentTabs: () => ReturnType<typeof useDocumentTabs>;
  getProjectId: () => string | null;
};

export function createEditorTabsClientToolRegistration(
  options: EditorTabsClientToolOptions,
): ClientToolRegistration {
  return {
    name: EDITOR_TABS_TOOL_NAME,
    execute: (request) => executeEditorTabsClientTool(request, options),
  };
}

async function executeEditorTabsClientTool(
  request: ChatClientToolRequestEvent,
  options: EditorTabsClientToolOptions,
): Promise<ClientToolExecutionResult> {
  const currentProjectId = options.getProjectId();
  const projectId = readString(request.project_id) || currentProjectId;
  if (!projectId) {
    return fail("工具请求没有指定项目，无法管理编辑器标签页。");
  }

  const args = parseArguments(request.arguments);
  if (!args.ok) return fail(args.error);

  const action = readString(args.value.action);
  if (!action) return fail("缺少 action 参数。");
  const requestedPath = readPath(args.value.path);
  const requestedPaths = readPathList(args.value.paths);

  if (projectId !== currentProjectId) {
    return executeBackgroundEditorTabsClientTool({
      action,
      path: requestedPath,
      paths: requestedPaths,
      projectId,
    });
  }

  const documentTabs = options.getDocumentTabs();
  const projectTabs = getProjectTabs(options, projectId);
  if (action === "list_tabs") {
    return ok({
      action,
      tabs: projectTabs.map((tab) => serializeTab(tab, documentTabs.activeTabId)),
      active_tab_id: documentTabs.activeTabId,
    });
  }

  if (action === "open_file") {
    const filePath = requestedPath;
    if (!filePath) return fail("open_file 需要 path 参数。");
    await documentTabs.openNode({
      id: `project:${projectId}:${filePath}`,
      kind: "file",
      name: getPathName(filePath),
      path: filePath,
    }, {
      projectFilePath: filePath,
      projectId,
    });
    await waitForUiUpdate();
    const latestDocumentTabs = options.getDocumentTabs();
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
    await waitForUiUpdate();
    const latestDocumentTabs = options.getDocumentTabs();
    const focusedTab = findProjectTabByPath(
      getProjectTabs(options, projectId),
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
    await waitForUiUpdate();
    const stillOpen = findStillOpenTabs(options, projectId, closeResult.closed);
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
      : projectTabs.find((tab) => tab.id === documentTabs.activeTabId) ?? null;
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
    await waitForUiUpdate();
    const latestDocumentTabs = options.getDocumentTabs();
    const latestProjectTabs = getProjectTabs(options, projectId);
    const latestKeepTab = keepPath
      ? findProjectTabByPath(latestProjectTabs, keepPath)
      : latestProjectTabs.find((tab) => tab.id === keepTab.id) ?? null;
    const stillOpen = findStillOpenTabs(options, projectId, closeResult.closed);
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
  options: EditorTabsClientToolOptions,
  projectId: string,
) {
  return options.getDocumentTabs().tabs.filter(
    (tab) => tab.projectId === projectId && !isProjectConversationOverviewTab(tab),
  );
}

function closeCleanTabs(
  documentTabs: ReturnType<typeof useDocumentTabs>,
  tabs: DocumentTab[],
) {
  const closed: ReturnType<typeof serializeTab>[] = [];
  const skippedDirty: ReturnType<typeof serializeTab>[] = [];
  const skippedPinned: ReturnType<typeof serializeTab>[] = [];
  for (const tab of tabs) {
    const serialized = serializeTab(tab, documentTabs.activeTabId);
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
  options: EditorTabsClientToolOptions,
  projectId: string,
  tabs: ReturnType<typeof serializeTab>[],
) {
  const latestProjectTabs = getProjectTabs(options, projectId);
  return tabs.filter((tab) => tab.path && findProjectTabByPath(latestProjectTabs, tab.path));
}

function findProjectTabByPath(tabs: DocumentTab[], path: string) {
  const normalizedPath = normalizeWorkspacePath(path);
  return tabs.find((tab) => tabPath(tab) === normalizedPath) ?? null;
}

function serializeTab(tab: DocumentTab, activeTabId: string | null) {
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

async function waitForUiUpdate() {
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

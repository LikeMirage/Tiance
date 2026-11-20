import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";
import type { WorkspaceTabEntry } from "../../../entities/editor/model/editorDocument";
import {
  applyProjectWorkspaceTabsAction,
  type ProjectWorkspaceTabsAction,
  type ProjectWorkspaceTabsActionResponse,
} from "../../../services/project/applyProjectWorkspaceTabsAction";
import { getProjectDocumentSourceKey } from "../../document-tabs/model/documentFileSources";
import { resolveDocumentPreview } from "../../document-tabs/model/documentPreviewResolver";
import { webTabTitle } from "../../document-tabs/model/workspaceTabEntries";
import {
  getPathName,
  makeTabId,
} from "../../document-tabs/model/documentTabUtils";
import type { ClientToolExecutionResult } from "./clientToolBridge";

type ExecuteBackgroundEditorTabsOptions = {
  action: string;
  path: string;
  paths: string[];
  projectId: string;
  url: string;
  tabId: string;
};

export async function executeBackgroundEditorTabsClientTool({
  action,
  path,
  paths,
  projectId,
  url,
  tabId,
}: ExecuteBackgroundEditorTabsOptions): Promise<ClientToolExecutionResult> {
  if (!isProjectWorkspaceTabsAction(action)) {
    return fail(`不支持的标签页操作：${action}`);
  }
  if ((action === "open_file" || action === "focus_file") && !path) {
    return fail(`${action} 需要 path 参数。`, { action });
  }

  try {
    const response = await applyProjectWorkspaceTabsAction(projectId, {
      action,
      ...(path ? { path } : {}),
      ...(paths.length > 0 ? { paths } : {}),
      ...(url ? { url } : {}),
      ...(tabId ? { tab_id: tabId } : {}),
    });
    return buildToolResult(projectId, response);
  } catch (error) {
    return fail(
      error instanceof Error ? error.message : "后台项目标签操作失败。",
      { action, path: path || null, project_id: projectId },
    );
  }
}

function buildToolResult(
  projectId: string,
  response: ProjectWorkspaceTabsActionResponse,
): ClientToolExecutionResult {
  const entries: WorkspaceTabEntry[] = response.open_tabs ?? response.open_file_paths.map(path => ({ kind: "file", path }));
  const tabs = entries.map(entry => entry.kind === "web" ? serializeWebTab(entry)
    : serializeBackgroundTab(projectId, entry.path, response.active_file_path, response.missing_file_paths));
  const active = tabs.find(tab => tab.is_active) ?? null;
  const common = {
    action: response.action,
    execution_scope: "background_workspace",
    project_id: projectId,
  };

  if (response.action === "list_tabs") {
    return ok({ ...common, tabs, active_tab_id: active?.id ?? null });
  }
  if (response.action === "open_url") return ok({ ...common, opened_tab: active });
  if (response.action === "focus_web") return ok({ ...common, focused_tab: active });
  if (response.action === "open_file") {
    const openedTab = tabs.find((tab) => tab.path === response.active_file_path) ?? null;
    return ok({
      ...common,
      opened_path: response.active_file_path,
      opened_tab: openedTab,
    });
  }
  if (response.action === "focus_file") {
    const focusedTab = tabs.find((tab) => tab.path === response.active_file_path) ?? null;
    return ok({ ...common, focused_tab: focusedTab });
  }

  const closed = response.closed_file_paths.map((path) => serializeBackgroundTab(
    projectId,
    path,
    null,
    response.missing_file_paths,
  ));
  const closeResult = {
    closed,
    closed_count: closed.length,
    skipped_dirty: [],
    skipped_dirty_count: 0,
    skipped_pinned: [],
    skipped_pinned_count: 0,
  };
  if (response.action === "close_others_clean") {
    const keptTab = tabs.find((tab) => tab.is_active) ?? null;
    return ok({ ...common, kept_tab: keptTab, ...closeResult });
  }
  return ok({ ...common, ...closeResult });
}

export function serializeWebTab(tab: Extract<WorkspaceTabEntry, { kind: "web" }>) {
  return {
    id: tab.id, kind: tab.kind, url: tab.url, title: webTabTitle(tab.url, tab.title),
    path: null, is_active: tab.active, is_dirty: false, is_missing: false, save_state: "idle",
  };
}

function serializeBackgroundTab(
  projectId: string,
  path: string,
  activeFilePath: string | null,
  missingFilePaths: string[],
) {
  const name = getPathName(path);
  const preview = resolveDocumentPreview({
    id: path,
    kind: "file",
    name,
    path,
  } as ExplorerNode);
  const isMissing = missingFilePaths.includes(path);
  return {
    id: makeTabId(getProjectDocumentSourceKey(projectId), path),
    title: name,
    path,
    kind: preview.kind,
    is_active: path === activeFilePath,
    is_dirty: false,
    is_missing: isMissing,
    save_state: isMissing ? "error" : "idle",
  };
}

function isProjectWorkspaceTabsAction(value: string): value is ProjectWorkspaceTabsAction {
  return [
    "list_tabs",
    "open_file",
    "open_url",
    "focus_web",
    "focus_file",
    "close_clean_tabs",
    "close_others_clean",
  ].includes(value);
}

function ok(content: Record<string, unknown>): ClientToolExecutionResult {
  return { ok: true, content };
}

function fail(
  error: string,
  content: Record<string, unknown> = {},
): ClientToolExecutionResult {
  return { ok: false, content, error };
}

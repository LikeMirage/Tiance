import type { DocumentTab, EditorTabId } from "../../../entities/editor/model/editorDocument";

import { getProjectDocumentSourceKey } from "./documentFileSources";
import {
  PROJECT_CONVERSATION_OVERVIEW_TAB_PREFIX,
  PROJECT_ROLE_CONFIGURATION_TAB_PREFIX,
  PROJECT_THEME_CONFIGURATION_TAB_PREFIX,
} from "./documentVirtualTabs";

export function makeTabId(sourceKey: string, filePath: string): EditorTabId {
  return `${sourceKey}:${normalizeWorkspacePath(filePath)}`;
}

export function makeStandaloneTabId(filePath: string): EditorTabId {
  return normalizeWorkspacePath(filePath);
}

export function normalizeWorkspacePath(path: string): string {
  return path.trim().replace(/^\/+|\/+$/g, "");
}

export function isWorkspacePathAffected(filePath: string, changedPaths: string[]): boolean {
  if (changedPaths.length === 0) return true;
  const normalizedFilePath = normalizeWorkspacePath(filePath);
  return changedPaths.some((changedPath) =>
    normalizedFilePath === changedPath || normalizedFilePath.startsWith(`${changedPath}/`),
  );
}

export function getTabSourceKey(tab: DocumentTab | null | undefined): string | null {
  if (!tab) return null;
  return tab.fileSource?.key ?? (tab.projectId ? getProjectDocumentSourceKey(tab.projectId) : null);
}

export function getTabFilePath(tab: DocumentTab | null | undefined): string | null {
  if (!tab) return null;
  return tab.filePath ?? tab.projectFilePath;
}

export function isPinnedDocumentTab(tab: DocumentTab | null | undefined): boolean {
  return tab?.fileSource?.kind === "tool-dashboard"
    || isProjectConversationOverviewTab(tab)
    || isProjectRoleConfigurationTab(tab)
    || isProjectThemeConfigurationTab(tab);
}

export function isProjectConversationOverviewTab(
  tab: DocumentTab | null | undefined,
): boolean {
  return tab?.id.startsWith(PROJECT_CONVERSATION_OVERVIEW_TAB_PREFIX) ?? false;
}

export function isProjectRoleConfigurationTab(
  tab: DocumentTab | null | undefined,
): boolean {
  return tab?.id.startsWith(PROJECT_ROLE_CONFIGURATION_TAB_PREFIX) ?? false;
}

export function isProjectThemeConfigurationTab(
  tab: DocumentTab | null | undefined,
): boolean {
  return tab?.id.startsWith(PROJECT_THEME_CONFIGURATION_TAB_PREFIX) ?? false;
}

export function isToolDashboardTabForSource(tab: DocumentTab, sourceKey: string): boolean {
  return isPinnedDocumentTab(tab) && tab.fileSource?.key === sourceKey;
}

export function getPathName(path: string): string {
  return normalizeWorkspacePath(path).split("/").pop() || path;
}

export function resolveRenamedTabId(
  sourceKey: string,
  tabPath: string,
  previousPath: string,
  nextPath: string,
): EditorTabId | null {
  if (tabPath === previousPath) {
    return makeTabId(sourceKey, nextPath);
  }

  const previousPrefix = `${previousPath}/`;
  if (!tabPath.startsWith(previousPrefix)) {
    return null;
  }

  return makeTabId(sourceKey, `${nextPath}/${tabPath.slice(previousPrefix.length)}`);
}

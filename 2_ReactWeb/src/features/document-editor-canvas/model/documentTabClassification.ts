import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import {
  isPinnedDocumentTab,
  isProjectConversationOverviewTab as isProjectConversationOverviewDocumentTab,
  isProjectKnowledgeContentTab as isProjectKnowledgeContentDocumentTab,
  isProjectRoleConfigurationTab as isProjectRoleConfigurationDocumentTab,
  isProjectThemeConfigurationTab as isProjectThemeConfigurationDocumentTab,
} from "../../document-tabs/model/documentTabUtils";

export function isCompressionLogTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return getTabPath(tab).endsWith("compressions.jsonl");
}

export function isConversationInjectionPreviewTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return getTabPath(tab).endsWith("injection_preview.json");
}

export function isConversationMessagesTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return getTabPath(tab).endsWith("messages.jsonl");
}

export function isConversationSessionTab(tab: DocumentTab | null) {
  if (!tab) return false;
  const path = getNormalizedTabPath(tab);
  return path.includes(".tiance/conversations/sessions/") && path.endsWith("/session.json");
}

export function isConversationIndexTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return getNormalizedTabPath(tab).endsWith(".tiance/conversations/index.json");
}

export function isConversationBranchesTab(tab: DocumentTab | null) {
  return tab?.id.startsWith("conversation-branches:") ?? false;
}

export function isProjectMemoryTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return tab.id.startsWith("memory-dashboard:project:")
    || getNormalizedTabPath(tab).endsWith(".tiance/memory/project_memory.jsonl");
}

export function isGlobalMemoryTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return tab.id.startsWith("memory-dashboard:global:");
}

export function isReferenceViewerTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return tab.id.startsWith("reference-viewer:");
}

export function isFixedDocumentTab(tab: DocumentTab) {
  return isPinnedDocumentTab(tab);
}

export function isProjectConversationOverviewTab(tab: DocumentTab | null) {
  return isProjectConversationOverviewDocumentTab(tab);
}

export function isProjectKnowledgeContentTab(tab: DocumentTab | null) {
  return isProjectKnowledgeContentDocumentTab(tab);
}

export function isProjectRoleConfigurationTab(tab: DocumentTab | null) {
  return isProjectRoleConfigurationDocumentTab(tab);
}

export function isProjectThemeConfigurationTab(tab: DocumentTab | null) {
  return isProjectThemeConfigurationDocumentTab(tab);
}

export function isToolDashboardTab(tab: DocumentTab | null) {
  if (!tab) return false;
  return tab.fileSource?.kind === "tool-dashboard";
}

function getTabPath(tab: DocumentTab) {
  return (tab.filePath ?? tab.projectFilePath ?? tab.displayPath ?? tab.title).toLowerCase();
}

function getNormalizedTabPath(tab: DocumentTab) {
  return getTabPath(tab).replaceAll("\\", "/");
}

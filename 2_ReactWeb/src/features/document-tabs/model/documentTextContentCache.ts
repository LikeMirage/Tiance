import type { DocumentTab, EditorTabId } from "../../../entities/editor/model/editorDocument";

import {
  getTabFilePath,
  isPinnedDocumentTab,
} from "./documentTabUtils";

const maxRetainedCleanTextTabs = 8;
const maxRetainedCleanTextChars = 10_000_000;

export type DocumentTextContentCacheRules = {
  maxRetainedCleanTextChars: number;
  maxRetainedCleanTextTabs: number;
};

export const documentTextContentCacheRules: DocumentTextContentCacheRules = {
  maxRetainedCleanTextChars,
  maxRetainedCleanTextTabs,
};

export function markDocumentTextContentAccessed(tab: DocumentTab, accessedAt = Date.now()): DocumentTab {
  if (tab.kind !== "text") return tab;
  return {
    ...tab,
    textContentAccessedAt: accessedAt,
  };
}

export function pruneDocumentTextContentCache(
  tabs: DocumentTab[],
  activeTabId: EditorTabId | null,
): DocumentTab[] {
  const candidates = tabs
    .filter((tab) => canUnloadCleanTextContent(tab, activeTabId))
    .sort((left, right) => (right.textContentAccessedAt ?? 0) - (left.textContentAccessedAt ?? 0));

  let retainedTextTabs = 0;
  let retainedTextChars = 0;
  const unloadTabIds = new Set<EditorTabId>();

  for (const tab of candidates) {
    const charCount = textContentCharCount(tab);
    const shouldRetain =
      retainedTextTabs < maxRetainedCleanTextTabs &&
      retainedTextChars + charCount <= maxRetainedCleanTextChars;

    if (shouldRetain) {
      retainedTextTabs += 1;
      retainedTextChars += charCount;
      continue;
    }

    unloadTabIds.add(tab.id);
  }

  if (unloadTabIds.size === 0) return tabs;

  return tabs.map((tab) =>
    unloadTabIds.has(tab.id)
      ? unloadDocumentTextContent(tab)
      : tab,
  );
}

function canUnloadCleanTextContent(tab: DocumentTab, activeTabId: EditorTabId | null) {
  if (tab.id === activeTabId) return false;
  if (tab.kind !== "text") return false;
  if (!tab.textContentLoaded) return false;
  if (tab.isDirty) return false;
  if (tab.externalChange) return false;
  if (tab.saveState === "saving" || tab.saveState === "error") return false;
  if (isPinnedDocumentTab(tab)) return false;
  return Boolean(getTabFilePath(tab));
}

function unloadDocumentTextContent(tab: DocumentTab): DocumentTab {
  return {
    ...tab,
    content: "",
    savedContent: "",
    textContentLoaded: false,
  };
}

function textContentCharCount(tab: DocumentTab) {
  return tab.content.length + tab.savedContent.length;
}

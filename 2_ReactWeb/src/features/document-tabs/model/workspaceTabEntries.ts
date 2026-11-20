import type { DocumentTab, WorkspaceTabEntry } from "../../../entities/editor/model/editorDocument";

type WebEntry = Extract<WorkspaceTabEntry, { kind: "web" }>;

// A reserved UUID keeps the fixed tab compatible with saved workspace tab entries.
const homeKey = "00000000-0000-0000-0000-000000000000";

export function createHomeTab(projectId: string | null, group: string) {
  return createWebTab(projectId, group, { kind: "web", id: homeKey, url: "", title: "", active: false });
}

export function isWebHomeTab(tab: DocumentTab | null | undefined) {
  return tab?.kind === "web" && webKey(tab) === homeKey;
}

export function isOverviewEditorTab(tab: DocumentTab) {
  return tab.kind === "web" || (tab.projectId === null && tab.fileSource?.kind === "local");
}

export function webTabTitle(url: string, title: string) {
  return url ? title || new URL(url).hostname : "主页";
}

export function createWebTab(projectId: string | null, group: string, entry: WebEntry): DocumentTab {
  const address = entry.url ? new URL(entry.url) : null;
  if (address && (!["http:", "https:"].includes(address.protocol) || address.username || address.password)) {
    throw new Error("请输入有效的 HTTP 或 HTTPS 网址");
  }
  return {
    id: `web:${group}:${projectId ?? ""}:${entry.id}`, kind: "web",
    title: webTabTitle(entry.url, entry.title),
    favicon: address && entry.favicon && entry.favicon.length <= 8192 && /^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(entry.favicon)
      ? entry.favicon : undefined,
    displayPath: entry.url, projectId,
    languageId: "plaintext", content: "", savedContent: "", textContentAccessedAt: null,
    textContentLoaded: false, isDirty: false, isMissing: false, saveState: "idle", saveError: null,
    fileSource: null, filePath: null, projectFilePath: null, assetVersion: null, mtimeMs: null, externalChange: null,
  };
}

export function snapshotWorkspaceTabs(
  tabs: DocumentTab[], activeId: string | null, projectId: string | null,
  filePath: (tab: DocumentTab) => string | null = tab => tab.projectFilePath,
): WorkspaceTabEntry[] {
  const entries: WorkspaceTabEntry[] = [];
  for (const tab of tabs) {
    if (tab.projectId !== projectId) continue;
    if (isWebHomeTab(tab) && tab.id !== activeId) continue;
    if (tab.kind === "web") {
      entries.push({ kind: "web", id: webKey(tab), url: tab.displayPath, title: tab.title,
        ...(tab.favicon && { favicon: tab.favicon }), active: tab.id === activeId });
    } else {
      const path = filePath(tab);
      if (path) entries.push({ kind: "file", path });
    }
  }
  return entries;
}

export function webKey(tab: DocumentTab) {
  return tab.id.slice(tab.id.lastIndexOf(":") + 1);
}

export function restoreWorkspaceTabEntries(
  entries: WorkspaceTabEntry[], files: DocumentTab[], liveWebTabs: DocumentTab[],
  projectId: string | null, group: string, restoreMissingWeb: boolean,
) {
  const byPath = new Map(files.map(tab => [tab.filePath, tab]));
  const byId = new Map(liveWebTabs.map(tab => [webKey(tab), tab]));
  const home = createHomeTab(projectId, group);
  const tabs: DocumentTab[] = [home];
  const seen = new Set<string>([home.id]);
  let savedActiveId: string | null = null;
  for (const entry of entries) {
    let tab: DocumentTab | undefined;
    if (entry.kind === "web") {
      tab = entry.id === homeKey ? home : byId.get(entry.id);
      if (!tab && restoreMissingWeb) {
        try { tab = createWebTab(projectId, group, entry); } catch { continue; }
      }
      if (tab && entry.active) savedActiveId = tab.id;
    } else {
      tab = byPath.get(entry.path);
    }
    if (tab && !seen.has(tab.id)) { tabs.push(tab); seen.add(tab.id); }
  }
  for (const tab of [...files, ...liveWebTabs]) {
    if (!seen.has(tab.id)) tabs.push(tab);
  }
  return { tabs, savedActiveId };
}

export function readOverviewTabs(group: string): WebEntry[] {
  try {
    const entries = JSON.parse(window.localStorage.getItem(`tiance.overview-tabs.${group}`) || "[]");
    return Array.isArray(entries) ? entries.filter(e => e?.kind === "web" && typeof e.id === "string"
      && typeof e.url === "string" && typeof e.title === "string") : [];
  } catch { return []; }
}

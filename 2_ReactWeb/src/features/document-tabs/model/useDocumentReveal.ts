import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { createDocumentRevealRequest, DocumentRevealError, type DocumentRevealRequest, type DocumentRevealTarget } from "../../../entities/editor/model/documentReveal";
import { getProjectDocumentSourceKey } from "./documentFileSources";
import { makeTabId, normalizeWorkspacePath } from "./documentTabUtils";
import { resolveDocumentPreview } from "./documentPreviewResolver";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";

type Options = {
  getSnapshot: () => { tabs: DocumentTab[]; activeTabId: string | null };
  openNode: (node: ExplorerNode, options?: { projectId?: string | null; projectFilePath?: string | null }) => Promise<void>;
  selectTab: (tabId: string) => void;
  tabs: DocumentTab[];
  activeTabId: string | null;
  setTabs: Dispatch<SetStateAction<DocumentTab[]>>;
};

export function useDocumentReveal({ getSnapshot, openNode, selectTab, tabs, activeTabId, setTabs }: Options) {
  const pending = useRef<{ tabId: string; request: DocumentRevealRequest } | null>(null);
  useEffect(() => () => {
    pending.current?.request.fail(new DocumentRevealError("CANCELLED", "编辑器已关闭，定位取消。"));
  }, []);
  useEffect(() => {
    const command = pending.current;
    if (!command) return;
    const tab = tabs.find((item) => item.id === command.tabId);
    if (!tab || activeTabId !== command.tabId) {
      command.request.fail(new DocumentRevealError("NAVIGATION_INTERRUPTED", "目标标签已关闭或切换，定位中止。"));
    } else if (tab.isMissing && !tab.isDirty) {
      command.request.fail(new DocumentRevealError("FILE_NOT_FOUND", "目标文件不存在。"));
    } else if (tab.textContentUnavailable) {
      command.request.fail(new DocumentRevealError("CONTENT_UNAVAILABLE", "文件超过文本编辑器读取上限。"));
    } else if (tab.kind === "text" && !tab.textContentLoaded && tab.saveError) {
      command.request.fail(new DocumentRevealError("LOAD_FAILED", tab.saveError));
    }
  }, [activeTabId, tabs]);

  return useCallback((projectId: string, rawPath: string, target: DocumentRevealTarget, signal: AbortSignal) => {
    const path = normalizeWorkspacePath(rawPath);
    const node = { id: `project:${projectId}:${path}`, kind: "file" as const, name: path.split("/").at(-1) || path, path };
    const tabId = makeTabId(getProjectDocumentSourceKey(projectId), path);
    const existing = getSnapshot().tabs.find((tab) => tab.id === tabId);
    const kind = existing?.kind ?? resolveDocumentPreview(node).kind;
    if (kind !== (target.type === "pdf_page" ? "pdf" : "text")) {
      const supported = kind === "pdf" ? ["pdf_page"] : kind === "text" ? ["text", "line_range", "text_ranges"] : [];
      const message = supported.length
        ? `文件“${node.name}”不支持 ${target.type}，可用定位类型：${supported.join("、")}。`
        : `文件“${node.name}”使用${kind === "office" ? " Office/表格" : "非文本"}预览，不支持 reveal_file 的任何定位或选区方式。Word、Excel、PPT、CSV/TSV 等不能按原文或行号选中；请用 open_file 打开完整文件，且不要将打开预览称为已定位或已选中。`;
      return Promise.reject(new DocumentRevealError("UNSUPPORTED_TARGET", message, {
        file_kind: kind, requested_target: target.type, supported_target_types: supported,
        suggested_action: supported.length ? "reveal_file" : "open_file",
      }));
    }
    if (signal.aborted) return Promise.reject(new DocumentRevealError("CANCELLED", "文件定位已取消。"));
    pending.current?.request.fail(new DocumentRevealError("SUPERSEDED", "已被新的文件定位请求替代。"));
    const { request, result } = createDocumentRevealRequest(target, signal);
    pending.current = { tabId, request };
    try {
      // Existing tabs keep their live editor buffer, including uncommitted typing.
      if (existing) selectTab(tabId);
      else void openNode(node, { projectId, projectFilePath: path }).catch(request.fail);
      setTabs((current) => current.map((tab) => tab.id === tabId ? { ...tab, revealRequest: request } : tab));
    } catch (error) { request.fail(error); }
    return result.finally(() => {
      if (pending.current?.request === request) pending.current = null;
      setTabs((current) => current.some((tab) => tab.revealRequest === request)
        ? current.map((tab) => tab.revealRequest === request ? { ...tab, revealRequest: undefined } : tab)
        : current);
    });
  }, [getSnapshot, openNode, selectTab, setTabs]);
}

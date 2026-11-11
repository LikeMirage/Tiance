import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import { publishProjectFileMutation } from "../../../entities/project/model/projectFileMutation";
import type { WorkspaceLayoutPreferenceUpdate } from "../../../entities/workspace/model/workspaceLayoutPreferences";
import type { ConversationDataFileName } from "../../../features/ai-panel/ui/ChatDataDashboardPanel";
import {
  createEditorTabsClientToolRegistration,
  type EditorTabsCapability,
} from "../../../features/client-tools/model/editorTabsClientTool";
import { saveProjectCodeBlock } from "../../../features/document-editor-canvas/model/saveProjectCodeBlock";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import type { CodeBlockSavePayload } from "../../../features/markdown-preview/model/codeBlockFile";
import { generateProjectMarkdownDocx } from "../../../services/project/generateProjectMarkdownDocx";
import { getConversationDataView } from "../../../services/project/getConversationDataView";
import { resolveFileReference } from "../../../services/editor/localEditorFiles";
import { createLocalDocumentSource } from "../../../features/document-tabs/model/localDocumentFileSource";
import type { DocumentFileSourceRuntime } from "../../../features/document-tabs/model/documentFileSources";
import { getProjectDocumentSourceKey } from "../../../features/document-tabs/model/documentFileSources";
import { makeTabId } from "../../../features/document-tabs/model/documentTabUtils";
import { referenceOriginalFile, referenceRevealTarget } from "../../../entities/editor/model/referenceNavigation";
import { DocumentRevealError } from "../../../entities/editor/model/documentReveal";

type UseWorkspaceDocumentActionsOptions = {
  documentTabs: ReturnType<typeof useDocumentTabs>;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  projectId: string | null;
  sessionId: string | null;
  projectFileSource?: DocumentFileSourceRuntime | null;
  onPrepareFileOpen?: (signal: AbortSignal) => boolean | void | Promise<boolean | void>;
};

export function useWorkspaceDocumentActions({
  documentTabs,
  onLayoutPreferenceChange,
  projectId,
  sessionId,
  projectFileSource,
  onPrepareFileOpen,
}: UseWorkspaceDocumentActionsOptions) {
  const documentTabsRef = useRef(documentTabs);
  const projectIdRef = useRef(projectId);
  const dataViewRequestsRef = useRef(new Map<string, AbortController>());
  documentTabsRef.current = documentTabs;
  projectIdRef.current = projectId;
  const [referenceOpenError, setReferenceOpenError] = useState<string | null>(null);
  const referenceRequestRef = useRef<AbortController | null>(null);
  useEffect(() => {
    setReferenceOpenError(null);
    return () => referenceRequestRef.current?.abort();
  }, [projectId, sessionId]);
  useEffect(() => setReferenceOpenError(null), [documentTabs.activeTabId]);

  useEffect(() => () => {
    for (const controller of dataViewRequestsRef.current.values()) controller.abort();
    dataViewRequestsRef.current.clear();
  }, []);

  const handleSaveProjectCodeBlock = useCallback(async ({ code, language }: CodeBlockSavePayload) => {
    if (!projectId) {
      throw new Error("未选择项目，无法保存代码块。");
    }
    return saveProjectCodeBlock(projectId, code, language);
  }, [projectId]);

  const handleGenerateMarkdownDocx = useCallback(async (tab: DocumentTab) => {
    const startedProjectId = projectId;
    const sourcePath = tab.projectFilePath;
    if (!startedProjectId || tab.projectId !== startedProjectId || !sourcePath) {
      throw new Error("只能将当前项目中的 Markdown 文件生成 Word。");
    }
    const result = await generateProjectMarkdownDocx(startedProjectId, {
      path: sourcePath,
      content: tab.content,
    });
    if (projectIdRef.current === startedProjectId) {
      publishProjectFileMutation({
        projectId: startedProjectId,
        node: result.node,
        sourceId: "markdown-to-docx",
      });
      await documentTabsRef.current.openNode(result.node, {
        projectId: startedProjectId,
        projectFilePath: result.output_path,
      });
    }
    return {
      outputPath: result.output_path,
      warnings: result.warnings,
    };
  }, [projectId]);

  const handlePreviewHtmlCode = useCallback((html: string) => {
    if (!projectId) return;
    documentTabs.openVirtualHtmlPreview(html, { projectId });
  }, [documentTabs.openVirtualHtmlPreview, projectId]);

  const handleOpenReference = useCallback((payload: EditorReferenceViewerPayload) => {
    referenceRequestRef.current?.abort();
    setReferenceOpenError(null);
    if (!projectId) return;
    const controller = new AbortController();
    referenceRequestRef.current = controller;
    void (async () => {
      try {
        const file = await resolveFileReference(referenceOriginalFile(payload), projectId, sessionId, controller.signal);
        if (controller.signal.aborted || projectIdRef.current !== projectId) return;
        if (await onPrepareFileOpen?.(controller.signal) === false) return;
        if (controller.signal.aborted || projectIdRef.current !== projectId) return;
        if (file.kind === "folder") {
          documentTabsRef.current.openVirtualReferenceViewer(payload, { projectId, resolution: file });
          return;
        }
        const runtime = file.kind === "local" ? createLocalDocumentSource(file.root, projectId) : projectFileSource;
        const tabId = makeTabId(runtime?.source.key ?? getProjectDocumentSourceKey(projectId), file.path);
        await documentTabsRef.current.openNode({
          id: file.path, kind: "file", name: file.name, path: file.path, mtimeMs: file.mtime_ms,
        }, file.kind === "project"
          ? { projectId, projectFilePath: file.path, fileSource: projectFileSource }
          : { fileSource: runtime, filePath: file.path });
        if (controller.signal.aborted || projectIdRef.current !== projectId) return;
        try {
          await documentTabsRef.current.revealReference(tabId, payload, referenceRevealTarget(payload), controller.signal);
        } catch (error) {
          // A changed excerpt/page leaves the original file open. Loading, access and network
          // failures must retain their real error, not masquerade as a deleted source.
          if (!(error instanceof DocumentRevealError) || ![
            "TEXT_NOT_FOUND", "AMBIGUOUS_TEXT", "PAGE_OUT_OF_RANGE", "UNSUPPORTED_TARGET",
            "NAVIGATION_INTERRUPTED", "SUPERSEDED", "CANCELLED", "FILE_NOT_FOUND",
          ].includes(error.code)) throw error;
        }
      } catch (error) {
        if (!controller.signal.aborted && projectIdRef.current === projectId) {
          if (error && typeof error === "object" && "status" in error && error.status === 404) {
            if (await onPrepareFileOpen?.(controller.signal) === false || controller.signal.aborted) return;
            documentTabsRef.current.openVirtualReferenceViewer(payload, { projectId, resolution: { kind: "missing" } });
          } else setReferenceOpenError(error instanceof Error ? error.message : "打开引用文件失败。");
        }
      }
    })();
  }, [documentTabs.openVirtualReferenceViewer, projectId, sessionId, projectFileSource, onPrepareFileOpen]);

  const handleOpenProjectFile = useCallback(async (path: string) => {
    if (!projectId || !path.trim()) {
      throw new Error("文件路径为空，无法在工作区中查看。");
    }
    await documentTabs.openNode({
      id: `project:${projectId}:${path}`,
      kind: "file",
      name: path.split(/[\\/]/).at(-1) || path,
      path,
    }, {
      projectFilePath: path,
      projectId,
    });
  }, [documentTabs.openNode, projectId]);

  const handleOpenConversationBranches = useCallback((targetProjectId?: string | null) => {
    const resolvedProjectId = targetProjectId ?? projectId;
    if (!resolvedProjectId) return;
    documentTabs.openVirtualConversationBranches(resolvedProjectId);
  }, [documentTabs.openVirtualConversationBranches, projectId]);

  const loadConversationDataView = useCallback(async ({
    fileName,
    page,
    targetProjectId,
    viewSessionId,
  }: {
    fileName: ConversationDataFileName;
    page?: number;
    targetProjectId: string;
    viewSessionId: string | null;
  }) => {
    const requestKey = `${targetProjectId}:${viewSessionId ?? "project"}:${fileName}`;
    dataViewRequestsRef.current.get(requestKey)?.abort();
    const controller = new AbortController();
    dataViewRequestsRef.current.set(requestKey, controller);
    try {
      const result = await getConversationDataView(
        targetProjectId,
        fileName,
        viewSessionId,
        { page, signal: controller.signal },
      );
      if (
        controller.signal.aborted
        || dataViewRequestsRef.current.get(requestKey) !== controller
        || projectIdRef.current !== targetProjectId
      ) return;
      documentTabsRef.current.openVirtualConversationData({
        content: result.content,
        fileName,
        projectId: targetProjectId,
        revisionMs: result.revision_ms,
        sessionId: viewSessionId,
        totalCount: result.total_count,
        page: result.page,
        pageSize: result.page_size,
        totalPages: result.total_pages,
        hasPrevious: result.has_previous,
        hasNext: result.has_next,
      });
    } finally {
      if (dataViewRequestsRef.current.get(requestKey) === controller) {
        dataViewRequestsRef.current.delete(requestKey);
      }
    }
  }, []);

  const handleOpenConversationDataFile = useCallback((
    sessionId: string,
    fileName: ConversationDataFileName,
  ) => {
    if (!projectId) return;
    if (fileName === "global_memory.jsonl") {
      documentTabs.openVirtualMemoryDashboard("global", { projectId });
      return;
    }
    const viewSessionId = fileName === "index.json" || fileName === "project_memory.jsonl"
      ? null
      : sessionId;
    void loadConversationDataView({
      fileName,
      targetProjectId: projectId,
      viewSessionId,
    });
  }, [documentTabs.openVirtualMemoryDashboard, loadConversationDataView, projectId]);

  const handleConversationDataPageChange = useCallback(async (
    tab: DocumentTab,
    page: number,
  ) => {
    const view = tab.conversationDataView;
    if (!tab.projectId || !view || page === view.page || page < 1 || page > view.totalPages) return;
    await loadConversationDataView({
      fileName: view.fileName as ConversationDataFileName,
      page,
      targetProjectId: tab.projectId,
      viewSessionId: view.sessionId,
    });
  }, [loadConversationDataView]);

  const handleAiPanelWidthCommit = useCallback((aiPanelWidth: number) => {
    onLayoutPreferenceChange({ aiPanelWidth });
  }, [onLayoutPreferenceChange]);

  const handleComposerHeightCommit = useCallback((composerHeight: number) => {
    onLayoutPreferenceChange({ composerHeight });
  }, [onLayoutPreferenceChange]);

  const visibleProjectTabs = useMemo(() => (
    projectId
      ? documentTabs.tabs.filter((tab) => tab.projectId === projectId)
      : []
  ), [documentTabs.tabs, projectId]);
  const visibleActiveTab = projectId && documentTabs.activeTab?.projectId === projectId
    ? documentTabs.activeTab
    : null;
  const visibleActiveTabId = visibleActiveTab ? documentTabs.activeTabId : null;
  const clientToolRegistrations = useMemo(() => [
    createEditorTabsClientToolRegistration({
      getEditorTabs: () => createEditorTabsCapability(documentTabsRef.current),
      getProjectId: () => projectIdRef.current,
    }),
  ], []);
  const activeConversationDataFile = useMemo(
    () => getActiveConversationDataFile(visibleActiveTab),
    [
      visibleActiveTab?.displayPath,
      visibleActiveTab?.filePath,
      visibleActiveTab?.projectFilePath,
      visibleActiveTab?.title,
    ],
  );

  return {
    referenceOpenError,
    activeConversationDataFile,
    clientToolRegistrations,
    handleAiPanelWidthCommit,
    handleComposerHeightCommit,
    handleConversationDataPageChange,
    handleGenerateMarkdownDocx,
    handleOpenConversationBranches,
    handleOpenConversationDataFile,
    handleOpenProjectFile,
    handleOpenReference,
    handlePreviewHtmlCode,
    handleSaveProjectCodeBlock,
    visibleActiveTab,
    visibleActiveTabId,
    visibleProjectTabs,
  };
}

function createEditorTabsCapability(
  documentTabs: ReturnType<typeof useDocumentTabs>,
): EditorTabsCapability {
  return {
    closeTab: documentTabs.closeTab,
    getSnapshot: documentTabs.getSnapshot,
    revealProjectFile: documentTabs.revealProjectFile,
    openProjectFile: async (projectId, path) => {
      await documentTabs.openNode({
        id: `project:${projectId}:${path}`,
        kind: "file",
        name: path.split("/").at(-1) || path,
        path,
      }, {
        projectFilePath: path,
        projectId,
      });
    },
    selectTab: documentTabs.selectTab,
  };
}

function getActiveConversationDataFile(tab: {
  id: string;
  displayPath?: string | null;
  filePath?: string | null;
  projectFilePath?: string | null;
  title: string;
} | null): ConversationDataFileName | null {
  if (!tab) return null;
  if (tab.id.startsWith("memory-dashboard:project:")) return "project_memory.jsonl";
  if (tab.id.startsWith("memory-dashboard:global:")) return "global_memory.jsonl";
  const path = (tab.projectFilePath ?? tab.filePath ?? tab.displayPath ?? tab.title)
    .toLowerCase()
    .replaceAll("\\", "/");
  if (path.endsWith(".tiance/memory/project_memory.jsonl")) return "project_memory.jsonl";
  if (path.endsWith(".tiance/conversations/index.json")) return "index.json";
  if (!path.includes(".tiance/conversations/sessions/")) return null;
  if (path.endsWith("/compressions.jsonl")) return "compressions.jsonl";
  if (path.endsWith("/injection_preview.json")) return "injection_preview.json";
  if (path.endsWith("/messages.jsonl")) return "messages.jsonl";
  if (path.endsWith("/conversation_journal.jsonl")) return "conversation_journal.jsonl";
  if (path.endsWith("/model_exchanges.jsonl")) return "model_exchanges.jsonl";
  if (path.endsWith("/request_submissions.jsonl")) return "request_submissions.jsonl";
  if (path.endsWith("/model_http_exchanges.jsonl")) return "model_http_exchanges.jsonl";
  if (path.endsWith("/session.json")) return "session.json";
  return null;
}

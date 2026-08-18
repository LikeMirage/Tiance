import { useCallback, useEffect, useMemo, useRef } from "react";

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

type UseWorkspaceDocumentActionsOptions = {
  documentTabs: ReturnType<typeof useDocumentTabs>;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  projectId: string | null;
};

export function useWorkspaceDocumentActions({
  documentTabs,
  onLayoutPreferenceChange,
  projectId,
}: UseWorkspaceDocumentActionsOptions) {
  const documentTabsRef = useRef(documentTabs);
  const projectIdRef = useRef(projectId);
  const dataViewRequestsRef = useRef(new Map<string, AbortController>());
  documentTabsRef.current = documentTabs;
  projectIdRef.current = projectId;

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
    const sourcePath = tab.projectFilePath ?? tab.filePath;
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
    documentTabs.openVirtualReferenceViewer(payload, {
      projectId: payload.reference.projectId ?? projectId,
    });
  }, [documentTabs.openVirtualReferenceViewer, projectId]);

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
    activeConversationDataFile,
    clientToolRegistrations,
    handleAiPanelWidthCommit,
    handleComposerHeightCommit,
    handleConversationDataPageChange,
    handleGenerateMarkdownDocx,
    handleOpenConversationBranches,
    handleOpenConversationDataFile,
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
  if (path.endsWith("/model_http_exchanges.jsonl")) return "model_http_exchanges.jsonl";
  if (path.endsWith("/session.json")) return "session.json";
  return null;
}

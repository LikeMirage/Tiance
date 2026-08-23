import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { useAiPanelLayout } from "../../ai-panel/model/useAiPanelLayout";
import { useHorizontalScrollAnimation } from "../../../shared/model/horizontal-scroll-animation/useHorizontalScrollAnimation";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { ContextMenu, ContextMenuItem, ContextMenuSeparator } from "../../../shared/ui/context-menu";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { EditorWorkspaceFileReference } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorPdfPageImageReferenceRequest,
  EditorPresentationSlideImageReferenceRequest,
  EditorSpreadsheetRangeImageReferenceRequest,
  EditorTextReferenceDraft,
} from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import {
  isCompressionLogTab,
  isConversationBranchesTab,
  isConversationIndexTab,
  isConversationInjectionPreviewTab,
  isConversationMessagesTab,
  isConversationSessionTab,
  isGlobalMemoryTab,
  isProjectConversationOverviewTab,
  isProjectKnowledgeContentTab,
  isProjectRoleConfigurationTab,
  isProjectThemeConfigurationTab,
  isProjectMemoryTab,
  isReferenceViewerTab,
  isToolDashboardTab,
} from "../model/documentTabClassification";
import { createMarkdownAssetUrlResolver } from "../model/markdownPreviewAssets";
import { DocumentEditorActiveContent } from "./DocumentEditorActiveContent";
import { DocumentEditorTabBar } from "./DocumentEditorTabBar";
import "./document-editor-canvas.css";

type Props = {
  activeConversationMessageId?: string | null;
  activeConversationSessionId?: string | null;
  activeTab: DocumentTab | null;
  activeTabId: string | null;
  aiPanelInitialWidth?: number;
  assistantPanel?: ReactNode;
  emptyContent?: ReactNode;
  emptyMessage?: string | null;
  persistentEmptyContent?: ReactNode;
  persistentEmptyContentVisible?: boolean;
  projectConversationOverviewContent?: ReactNode;
  projectKnowledgeContent?: ReactNode;
  roleConfigurationContent?: ReactNode;
  themeConfigurationContent?: ReactNode;
  projectRootPath?: string;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  statusMessage?: string | null;
  tabs: DocumentTab[];
  toolEntryCandidates?: string[];
  onCloseTab: (id: string) => void;
  onCloseOtherTabs: (id: string) => void;
  onCloseAllTabs: () => void;
  onAiPanelWidthCommit?: (width: number) => void;
  onOverwriteExternalChange?: (id: string) => Promise<boolean>;
  onSaveTabAs?: (id: string, targetPath: string) => Promise<boolean>;
  onCreatePdfPageImageReference?: (request: EditorPdfPageImageReferenceRequest) => Promise<void>;
  onCreatePresentationSlideImageReference?: (request: EditorPresentationSlideImageReferenceRequest) => Promise<void>;
  onCreateSpreadsheetRangeImageReference?: (request: EditorSpreadsheetRangeImageReferenceRequest) => Promise<void>;
  onCreateTextReference?: (reference: EditorTextReferenceDraft) => void;
  onGenerateMarkdownDocx?: (tab: DocumentTab) => Promise<MarkdownDocxGenerationResult>;
  onReferenceWorkspaceFile?: (file: EditorWorkspaceFileReference) => void;
  onSelectConversationMessage?: (sessionId: string, messageId: string) => void;
  onSelectExportDirectory?: () => Promise<string | null>;
  onConversationDataPageChange?: (tab: DocumentTab, page: number) => Promise<void>;
  onMarkDirty: (id: string) => void;
  onMarkMissing: (id: string) => void;
  onSaveTab: (id: string, contentSnapshot?: string) => Promise<boolean>;
  onSelectTab: (id: string) => void;
  onUpdateContent: (id: string, content: string) => void;
};

type PendingCloseAction =
  | { mode: "single"; tabId: string }
  | { mode: "others"; tabId: string }
  | { mode: "all" };

type ToolDashboardView = "basics" | "permissions" | "examples" | "dependencies" | "callRecords";
type MarkdownEditorMode = "source" | "preview" | "visual";
type MarkdownDocxGenerationResult = {
  outputPath: string;
  warnings: string[];
};

export const DocumentEditorCanvas = memo(function DocumentEditorCanvas({
  activeConversationMessageId = null, activeConversationSessionId = null, activeTab, activeTabId, aiPanelInitialWidth, assistantPanel = null, emptyContent = null, emptyMessage = "点击左侧文件树中的文件以打开", persistentEmptyContent = null, persistentEmptyContentVisible = false, projectConversationOverviewContent = null, projectKnowledgeContent = null, roleConfigurationContent = null, themeConfigurationContent = null, projectRootPath = "", onSaveCodeBlock, statusMessage = null, tabs, toolEntryCandidates = [],
  onCloseTab, onCloseOtherTabs, onCloseAllTabs,
  onAiPanelWidthCommit,
  onOverwriteExternalChange,
  onSaveTabAs,
  onCreatePdfPageImageReference,
  onCreatePresentationSlideImageReference,
  onCreateSpreadsheetRangeImageReference,
  onCreateTextReference,
  onGenerateMarkdownDocx,
  onReferenceWorkspaceFile,
  onSelectConversationMessage,
  onSelectExportDirectory,
  onConversationDataPageChange,
  onMarkDirty, onMarkMissing, onSaveTab, onSelectTab, onUpdateContent,
}: Props) {
  const aiPanel = useAiPanelLayout({
    initialWidth: aiPanelInitialWidth,
    onWidthCommit: onAiPanelWidthCommit,
  });
  const hasAssistantPanel = Boolean(assistantPanel);
  const hasPersistentEmptyContent = Boolean(persistentEmptyContent);
  const [pendingCloseAction, setPendingCloseAction] = useState<PendingCloseAction | null>(null);
  const [isCloseSaving, setIsCloseSaving] = useState(false);
  const [closeSaveError, setCloseSaveError] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{ tabId: string; x: number; y: number } | null>(null);
  const [markdownMode, setMarkdownMode] = useState<MarkdownEditorMode>("preview");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [conflictSaveAsPath, setConflictSaveAsPath] = useState("");
  const [isResolvingExternalConflict, setIsResolvingExternalConflict] = useState(false);
  const [tabIndicator, setTabIndicator] = useState<{ left: number; width: number } | null>(null);
  const tabBarRef = useRef<HTMLDivElement>(null);
  const editorScrollerRef = useRef<HTMLElement | null>(null);
  const closeSaveRunIdRef = useRef(0);
  const {
    cancelHorizontalScroll: cancelDocumentTabScroll,
    scrollHorizontallyTo: scrollDocumentTabsTo,
  } = useHorizontalScrollAnimation();

  const activeIdx = activeTabId ? tabs.findIndex((t) => t.id === activeTabId) : -1;
  const tabLayoutKey = useMemo(
    () => tabs.map((tab) => [
      tab.id,
      tab.title,
      tab.isDirty ? "dirty" : "clean",
      tab.saveState,
    ].join(":")).join("|"),
    [tabs],
  );
  const isMarkdown = activeTab?.languageId === "markdown";
  const isHtml = activeTab?.languageId === "html";
  const isCompressionLog = isCompressionLogTab(activeTab);
  const isConversationIndex = isConversationIndexTab(activeTab);
  const isConversationBranches = isConversationBranchesTab(activeTab);
  const isConversationInjectionPreview = isConversationInjectionPreviewTab(activeTab);
  const isConversationMessages = isConversationMessagesTab(activeTab);
  const isConversationSession = isConversationSessionTab(activeTab);
  const isProjectMemory = isProjectMemoryTab(activeTab);
  const isProjectConversationOverview = isProjectConversationOverviewTab(activeTab);
  const isProjectKnowledgeContent = isProjectKnowledgeContentTab(activeTab);
  const isProjectRoleConfiguration = isProjectRoleConfigurationTab(activeTab);
  const isProjectThemeConfiguration = isProjectThemeConfigurationTab(activeTab);
  const isGlobalMemory = isGlobalMemoryTab(activeTab);
  const isReferenceViewer = isReferenceViewerTab(activeTab);
  const isToolDashboard = isToolDashboardTab(activeTab);
  const externalConflictTab = activeTab?.externalChange?.kind === "conflict" ? activeTab : null;
  const toolDashboardView = getToolDashboardView(activeTab);
  const toolDependencyTarget = toolDashboardView === "dependencies"
    ? getToolDependencyTarget(activeTab)
    : null;
  const toolCallRecordTarget = toolDashboardView === "callRecords"
    ? getToolFolderTarget(activeTab)
    : null;
  const isPreviewable = isMarkdown
    || isHtml
    || isCompressionLog
    || isConversationInjectionPreview
    || isConversationMessages
    || isConversationSession
    || isConversationIndex
    || isProjectMemory
    || isGlobalMemory;
  const isVirtualHtmlPreview = activeTab?.id.startsWith("preview:html:") ?? false;
  const markdownAssetUrlResolver = useMemo(
    () => createMarkdownAssetUrlResolver(activeTab),
    [
      activeTab?.filePath,
      activeTab?.fileSource?.id,
      activeTab?.fileSource?.key,
      activeTab?.fileSource?.kind,
    ],
  );

  useEffect(() => {
    if (!externalConflictTab) {
      setConflictSaveAsPath("");
      setIsResolvingExternalConflict(false);
      return;
    }
    setConflictSaveAsPath(makeExternalConflictSaveAsPath(
      externalConflictTab.filePath ?? externalConflictTab.displayPath,
    ));
    setIsResolvingExternalConflict(false);
  }, [externalConflictTab?.externalChange?.detectedAt, externalConflictTab?.id]);

  const handleEditorScroll = (scroller: HTMLElement) => {
    editorScrollerRef.current = scroller;
  };

  useEffect(() => {
    setContextMenu(null);
    if (isMarkdown) {
      setPreviewOpen(false);
      setMarkdownMode("preview");
      return;
    }
    if (isVirtualHtmlPreview) {
      setPreviewOpen(true);
      return;
    }
    if (isCompressionLog) {
      setPreviewOpen(true);
      return;
    }
    if (isConversationInjectionPreview) {
      setPreviewOpen(true);
      return;
    }
    if (isConversationMessages) {
      setPreviewOpen(true);
      return;
    }
    if (isConversationSession || isConversationIndex) {
      setPreviewOpen(true);
      return;
    }
    if (isProjectMemory || isGlobalMemory) {
      setPreviewOpen(true);
      return;
    }
    if (isReferenceViewer) {
      setPreviewOpen(true);
      return;
    }
    if (!activeTab || !isPreviewable || activeTab.languageId === "html") {
      setPreviewOpen(false);
    }
  }, [
    activeTab?.id,
    activeTab?.languageId,
    isCompressionLog,
    isConversationIndex,
    isConversationInjectionPreview,
    isConversationMessages,
    isConversationSession,
    isGlobalMemory,
    isPreviewable,
    isProjectMemory,
    isReferenceViewer,
    isVirtualHtmlPreview,
  ]);

  useLayoutEffect(() => {
    const tabBar = tabBarRef.current;
    if (!tabBar || activeIdx < 0) {
      setTabIndicator(null);
      return;
    }

    const activeTabElement = tabBar.querySelector<HTMLElement>(".doc-editor__tab--active");
    if (!activeTabElement) {
      setTabIndicator(null);
      return;
    }

    setTabIndicator({
      left: activeTabElement.offsetLeft,
      width: activeTabElement.offsetWidth,
    });
  }, [activeIdx, activeTabId, tabLayoutKey]);

  useLayoutEffect(() => {
    const tabBar = tabBarRef.current;
    if (!tabBar || activeIdx < 0) return;

    const activeTabElement = tabBar.querySelector<HTMLElement>(".doc-editor__tab--active");
    if (!activeTabElement) return;
    const targetLeft = resolveDocumentTabScrollLeft(tabBar, activeTabElement);
    if (targetLeft !== null) {
      scrollDocumentTabsTo(tabBar, targetLeft);
    }
  }, [activeIdx, activeTabId, scrollDocumentTabsTo]);

  useLayoutEffect(() => {
    const tabBar = tabBarRef.current;
    if (!tabBar || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(() => {
      const activeTabElement = tabBar.querySelector<HTMLElement>(".doc-editor__tab--active");
      if (!activeTabElement) return;

      setTabIndicator({
        left: activeTabElement.offsetLeft,
        width: activeTabElement.offsetWidth,
      });
      const targetLeft = resolveDocumentTabScrollLeft(tabBar, activeTabElement);
      if (targetLeft !== null) {
        scrollDocumentTabsTo(tabBar, targetLeft, { animate: false });
      }
    });
    observer.observe(tabBar);
    return () => observer.disconnect();
  }, [scrollDocumentTabsTo]);

  const resolveCloseTabs = (action: PendingCloseAction) => {
    if (action.mode === "single") {
      return tabs.filter((tab) => tab.id === action.tabId);
    }
    if (action.mode === "others") {
      return tabs.filter((tab) => tab.id !== action.tabId);
    }
    return tabs;
  };

  const closeByAction = (action: PendingCloseAction) => {
    if (action.mode === "single") {
      onCloseTab(action.tabId);
      return;
    }
    if (action.mode === "others") {
      onCloseOtherTabs(action.tabId);
      return;
    }
    onCloseAllTabs();
  };

  const requestClose = (action: PendingCloseAction) => {
    if (resolveCloseTabs(action).some((tab) => tab.isDirty)) {
      setCloseSaveError(null);
      setPendingCloseAction(action);
      return;
    }
    closeByAction(action);
  };

  const saveAndClosePendingTabs = async () => {
    const action = pendingCloseAction;
    if (!action || isCloseSaving) return;

    setIsCloseSaving(true);
    setCloseSaveError(null);
    const runId = closeSaveRunIdRef.current + 1;
    closeSaveRunIdRef.current = runId;
    for (const tab of resolveCloseTabs(action)) {
      if (!tab.isDirty) continue;
      const didSave = await onSaveTab(tab.id);
      if (closeSaveRunIdRef.current !== runId) {
        return;
      }
      if (!didSave) {
        onSelectTab(tab.id);
        setCloseSaveError(`保存 ${tab.title} 失败。请重试，或选择“不保存”直接关闭。`);
        setIsCloseSaving(false);
        return;
      }
    }
    setIsCloseSaving(false);
    setCloseSaveError(null);
    setPendingCloseAction(null);
    closeByAction(action);
  };

  const discardAndClosePendingTabs = () => {
    const action = pendingCloseAction;
    if (!action) return;

    closeSaveRunIdRef.current += 1;
    setIsCloseSaving(false);
    setCloseSaveError(null);
    setPendingCloseAction(null);
    closeByAction(action);
  };

  const overwriteExternalConflict = async () => {
    if (!externalConflictTab || !onOverwriteExternalChange || isResolvingExternalConflict) return;
    setIsResolvingExternalConflict(true);
    const didResolve = await onOverwriteExternalChange(externalConflictTab.id);
    if (!didResolve) {
      setIsResolvingExternalConflict(false);
    }
  };

  const saveExternalConflictAs = async () => {
    if (!externalConflictTab || !onSaveTabAs || isResolvingExternalConflict) return;
    const targetPath = conflictSaveAsPath.trim();
    if (!targetPath) return;
    setIsResolvingExternalConflict(true);
    const didResolve = await onSaveTabAs(externalConflictTab.id, targetPath);
    if (!didResolve) {
      setIsResolvingExternalConflict(false);
    }
  };

  const pendingDirtyCount = pendingCloseAction
    ? resolveCloseTabs(pendingCloseAction).filter((tab) => tab.isDirty).length
    : 0;

  const pendingCloseMessage = pendingDirtyCount > 1
    ? `有 ${pendingDirtyCount} 个标签包含未保存的更改，关闭前是否保存？`
    : "关闭前是否保存对此文件的更改？";
  const pendingSaveError = pendingCloseAction
    ? resolveCloseTabs(pendingCloseAction).find((tab) => tab.saveState === "error" && tab.saveError)?.saveError ?? null
    : null;
  const pendingCloseModalMessage = [
    pendingCloseMessage,
    isCloseSaving ? "正在保存，文件较大时可能需要稍等。你仍然可以取消或不保存关闭。" : "",
    pendingSaveError || closeSaveError ? `保存失败：${pendingSaveError || closeSaveError}` : "",
  ].filter(Boolean).join("\n");

  const handleClose = (tabId: string) => {
    requestClose({ mode: "single", tabId });
  };

  const copyTabPath = (tabId: string) => {
    const tab = tabs.find((item) => item.id === tabId);
    const path = tab?.filePath ?? tab?.projectFilePath ?? tab?.displayPath ?? tabId;
    void navigator.clipboard.writeText(path).catch(() => undefined);
  };

  return (
    <div className="workspace-page__canvas-chat-shell">
      {/* 编辑区主体 */}
      <div className="workspace-page__canvas-chat-main">
        <div className="doc-editor">
          <DocumentEditorTabBar
            activeTabId={activeTabId}
            onCancelAutoScroll={cancelDocumentTabScroll}
            tabBarRef={tabBarRef}
            tabIndicator={tabIndicator}
            tabs={tabs}
            onOpenContextMenu={(tabId, x, y) => setContextMenu({ tabId, x, y })}
            onRequestClose={handleClose}
            onSelectTab={onSelectTab}
          />

          {statusMessage ? (
            <div className="doc-editor__status-error" role="status">
              {statusMessage}
            </div>
          ) : null}

          {/* 编辑区域 */}
          <div className="doc-editor__body">
            {hasPersistentEmptyContent ? (
              <div
                className={
                  persistentEmptyContentVisible
                    ? "doc-editor__persistent-empty"
                    : "doc-editor__persistent-empty doc-editor__persistent-empty--hidden"
                }
                aria-hidden={persistentEmptyContentVisible ? undefined : "true"}
              >
                {persistentEmptyContent}
              </div>
            ) : null}
            <div
              className={
                persistentEmptyContentVisible
                  ? "doc-editor__active-content doc-editor__active-content--hidden"
                  : "doc-editor__active-content"
              }
              aria-hidden={persistentEmptyContentVisible ? "true" : undefined}
            >
              <DocumentEditorActiveContent
                activeConversationMessageId={activeConversationMessageId}
                activeConversationSessionId={activeConversationSessionId}
                activeTab={activeTab}
                emptyContent={emptyContent}
                emptyMessage={emptyMessage}
                isCompressionLog={isCompressionLog}
                isConversationBranches={isConversationBranches}
                isConversationIndex={isConversationIndex}
                isConversationInjectionPreview={isConversationInjectionPreview}
                isConversationMessages={isConversationMessages}
                isConversationSession={isConversationSession}
                isGlobalMemory={isGlobalMemory}
                isHtml={isHtml}
                isMarkdown={isMarkdown}
                isPreviewable={isPreviewable}
                isProjectMemory={isProjectMemory}
                isProjectConversationOverview={isProjectConversationOverview}
                isProjectKnowledgeContent={isProjectKnowledgeContent}
                isProjectRoleConfiguration={isProjectRoleConfiguration}
                isProjectThemeConfiguration={isProjectThemeConfiguration}
                isReferenceViewer={isReferenceViewer}
                isToolDashboard={isToolDashboard}
                markdownMode={markdownMode}
                markdownAssetUrlResolver={markdownAssetUrlResolver}
                onCreatePdfPageImageReference={onCreatePdfPageImageReference}
                onCreatePresentationSlideImageReference={onCreatePresentationSlideImageReference}
                onCreateSpreadsheetRangeImageReference={onCreateSpreadsheetRangeImageReference}
                onCreateTextReference={onCreateTextReference}
                onGenerateMarkdownDocx={onGenerateMarkdownDocx}
                onReferenceWorkspaceFile={onReferenceWorkspaceFile}
                onSelectConversationMessage={onSelectConversationMessage}
                onSelectExportDirectory={onSelectExportDirectory}
                onConversationDataPageChange={onConversationDataPageChange}
                onEditorScroll={handleEditorScroll}
                onEditorScrollerReady={(scroller) => { editorScrollerRef.current = scroller; }}
                onMarkDirty={onMarkDirty}
                onMarkMissing={onMarkMissing}
                onSaveCodeBlock={onSaveCodeBlock}
                onSaveTab={onSaveTab}
                onUpdateContent={onUpdateContent}
                previewOpen={previewOpen}
                projectConversationOverviewContent={projectConversationOverviewContent}
                projectKnowledgeContent={projectKnowledgeContent}
                roleConfigurationContent={roleConfigurationContent}
                themeConfigurationContent={themeConfigurationContent}
                projectRootPath={projectRootPath}
                setMarkdownMode={setMarkdownMode}
                setPreviewOpen={setPreviewOpen}
                toolCallRecordTarget={toolCallRecordTarget}
                toolDashboardView={toolDashboardView}
                toolDependencyTarget={toolDependencyTarget}
                toolEntryCandidates={toolEntryCandidates}
              />
            </div>
          </div>
        </div>
      </div>

      {hasAssistantPanel ? (
        <>
          {/* 分隔条 */}
          <div className={aiPanel.isResizing ? "workspace-page__canvas-chat-resizer workspace-page__canvas-chat-resizer--active" : "workspace-page__canvas-chat-resizer"}
            role="separator" aria-orientation="vertical"
            onPointerDown={aiPanel.handleResizeStart} onDoubleClick={aiPanel.resetWidth} />

          {/* AI 面板 */}
          <aside className="workspace-page__ai-panel" style={{ width: aiPanel.width }}>
            {assistantPanel}
          </aside>
        </>
      ) : null}

      {/* 右键菜单 */}
      {contextMenu && (
        <ContextMenu
          onClose={() => setContextMenu(null)}
          position={{ x: contextMenu.x, y: contextMenu.y }}
        >
          <ContextMenuItem onSelect={() => { requestClose({ mode: "single", tabId: contextMenu.tabId }); setContextMenu(null); }}>
            关闭
          </ContextMenuItem>
          <ContextMenuItem onSelect={() => { requestClose({ mode: "others", tabId: contextMenu.tabId }); setContextMenu(null); }}>
            关闭其他
          </ContextMenuItem>
          <ContextMenuItem onSelect={() => { requestClose({ mode: "all" }); setContextMenu(null); }}>
            关闭所有
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem onSelect={() => { copyTabPath(contextMenu.tabId); setContextMenu(null); }}>
            复制路径
          </ContextMenuItem>
        </ContextMenu>
      )}

      {/* 未保存提示 */}
      {pendingCloseAction && (
        <ConfirmModal
          confirmDisabled={isCloseSaving}
          confirmLabel={isCloseSaving ? "保存中..." : "保存并关闭"}
          message={pendingCloseModalMessage}
          onCancel={() => {
            closeSaveRunIdRef.current += 1;
            setCloseSaveError(null);
            setIsCloseSaving(false);
            setPendingCloseAction(null);
          }}
          onConfirm={() => { void saveAndClosePendingTabs(); }}
          onSecondary={discardAndClosePendingTabs}
          secondaryDanger
          secondaryLabel={isCloseSaving ? "不保存并关闭" : "不保存"}
          title="未保存的更改"
        />
      )}
      {externalConflictTab && (
        <ConfirmModal
          cancelDisabled
          confirmDisabled={isResolvingExternalConflict || !conflictSaveAsPath.trim() || !onSaveTabAs}
          confirmLabel={isResolvingExternalConflict ? "处理中..." : "另存当前内容"}
          message={[
            "磁盘文件已在外部发生变化，编辑器里还有未保存内容。",
            "请选择用当前编辑器内容覆盖原文件，或把当前内容另存到新路径。",
            externalConflictTab.saveState === "error" && externalConflictTab.saveError
              ? `当前状态：${externalConflictTab.saveError}`
              : "",
          ].filter(Boolean).join("\n")}
          onCancel={() => undefined}
          onConfirm={() => { void saveExternalConflictAs(); }}
          onSecondary={() => { void overwriteExternalConflict(); }}
          secondaryDanger
          secondaryDisabled={isResolvingExternalConflict || !onOverwriteExternalChange}
          secondaryLabel={isResolvingExternalConflict ? "处理中..." : "覆盖原文件"}
          title="文件已在外部修改"
        >
          <label className="confirm-modal__field">
            <span className="confirm-modal__label">另存路径</span>
            <input
              className="confirm-modal__input"
              disabled={isResolvingExternalConflict}
              value={conflictSaveAsPath}
              onChange={(event) => setConflictSaveAsPath(event.target.value)}
            />
          </label>
        </ConfirmModal>
      )}
    </div>
  );
});

function getToolDashboardView(tab: DocumentTab | null): ToolDashboardView {
  if (tab?.id.includes("__tool_dashboard_dependencies__")) {
    return "dependencies";
  }
  if (tab?.id.includes("__tool_dashboard_callRecords__")) {
    return "callRecords";
  }
  if (tab?.id.includes("__tool_dashboard_permissions__")) {
    return "permissions";
  }
  return tab?.id.includes("__tool_dashboard_examples__") ? "examples" : "basics";
}

function makeExternalConflictSaveAsPath(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const slashIndex = normalized.lastIndexOf("/");
  const parent = slashIndex >= 0 ? normalized.slice(0, slashIndex + 1) : "";
  const name = slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
  const dotIndex = name.lastIndexOf(".");
  if (dotIndex <= 0) {
    return `${parent}${name}.current`;
  }
  return `${parent}${name.slice(0, dotIndex)}.current${name.slice(dotIndex)}`;
}

function getToolDependencyTarget(tab: DocumentTab | null) {
  return getToolFolderTarget(tab);
}

function getToolFolderTarget(tab: DocumentTab | null) {
  const prefix = "tool-folder:";
  const sourceKey = tab?.fileSource?.key ?? "";
  if (!sourceKey.startsWith(prefix)) return null;
  const payload = sourceKey.slice(prefix.length);
  const separatorIndex = payload.indexOf(":");
  if (separatorIndex <= 0 || separatorIndex >= payload.length - 1) return null;
  return {
    toolsetId: payload.slice(0, separatorIndex),
    folderId: payload.slice(separatorIndex + 1),
  };
}

function resolveDocumentTabScrollLeft(
  tabBar: HTMLElement,
  activeTabElement: HTMLElement,
) {
  const viewportLeft = tabBar.scrollLeft;
  const viewportRight = viewportLeft + tabBar.clientWidth;
  const activeLeft = activeTabElement.offsetLeft;
  const activeRight = activeLeft + activeTabElement.offsetWidth;
  const previousTab = findAdjacentDocumentTab(activeTabElement, "previous");
  const nextTab = findAdjacentDocumentTab(activeTabElement, "next");
  const previousFullyVisible = !previousTab ||
    (previousTab.offsetLeft >= viewportLeft &&
      previousTab.offsetLeft + previousTab.offsetWidth <= viewportRight);
  const nextFullyVisible = !nextTab ||
    (nextTab.offsetLeft >= viewportLeft &&
      nextTab.offsetLeft + nextTab.offsetWidth <= viewportRight);
  const distanceToLeft = Math.max(0, activeLeft - viewportLeft);
  const distanceToRight = Math.max(0, viewportRight - activeRight);

  let targetLeft: number | null = null;
  if (activeLeft < viewportLeft || (!previousFullyVisible && distanceToLeft <= distanceToRight)) {
    targetLeft = previousTab ? previousTab.offsetLeft : activeLeft;
  } else if (activeRight > viewportRight || (!nextFullyVisible && distanceToRight < distanceToLeft)) {
    targetLeft = nextTab
      ? nextTab.offsetLeft + nextTab.offsetWidth - tabBar.clientWidth
      : activeRight - tabBar.clientWidth;
  }

  if (targetLeft === null) return null;
  const maxScrollLeft = Math.max(0, tabBar.scrollWidth - tabBar.clientWidth);
  return Math.min(Math.max(0, targetLeft), maxScrollLeft);
}

function findAdjacentDocumentTab(
  element: HTMLElement,
  direction: "previous" | "next",
) {
  let sibling = direction === "previous"
    ? element.previousElementSibling
    : element.nextElementSibling;
  while (sibling) {
    if (sibling instanceof HTMLElement && sibling.classList.contains("doc-editor__tab")) {
      return sibling;
    }
    sibling = direction === "previous"
      ? sibling.previousElementSibling
      : sibling.nextElementSibling;
  }
  return null;
}

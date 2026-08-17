import { lazy, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { CodeEditorTextSelectionContextMenu } from "../../editor/ui/CodeEditor";
import { PaginationControls } from "../../../shared/ui/pagination-controls/PaginationControls";
import { getPreviewToggleLabel } from "../model/previewToggleLabel";
import { EditorLazyBoundary, PreviewMountGate } from "./EditorContentBoundary";

const CodeEditor = lazy(() =>
  import("../../editor/ui/CodeEditor").then((module) => ({ default: module.CodeEditor })),
);
const CompressionLogPreview = lazy(() =>
  import("../../compression-log-preview/ui/CompressionLogPreview").then((module) => ({
    default: module.CompressionLogPreview,
  })),
);
const ConversationIndexPreview = lazy(() =>
  import("../../conversation-index-preview/ui/ConversationIndexPreview").then((module) => ({
    default: module.ConversationIndexPreview,
  })),
);
const ConversationInjectionPreview = lazy(() =>
  import("../../conversation-injection-preview/ui/ConversationInjectionPreview").then((module) => ({
    default: module.ConversationInjectionPreview,
  })),
);
const ConversationMessagesPreview = lazy(() =>
  import("../../conversation-messages-preview/ui/ConversationMessagesPreview").then((module) => ({
    default: module.ConversationMessagesPreview,
  })),
);
const ConversationSessionPreview = lazy(() =>
  import("../../conversation-session-preview/ui/ConversationSessionPreview").then((module) => ({
    default: module.ConversationSessionPreview,
  })),
);
const ProjectMemoryPreview = lazy(() =>
  import("../../project-memory-preview/ui/ProjectMemoryPreview").then((module) => ({
    default: module.ProjectMemoryPreview,
  })),
);
const HtmlPreview = lazy(() =>
  import("../../html-preview/ui/HtmlPreview").then((module) => ({ default: module.HtmlPreview })),
);

export function DocumentTextContent({
  activeTab,
  boundaryKey,
  isCompressionLog,
  isConversationIndex,
  isConversationInjectionPreview,
  isConversationMessages,
  isConversationSession,
  isGlobalMemory,
  isHtml,
  isMarkdown,
  isPreviewable,
  isProjectMemory,
  onEditorScroll,
  onEditorScrollerReady,
  onMarkDirty,
  onConversationDataPageChange,
  onSaveTab,
  onSourceTextContextMenu,
  onUpdateContent,
  previewOpen,
  setPreviewOpen,
}: {
  activeTab: DocumentTab;
  boundaryKey: string;
  isCompressionLog: boolean;
  isConversationIndex: boolean;
  isConversationInjectionPreview: boolean;
  isConversationMessages: boolean;
  isConversationSession: boolean;
  isGlobalMemory: boolean;
  isHtml: boolean;
  isMarkdown: boolean;
  isPreviewable: boolean;
  isProjectMemory: boolean;
  onEditorScroll: (scroller: HTMLElement) => void;
  onEditorScrollerReady: (scroller: HTMLElement | null) => void;
  onMarkDirty: (id: string) => void;
  onConversationDataPageChange?: (tab: DocumentTab, page: number) => Promise<void>;
  onSaveTab: (id: string, contentSnapshot?: string) => Promise<boolean>;
  onSourceTextContextMenu: (selection: CodeEditorTextSelectionContextMenu) => void;
  onUpdateContent: (id: string, content: string) => void;
  previewOpen: boolean;
  setPreviewOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const [isPageLoading, setIsPageLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const dataView = activeTab.conversationDataView;
  const handlePageChange = async (page: number) => {
    if (!onConversationDataPageChange || isPageLoading) return;
    setIsPageLoading(true);
    setPageError(null);
    try {
      await onConversationDataPageChange(activeTab, page);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "分页数据读取失败。");
    } finally {
      setIsPageLoading(false);
    }
  };
  const isSystemPreviewOpen = previewOpen && (
    isHtml ||
    isCompressionLog ||
    isConversationIndex ||
    isConversationInjectionPreview ||
    isConversationMessages ||
    isConversationSession ||
    isGlobalMemory ||
    isProjectMemory
  );

  return (
    <div className="doc-editor__text-content">
      {dataView && (!isSystemPreviewOpen || !isProjectMemory) ? (
        <>
          <PaginationControls
            isLoading={isPageLoading}
            onPageChange={handlePageChange}
            page={dataView.page}
            pageSize={dataView.pageSize}
            totalCount={dataView.totalCount}
            totalPages={dataView.totalPages}
          />
          {pageError ? <div className="doc-editor__pagination-error">{pageError}</div> : null}
        </>
      ) : null}
      <div className="doc-editor__text-content-body">
      {!isSystemPreviewOpen && (
        <div className="doc-editor__full">
          <div className="doc-editor__source">
            <EditorLazyBoundary resetKey={boundaryKey}>
              <CodeEditor
                value={activeTab.content}
                languageId={activeTab.languageId}
                onChange={(content) => onUpdateContent(activeTab.id, content)}
                onDirty={() => onMarkDirty(activeTab.id)}
                onSave={(content) => void onSaveTab(activeTab.id, content)}
                onScrollerReady={onEditorScrollerReady}
                onScroll={onEditorScroll}
                onTextSelectionContextMenu={onSourceTextContextMenu}
              />
            </EditorLazyBoundary>
          </div>
        </div>
      )}

      {isPreviewable && (
        <div className="doc-editor__preview-controls">
          <button
            className="doc-editor__preview-toggle"
            type="button"
            onClick={() => setPreviewOpen((isOpen) => !isOpen)}
          >
            {getPreviewToggleLabel({
              isCompressionLog,
              isConversationIndex,
              isConversationInjectionPreview,
              isConversationMessages,
              isConversationSession,
              isGlobalMemory,
              isHtml,
              isMarkdown,
              isProjectMemory,
              previewOpen,
            })}
          </button>
        </div>
      )}

      {previewOpen && isHtml && (
        <div className="doc-editor__html-preview">
          <EditorLazyBoundary resetKey={boundaryKey}>
            <HtmlPreview htmlContent={activeTab.content} />
          </EditorLazyBoundary>
        </div>
      )}

      {previewOpen && isCompressionLog && (
        <div className="doc-editor__compression-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:compression`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <CompressionLogPreview
                content={activeTab.content}
                tabId={activeTab.id}
                onMarkDirty={onMarkDirty}
                onSaveContent={(contentSnapshot) => onSaveTab(activeTab.id, contentSnapshot)}
                onUpdateContent={onUpdateContent}
              />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}

      {previewOpen && isConversationInjectionPreview && (
        <div className="doc-editor__conversation-injection-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:injection`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <ConversationInjectionPreview content={activeTab.content} />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}

      {previewOpen && isConversationMessages && (
        <div className="doc-editor__conversation-messages-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:messages`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <ConversationMessagesPreview content={activeTab.content} />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}

      {previewOpen && isConversationSession && (
        <div className="doc-editor__conversation-session-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:session`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <ConversationSessionPreview content={activeTab.content} />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}

      {previewOpen && isConversationIndex && (
        <div className="doc-editor__conversation-index-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:index`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <ConversationIndexPreview content={activeTab.content} />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}

      {previewOpen && (isProjectMemory || isGlobalMemory) && (
        <div className="doc-editor__project-memory-preview">
          <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:memory`}>
            <EditorLazyBoundary resetKey={boundaryKey}>
              <ProjectMemoryPreview
                projectId={activeTab.projectId}
                scope={isGlobalMemory ? "global" : "project"}
              />
            </EditorLazyBoundary>
          </PreviewMountGate>
        </div>
      )}
      </div>
    </div>
  );
}

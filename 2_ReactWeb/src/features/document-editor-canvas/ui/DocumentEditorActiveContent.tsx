import { lazy } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { EditorWorkspaceFileReference } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorPdfPageImageReferenceRequest,
  EditorPresentationSlideImageReferenceRequest,
  EditorSpreadsheetRangeImageReferenceRequest,
  EditorTextReferenceDraft,
} from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { DocumentAssetPreviewContent, isDocumentAssetPreviewKind } from "./DocumentAssetPreviewContent";
import { buildEditorContentResetKey, EditorLazyBoundary, PreviewMountGate } from "./EditorContentBoundary";
import {
  MarkdownDocumentContent,
  type MarkdownDocxGenerationResult,
  type MarkdownEditorMode,
} from "./MarkdownDocumentContent";
import { DocumentTextContent } from "./DocumentTextContent";
import { useDocumentTextReferenceMenu } from "./DocumentTextReferenceMenu";
import { ToolDashboardContent, type ToolDashboardView, type ToolFolderTarget } from "./ToolDashboardContent";
import { UnsupportedDocumentContent } from "./UnsupportedDocumentContent";

const ProjectMemoryPreview = lazy(() =>
  import("../../project-memory-preview/ui/ProjectMemoryPreview").then((module) => ({
    default: module.ProjectMemoryPreview,
  })),
);
const ReferenceViewer = lazy(() =>
  import("../../reference-viewer/ui/ReferenceViewer").then((module) => ({
    default: module.ReferenceViewer,
  })),
);
const ConversationBranchDashboard = lazy(() =>
  import("../../conversation-branch-dashboard/ui/ConversationBranchDashboard").then((module) => ({
    default: module.ConversationBranchDashboard,
  })),
);

type DocumentEditorActiveContentProps = {
  activeConversationMessageId: string | null;
  activeConversationSessionId: string | null;
  activeTab: DocumentTab | null;
  emptyContent: ReactNode;
  emptyMessage: string | null;
  isCompressionLog: boolean;
  isConversationBranches: boolean;
  isConversationIndex: boolean;
  isConversationInjectionPreview: boolean;
  isConversationMessages: boolean;
  isConversationSession: boolean;
  isGlobalMemory: boolean;
  isHtml: boolean;
  isMarkdown: boolean;
  isPreviewable: boolean;
  isProjectMemory: boolean;
  isProjectConversationOverview: boolean;
  isProjectRoleConfiguration: boolean;
  isProjectThemeConfiguration: boolean;
  isReferenceViewer: boolean;
  isToolDashboard: boolean;
  markdownMode: MarkdownEditorMode;
  markdownAssetUrlResolver?: (src: string | undefined) => string | undefined;
  onEditorScroll: (scroller: HTMLElement) => void;
  onEditorScrollerReady: (scroller: HTMLElement | null) => void;
  onConversationDataPageChange?: (tab: DocumentTab, page: number) => Promise<void>;
  onMarkDirty: (id: string) => void;
  onMarkMissing: (id: string) => void;
  onCreatePdfPageImageReference?: (request: EditorPdfPageImageReferenceRequest) => Promise<void>;
  onCreatePresentationSlideImageReference?: (request: EditorPresentationSlideImageReferenceRequest) => Promise<void>;
  onCreateSpreadsheetRangeImageReference?: (request: EditorSpreadsheetRangeImageReferenceRequest) => Promise<void>;
  onCreateTextReference?: (reference: EditorTextReferenceDraft) => void;
  onReferenceWorkspaceFile?: (file: EditorWorkspaceFileReference) => void;
  onSelectConversationMessage?: (sessionId: string, messageId: string) => void;
  onSelectExportDirectory?: () => Promise<string | null>;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  onGenerateMarkdownDocx?: (tab: DocumentTab) => Promise<MarkdownDocxGenerationResult>;
  onSaveTab: (id: string, contentSnapshot?: string) => Promise<boolean>;
  onUpdateContent: (id: string, content: string) => void;
  previewOpen: boolean;
  projectConversationOverviewContent: ReactNode;
  roleConfigurationContent: ReactNode;
  themeConfigurationContent: ReactNode;
  projectRootPath: string;
  setMarkdownMode: Dispatch<SetStateAction<MarkdownEditorMode>>;
  setPreviewOpen: Dispatch<SetStateAction<boolean>>;
  toolCallRecordTarget: ToolFolderTarget;
  toolDashboardView: ToolDashboardView;
  toolDependencyTarget: ToolFolderTarget;
  toolEntryCandidates: string[];
};

export function DocumentEditorActiveContent({
  activeConversationMessageId,
  activeConversationSessionId,
  activeTab,
  emptyContent,
  emptyMessage,
  isCompressionLog,
  isConversationBranches,
  isConversationIndex,
  isConversationInjectionPreview,
  isConversationMessages,
  isConversationSession,
  isGlobalMemory,
  isHtml,
  isMarkdown,
  isPreviewable,
  isProjectMemory,
  isProjectConversationOverview,
  isProjectRoleConfiguration,
  isProjectThemeConfiguration,
  isReferenceViewer,
  isToolDashboard,
  markdownMode,
  markdownAssetUrlResolver,
  onEditorScroll,
  onEditorScrollerReady,
  onConversationDataPageChange,
  onMarkDirty,
  onMarkMissing,
  onCreatePdfPageImageReference,
  onCreatePresentationSlideImageReference,
  onCreateSpreadsheetRangeImageReference,
  onCreateTextReference,
  onReferenceWorkspaceFile,
  onSelectConversationMessage,
  onSelectExportDirectory,
  onSaveCodeBlock,
  onGenerateMarkdownDocx,
  onSaveTab,
  onUpdateContent,
  previewOpen,
  projectConversationOverviewContent,
  roleConfigurationContent,
  themeConfigurationContent,
  projectRootPath,
  setMarkdownMode,
  setPreviewOpen,
  toolCallRecordTarget,
  toolDashboardView,
  toolDependencyTarget,
  toolEntryCandidates,
}: DocumentEditorActiveContentProps) {
  const {
    handleRenderedTextContextMenu,
    handleSourceTextContextMenu,
    withTextReferenceMenu,
  } = useDocumentTextReferenceMenu({ activeTab, onCreateTextReference });

  if (!activeTab) {
    if (emptyContent) return emptyContent;
    return emptyMessage ? <div className="doc-editor__empty">{emptyMessage}</div> : null;
  }

  if (activeTab.isMissing && !activeTab.isDirty) {
    return <div className="doc-editor__empty">文件已被删除。</div>;
  }

  if (activeTab.kind === "text" && !activeTab.textContentLoaded) {
    return <LoadingStrip ariaLabel="正在加载文件内容" mode="fill" surface="dark" visual="ring" />;
  }

  const boundaryKey = buildEditorContentResetKey(activeTab);

  if (isProjectConversationOverview) {
    return projectConversationOverviewContent;
  }

  if (isProjectRoleConfiguration) {
    return roleConfigurationContent;
  }

  if (isProjectThemeConfiguration) {
    return themeConfigurationContent;
  }

  if (isToolDashboard) {
    return (
      <EditorLazyBoundary resetKey={boundaryKey}>
        <ToolDashboardContent
          activeTab={activeTab}
          toolCallRecordTarget={toolCallRecordTarget}
          toolDashboardView={toolDashboardView}
          toolDependencyTarget={toolDependencyTarget}
          toolEntryCandidates={toolEntryCandidates}
          onSaveTab={onSaveTab}
          onUpdateContent={onUpdateContent}
        />
      </EditorLazyBoundary>
    );
  }

  if (isReferenceViewer) {
    return (
      <div className="doc-editor__reference-viewer">
        <PreviewMountGate ariaLabel="正在加载引用内容" gateKey={`${activeTab.id}:reference-viewer`}>
          <EditorLazyBoundary resetKey={boundaryKey}>
            <ReferenceViewer content={activeTab.content} />
          </EditorLazyBoundary>
        </PreviewMountGate>
      </div>
    );
  }

  if (isConversationBranches) {
    return (
      <PreviewMountGate ariaLabel="正在加载会话分支" gateKey={`${activeTab.id}:conversation-branches`}>
        <EditorLazyBoundary resetKey={boundaryKey}>
          <ConversationBranchDashboard
            activeMessageId={activeConversationMessageId}
            activeSessionId={activeConversationSessionId}
            onSelectMessage={onSelectConversationMessage}
            onSelectExportDirectory={onSelectExportDirectory}
            projectId={activeTab.projectId}
            projectRootPath={projectRootPath}
          />
        </EditorLazyBoundary>
      </PreviewMountGate>
    );
  }

  if (isDocumentAssetPreviewKind(activeTab.kind)) {
    const content = (
      <DocumentAssetPreviewContent
        activeTab={activeTab}
        onCreatePdfPageImageReference={onCreatePdfPageImageReference}
        onCreatePresentationSlideImageReference={onCreatePresentationSlideImageReference}
        onCreateSpreadsheetRangeImageReference={onCreateSpreadsheetRangeImageReference}
        onMissing={() => onMarkMissing(activeTab.id)}
        onReferenceWorkspaceFile={onReferenceWorkspaceFile}
        onRenderedTextContextMenu={handleRenderedTextContextMenu}
      />
    );
    return activeTab.kind === "office" ? withTextReferenceMenu(content) : content;
  }

  if (activeTab.kind === "unsupported") {
    return <UnsupportedDocumentContent activeTab={activeTab} />;
  }

  if (isGlobalMemory) {
    return (
      <div className="doc-editor__project-memory-preview">
        <PreviewMountGate ariaLabel="正在加载看板" gateKey={`${activeTab.id}:global-memory`}>
          <EditorLazyBoundary resetKey={boundaryKey}>
            <ProjectMemoryPreview projectId={activeTab.projectId} scope="global" />
          </EditorLazyBoundary>
        </PreviewMountGate>
      </div>
    );
  }

  if (isMarkdown) {
    return withTextReferenceMenu(
      <MarkdownDocumentContent
        activeTab={activeTab}
        boundaryKey={boundaryKey}
        onRenderedTextContextMenu={handleRenderedTextContextMenu}
        onSourceTextContextMenu={handleSourceTextContextMenu}
        markdownAssetUrlResolver={markdownAssetUrlResolver}
        markdownMode={markdownMode}
        onEditorScroll={onEditorScroll}
        onEditorScrollerReady={onEditorScrollerReady}
        onMarkDirty={onMarkDirty}
        onGenerateDocx={onGenerateMarkdownDocx}
        onSaveCodeBlock={onSaveCodeBlock}
        onSaveTab={onSaveTab}
        onUpdateContent={onUpdateContent}
        setMarkdownMode={setMarkdownMode}
      />,
    );
  }

  return withTextReferenceMenu(
    <DocumentTextContent
      activeTab={activeTab}
      boundaryKey={boundaryKey}
      isCompressionLog={isCompressionLog}
      isConversationIndex={isConversationIndex}
      isConversationInjectionPreview={isConversationInjectionPreview}
      isConversationMessages={isConversationMessages}
      isConversationSession={isConversationSession}
      isGlobalMemory={isGlobalMemory}
      isHtml={isHtml}
      isMarkdown={isMarkdown}
      isPreviewable={isPreviewable}
      isProjectMemory={isProjectMemory}
      onEditorScroll={onEditorScroll}
      onEditorScrollerReady={onEditorScrollerReady}
      onConversationDataPageChange={onConversationDataPageChange}
      onMarkDirty={onMarkDirty}
      onSaveTab={onSaveTab}
      onSourceTextContextMenu={handleSourceTextContextMenu}
      onUpdateContent={onUpdateContent}
      previewOpen={previewOpen}
      setPreviewOpen={setPreviewOpen}
    />,
  );
}

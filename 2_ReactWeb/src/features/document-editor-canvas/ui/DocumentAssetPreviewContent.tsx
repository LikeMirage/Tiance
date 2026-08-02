import { lazy } from "react";
import type { MouseEvent } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import {
  createEditorWorkspaceFileReference,
  getEditorDocumentPath,
  type EditorWorkspaceFileReference,
} from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorPdfPageImageReferenceRequest,
  EditorPresentationSlideImageReferenceRequest,
  EditorSpreadsheetRangeImageReferenceRequest,
  EditorTextReferenceSource,
} from "../../../entities/editor/model/editorReference";
import { createDocumentExternalFileActions } from "../model/documentExternalFileActions";
import { resolveDocumentAssetUrl } from "../model/documentAssetUrls";
import { buildEditorContentResetKey, EditorLazyBoundary, PreviewMountGate } from "./EditorContentBoundary";

const DatabasePreview = lazy(() =>
  import("../../database-preview/ui/DatabasePreview").then((module) => ({ default: module.DatabasePreview })),
);
const ImagePreview = lazy(() =>
  import("./ImagePreview").then((module) => ({ default: module.ImagePreview })),
);
const PdfPreview = lazy(() =>
  import("../../pdf-preview/ui/PdfPreview").then((module) => ({ default: module.PdfPreview })),
);
const OfficePreview = lazy(() =>
  import("../../office-preview/ui/OfficePreview").then((module) => ({ default: module.OfficePreview })),
);
const VideoPreview = lazy(() =>
  import("./VideoPreview").then((module) => ({ default: module.VideoPreview })),
);

export function isDocumentAssetPreviewKind(kind: DocumentTab["kind"]) {
  return kind === "image"
    || kind === "video"
    || kind === "pdf"
    || kind === "database"
    || kind === "office";
}

export function DocumentAssetPreviewContent({
  activeTab,
  onCreatePdfPageImageReference,
  onCreatePresentationSlideImageReference,
  onCreateSpreadsheetRangeImageReference,
  onMissing,
  onReferenceWorkspaceFile,
  onRenderedTextContextMenu,
}: {
  activeTab: DocumentTab;
  onCreatePdfPageImageReference?: (request: EditorPdfPageImageReferenceRequest) => Promise<void>;
  onCreatePresentationSlideImageReference?: (request: EditorPresentationSlideImageReferenceRequest) => Promise<void>;
  onCreateSpreadsheetRangeImageReference?: (request: EditorSpreadsheetRangeImageReferenceRequest) => Promise<void>;
  onMissing?: () => void;
  onReferenceWorkspaceFile?: (file: EditorWorkspaceFileReference) => void;
  onRenderedTextContextMenu: (
    event: MouseEvent<HTMLElement>,
    source: EditorTextReferenceSource,
  ) => void;
}) {
  const boundaryKey = buildEditorContentResetKey(activeTab);
  const externalFileActions = createDocumentExternalFileActions(activeTab);
  const sourceFilePath = getEditorDocumentPath(activeTab);
  const workspaceFileReference = createEditorWorkspaceFileReference(activeTab);

  if (activeTab.kind === "image") {
    return (
      <EditorLazyBoundary resetKey={boundaryKey}>
        <ImagePreview
          displayPath={activeTab.displayPath}
          fileName={activeTab.title}
          onReferenceImage={onReferenceWorkspaceFile && workspaceFileReference
            ? () => onReferenceWorkspaceFile(workspaceFileReference)
            : null}
          src={resolveDocumentAssetUrl(activeTab)}
        />
      </EditorLazyBoundary>
    );
  }

  if (activeTab.kind === "video") {
    return (
      <EditorLazyBoundary resetKey={boundaryKey}>
        <VideoPreview
          displayPath={activeTab.displayPath}
          fileName={activeTab.title}
          src={resolveDocumentAssetUrl(activeTab)}
        />
      </EditorLazyBoundary>
    );
  }

  if (activeTab.kind === "pdf") {
    return (
      <PreviewMountGate ariaLabel="正在加载文件预览" gateKey={`${activeTab.id}:pdf`}>
        <EditorLazyBoundary resetKey={boundaryKey}>
          <PdfPreview
            displayPath={activeTab.displayPath}
            fileName={activeTab.title}
            onCreatePageImageReference={onCreatePdfPageImageReference
              ? (payload) => onCreatePdfPageImageReference({
                file: payload.file,
                pageNumber: payload.pageNumber,
                projectId: activeTab.projectId,
                sourceDisplayPath: payload.sourceDisplayPath,
                sourceFileName: payload.sourceFileName,
                sourceFilePath,
              })
              : null}
            onRevealFile={externalFileActions.revealFile}
            onMissing={onMissing}
            src={resolveDocumentAssetUrl(activeTab)}
          />
        </EditorLazyBoundary>
      </PreviewMountGate>
    );
  }

  if (activeTab.kind === "database") {
    return (
      <PreviewMountGate ariaLabel="正在加载数据库看板" gateKey={`${activeTab.id}:database`}>
        <EditorLazyBoundary resetKey={boundaryKey}>
          <DatabasePreview
            displayPath={activeTab.displayPath}
            fileName={activeTab.title}
            path={sourceFilePath}
            projectId={activeTab.projectId}
            refreshKey={activeTab.assetVersion ?? activeTab.mtimeMs}
          />
        </EditorLazyBoundary>
      </PreviewMountGate>
    );
  }

  if (activeTab.kind === "office") {
    return (
      <div
        className="doc-editor__reference-surface"
        onContextMenu={(event) => onRenderedTextContextMenu(event, "office")}
      >
        <EditorLazyBoundary resetKey={boundaryKey}>
          <OfficePreview
            displayPath={activeTab.displayPath}
            fileName={activeTab.title}
            onCreatePresentationSlideImageReference={onCreatePresentationSlideImageReference
              ? (payload) => onCreatePresentationSlideImageReference({
                file: payload.file,
                projectId: activeTab.projectId,
                slideNumber: payload.slideNumber,
                sourceDisplayPath: payload.sourceDisplayPath,
                sourceFileName: payload.sourceFileName,
                sourceFilePath,
              })
              : null}
            onCreateSpreadsheetRangeImageReference={onCreateSpreadsheetRangeImageReference
              ? (payload) => onCreateSpreadsheetRangeImageReference({
                cells: payload.cells,
                file: payload.file,
                projectId: activeTab.projectId,
                rangeAddress: payload.rangeAddress,
                sheetName: payload.sheetName,
                sourceDisplayPath: payload.sourceDisplayPath,
                sourceFileName: payload.sourceFileName,
                sourceFilePath,
              })
              : null}
            onOpenNativeFile={externalFileActions.openNativeFile}
            onRevealFile={externalFileActions.revealFile}
            onMissing={onMissing}
            src={resolveDocumentAssetUrl(activeTab)}
          />
        </EditorLazyBoundary>
      </div>
    );
  }

  return null;
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { EditorWorkspaceFileReference } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorExternalPathReferenceRequest,
  EditorFileReference,
  EditorImageReference,
  EditorPdfPageImageReferenceRequest,
  EditorPresentationSlideImageReferenceRequest,
  EditorSpreadsheetRangeImageReferenceRequest,
  EditorTextReference,
  EditorTextReferenceDraft,
} from "../../../entities/editor/model/editorReference";
import type { ProjectFileDragData } from "../../../entities/project/model/projectFileDragData";
import type {
  ConversationMessageReference,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import { uploadConversationImageAttachment } from "../../../services/project/uploadConversationImageAttachment";

type UseWorkspaceEditorReferencesOptions = {
  documentTabs: ReturnType<typeof useDocumentTabs>;
  projectId: string | null;
  sessionId: string | null;
};

type ImageReferenceOperation = {
  operationId: number;
  projectId: string;
  sessionId: string | null;
};

type PendingImageReference = {
  type: "pending_image";
  operationId: number;
};

type WorkspaceReferenceItem = ConversationMessageReference | PendingImageReference;

function createReferenceId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function useWorkspaceEditorReferences({
  documentTabs,
  projectId,
  sessionId,
}: UseWorkspaceEditorReferencesOptions) {
  const documentTabsRef = useRef(documentTabs);
  const projectIdRef = useRef(projectId);
  const sessionIdRef = useRef(sessionId);
  const nextImageReferenceOperationIdRef = useRef(0);
  const activeImageReferenceOperationIdsRef = useRef(new Set<number>());
  documentTabsRef.current = documentTabs;
  projectIdRef.current = projectId;
  sessionIdRef.current = sessionId;
  const [referenceItems, setReferenceItems] = useState<WorkspaceReferenceItem[]>([]);
  const [pendingImageReferenceOperationCount, setPendingImageReferenceOperationCount] = useState(0);
  const references = useMemo<ConversationMessageReferences>(
    () => referenceItems.filter(
      (item): item is ConversationMessageReference => item.type !== "pending_image",
    ),
    [referenceItems],
  );

  useEffect(() => {
    setReferenceItems([]);
  }, [projectId]);

  useEffect(() => {
    activeImageReferenceOperationIdsRef.current.clear();
    setPendingImageReferenceOperationCount(0);
    return () => {
      activeImageReferenceOperationIdsRef.current.clear();
    };
  }, [projectId, sessionId]);

  const beginImageReferenceOperation = useCallback((startedProjectId: string): ImageReferenceOperation => {
    nextImageReferenceOperationIdRef.current += 1;
    const operation = {
      operationId: nextImageReferenceOperationIdRef.current,
      projectId: startedProjectId,
      sessionId: sessionIdRef.current,
    };
    activeImageReferenceOperationIdsRef.current.add(operation.operationId);
    setReferenceItems((current) => [
      ...current,
      { type: "pending_image", operationId: operation.operationId },
    ]);
    setPendingImageReferenceOperationCount(activeImageReferenceOperationIdsRef.current.size);
    return operation;
  }, []);

  const isCurrentImageReferenceOperation = useCallback((operation: ImageReferenceOperation) => (
    activeImageReferenceOperationIdsRef.current.has(operation.operationId) &&
    projectIdRef.current === operation.projectId &&
    sessionIdRef.current === operation.sessionId
  ), []);

  const finishImageReferenceOperation = useCallback((operation: ImageReferenceOperation) => {
    if (!activeImageReferenceOperationIdsRef.current.delete(operation.operationId)) return;
    setReferenceItems((current) => current.filter(
      (item) => item.type !== "pending_image" || item.operationId !== operation.operationId,
    ));
    setPendingImageReferenceOperationCount(activeImageReferenceOperationIdsRef.current.size);
  }, []);

  const completeImageReferenceOperation = useCallback((
    operation: ImageReferenceOperation,
    reference: EditorImageReference,
  ) => {
    setReferenceItems((current) => current.map((item) => (
      item.type === "pending_image" && item.operationId === operation.operationId
        ? { type: "image", reference }
        : item
    )));
  }, []);

  const isCurrentDocumentSource = useCallback((startedProjectId: string, sourceFilePath: string) => {
    const activeTab = documentTabsRef.current.activeTab;
    if (projectIdRef.current !== startedProjectId || activeTab?.projectId !== startedProjectId) {
      return false;
    }
    return (activeTab.projectFilePath ?? activeTab.filePath ?? activeTab.displayPath) === sourceFilePath;
  }, []);

  const handleDraftReferencesChange = useCallback((nextReferences: ConversationMessageReferences) => {
    setReferenceItems(nextReferences);
  }, []);

  const handleCreateTextReference = useCallback((reference: EditorTextReferenceDraft) => {
    setReferenceItems((current) => [
      ...current,
      { type: "text", reference: {
        ...reference,
        id: createReferenceId("text-ref"),
      } },
    ]);
  }, []);

  const handleRemoveTextReference = useCallback((referenceId: string) => {
    setReferenceItems((current) => current.filter(
      (item) => item.type !== "text" || item.reference.id !== referenceId,
    ));
  }, []);

  const appendProjectFileReference = useCallback((file: {
    kind: ProjectFileDragData["kind"];
    name: string;
    path: string;
    projectId: string;
  }) => {
    setReferenceItems((current) => {
      if (current.some((item) =>
        item.type === "file" &&
        item.reference.projectId === file.projectId &&
        item.reference.filePath === file.path
      )) {
        return current;
      }
      return [
        ...current,
        { type: "file", reference: {
          displayPath: file.path,
          fileName: file.name,
          filePath: file.path,
          id: createReferenceId("file-ref"),
          kind: file.kind,
          projectId: file.projectId,
          source: "project_file",
        } },
      ];
    });
  }, []);

  const handleReferenceProjectFile = useCallback((file: ProjectFileDragData) => {
    if (!projectId || file.projectId !== projectId) return;
    appendProjectFileReference(file);
  }, [appendProjectFileReference, projectId]);

  const handleReferenceWorkspaceFile = useCallback((file: EditorWorkspaceFileReference) => {
    if (!projectId || file.fileSource.kind !== "project" || file.fileSource.id !== projectId) return;
    appendProjectFileReference({
      kind: file.kind,
      name: file.name,
      path: file.path,
      projectId,
    });
  }, [appendProjectFileReference, projectId]);

  const handleReferenceExternalPath = useCallback((externalReference: EditorExternalPathReferenceRequest) => {
    setReferenceItems((current) => {
      if (current.some((item) =>
        item.type === "file" &&
        item.reference.source === "external_path" &&
        item.reference.filePath === externalReference.path
      )) {
        return current;
      }
      return [
        ...current,
        { type: "file", reference: {
          displayPath: externalReference.path,
          fileName: externalReference.name,
          filePath: externalReference.path,
          id: createReferenceId("file-ref"),
          kind: externalReference.kind,
          projectId: null,
          source: "external_path",
        } },
      ];
    });
  }, []);

  const handleRemoveFileReference = useCallback((referenceId: string) => {
    setReferenceItems((current) => current.filter(
      (item) => item.type !== "file" || item.reference.id !== referenceId,
    ));
  }, []);

  const handleCreatePdfPageImageReference = useCallback(async (
    request: EditorPdfPageImageReferenceRequest,
  ) => {
    if (!projectId || request.projectId !== projectId) {
      throw new Error("只能引用当前项目里的 PDF 页面。");
    }
    const startedProjectId = projectId;
    const operation = beginImageReferenceOperation(startedProjectId);
    if (!operation.sessionId) {
      finishImageReferenceOperation(operation);
      throw new Error("当前没有可保存附件的会话。");
    }
    try {
      const uploaded = await uploadConversationImageAttachment(
        startedProjectId,
        operation.sessionId,
        request.file,
        { sourceKind: "preview_reference", sourcePath: request.sourceFilePath },
      );
      if (!isCurrentImageReferenceOperation(operation)) return;

      completeImageReferenceOperation(operation, {
          displayPath: uploaded.path,
          fileName: uploaded.name,
          filePath: uploaded.path,
          id: createReferenceId("image-ref"),
          imagePath: uploaded.path,
          mimeType: uploaded.mime_type,
          pageNumber: request.pageNumber,
          projectId: startedProjectId,
          sizeBytes: uploaded.size_bytes,
          source: "pdf_page",
          sourceDisplayPath: request.sourceDisplayPath,
          sourceFileName: request.sourceFileName,
          sourceFilePath: request.sourceFilePath,
      });
    } finally {
      finishImageReferenceOperation(operation);
    }
  }, [
    beginImageReferenceOperation,
    completeImageReferenceOperation,
    finishImageReferenceOperation,
    isCurrentImageReferenceOperation,
    projectId,
  ]);

  const handleCreatePresentationSlideImageReference = useCallback(async (
    request: EditorPresentationSlideImageReferenceRequest,
  ) => {
    if (!projectId || request.projectId !== projectId) {
      throw new Error("只能引用当前项目里的 PPT 页面。");
    }
    const startedProjectId = projectId;
    const operation = beginImageReferenceOperation(startedProjectId);
    if (!operation.sessionId) {
      finishImageReferenceOperation(operation);
      throw new Error("当前没有可保存附件的会话。");
    }
    try {
      const uploaded = await uploadConversationImageAttachment(
        startedProjectId,
        operation.sessionId,
        request.file,
        { sourceKind: "preview_reference", sourcePath: request.sourceFilePath },
      );
      if (!isCurrentImageReferenceOperation(operation)) return;

      completeImageReferenceOperation(operation, {
          displayPath: uploaded.path,
          fileName: uploaded.name,
          filePath: uploaded.path,
          id: createReferenceId("image-ref"),
          imagePath: uploaded.path,
          mimeType: uploaded.mime_type,
          projectId: startedProjectId,
          sizeBytes: uploaded.size_bytes,
          slideNumber: request.slideNumber,
          source: "ppt_slide",
          sourceDisplayPath: request.sourceDisplayPath,
          sourceFileName: request.sourceFileName,
          sourceFilePath: request.sourceFilePath,
      });
    } finally {
      finishImageReferenceOperation(operation);
    }
  }, [
    beginImageReferenceOperation,
    completeImageReferenceOperation,
    finishImageReferenceOperation,
    isCurrentImageReferenceOperation,
    projectId,
  ]);

  const handleCreateSpreadsheetRangeImageReference = useCallback(async (
    request: EditorSpreadsheetRangeImageReferenceRequest,
  ) => {
    if (!projectId || request.projectId !== projectId) {
      throw new Error("只能引用当前项目里的 Excel 选区。");
    }
    const startedProjectId = projectId;
    if (!isCurrentDocumentSource(startedProjectId, request.sourceFilePath)) return;
    const operation = beginImageReferenceOperation(startedProjectId);
    if (!operation.sessionId) {
      finishImageReferenceOperation(operation);
      throw new Error("当前没有可保存附件的会话。");
    }
    try {
      const uploaded = await uploadConversationImageAttachment(
        startedProjectId,
        operation.sessionId,
        request.file,
        { sourceKind: "preview_reference", sourcePath: request.sourceFilePath },
      );
      if (
        !isCurrentImageReferenceOperation(operation) ||
        !isCurrentDocumentSource(startedProjectId, request.sourceFilePath)
      ) return;

      completeImageReferenceOperation(operation, {
          cells: request.cells,
          displayPath: uploaded.path,
          fileName: uploaded.name,
          filePath: uploaded.path,
          id: createReferenceId("image-ref"),
          imagePath: uploaded.path,
          mimeType: uploaded.mime_type,
          projectId: startedProjectId,
          rangeAddress: request.rangeAddress,
          sheetName: request.sheetName,
          sizeBytes: uploaded.size_bytes,
          source: "xlsx_range",
          sourceDisplayPath: request.sourceDisplayPath,
          sourceFileName: request.sourceFileName,
          sourceFilePath: request.sourceFilePath,
      });
    } finally {
      finishImageReferenceOperation(operation);
    }
  }, [
    beginImageReferenceOperation,
    completeImageReferenceOperation,
    finishImageReferenceOperation,
    isCurrentDocumentSource,
    isCurrentImageReferenceOperation,
    projectId,
  ]);

  const handleRemoveImageReference = useCallback((referenceId: string) => {
    setReferenceItems((current) => current.filter(
      (item) => item.type !== "image" || item.reference.id !== referenceId,
    ));
  }, []);

  const handleClearReferences = useCallback(() => {
    setReferenceItems([]);
  }, []);

  return {
    handleClearReferences,
    handleCreatePdfPageImageReference,
    handleCreatePresentationSlideImageReference,
    handleCreateSpreadsheetRangeImageReference,
    handleCreateTextReference,
    handleDraftReferencesChange,
    handleReferenceExternalPath,
    handleReferenceProjectFile,
    handleReferenceWorkspaceFile,
    handleRemoveFileReference,
    handleRemoveImageReference,
    handleRemoveTextReference,
    isImageReferenceUploadPending: pendingImageReferenceOperationCount > 0,
    references,
  };
}

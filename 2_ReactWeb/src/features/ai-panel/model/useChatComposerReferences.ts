import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import type { EditorExternalPathReferenceRequest } from "../../../entities/editor/model/editorReference";
import type {
  ProjectFileDragData,
  ProjectFileReferenceRequest,
} from "../../../entities/project/model/projectFileDragData";
import { publishProjectFileMutation } from "../../../entities/project/model/projectFileMutation";
import {
  buildUserUploadImagesFolderNode,
  buildUserUploadsRootNode,
} from "../../../entities/project/model/projectUploadFolderNodes";
import { uploadProjectPastedImage } from "../../../services/project/uploadProjectPastedImage";
import type { DesktopPathEntry } from "../../../shared/types/desktopShell";
import { readDesktopClipboardPathEntries } from "../../desktop-shell/model/desktopClipboard";
import type { DesktopFileDropEvent } from "../../desktop-shell/model/desktopFileDropBridge";
import {
  filePathEntries,
  resolveComposerPathReference,
} from "./composerPathReferences";

type UseChatComposerReferencesInput = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionId: string | null;
  activeSessionIdRef: MutableRefObject<string | null>;
  onReferenceExternalPath?: (reference: EditorExternalPathReferenceRequest) => void;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  projectFileReferenceRequest?: ProjectFileReferenceRequest | null;
  projectId: string | null;
  projectRootPath: string;
  showChatView: () => void;
};

type ChatComposerUploadStatus = {
  kind: "error" | "idle" | "saving";
  message: string | null;
};

const IDLE_UPLOAD_STATUS: ChatComposerUploadStatus = { kind: "idle", message: null };

export function useChatComposerReferences({
  activeProjectIdRef,
  activeSessionId,
  activeSessionIdRef,
  onReferenceExternalPath,
  onReferenceProjectFile,
  projectFileReferenceRequest,
  projectId,
  projectRootPath,
  showChatView,
}: UseChatComposerReferencesInput) {
  const [uploadStatus, setUploadStatus] = useState<ChatComposerUploadStatus>(IDLE_UPLOAD_STATUS);
  const previousProjectIdRef = useRef(projectId);
  const uploadRequestIdRef = useRef(0);
  const previousUploadSessionIdRef = useRef<string | null>(null);
  const handledProjectFileReferenceRequestIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (previousProjectIdRef.current === projectId) return;
    previousProjectIdRef.current = projectId;
    uploadRequestIdRef.current += 1;
    setUploadStatus(IDLE_UPLOAD_STATUS);
    showChatView();
  }, [projectId, showChatView]);

  useEffect(() => {
    if (previousUploadSessionIdRef.current === activeSessionId) return;
    previousUploadSessionIdRef.current = activeSessionId;
    uploadRequestIdRef.current += 1;
    setUploadStatus(IDLE_UPLOAD_STATUS);
  }, [activeSessionId]);

  const referencePathEntries = useCallback((entries: DesktopPathEntry[]) => {
    if (!projectId) return 0;
    let referencedCount = 0;
    for (const entry of entries) {
      const resolved = resolveComposerPathReference(entry, projectId, projectRootPath);
      if (!resolved) continue;
      if (resolved.kind === "project") {
        onReferenceProjectFile?.(resolved.reference);
      } else {
        onReferenceExternalPath?.(resolved.reference);
      }
      referencedCount += 1;
    }
    return referencedCount;
  }, [onReferenceExternalPath, onReferenceProjectFile, projectId, projectRootPath]);

  const handlePasteFiles = useCallback(async (files: File[]) => {
    const requestId = uploadRequestIdRef.current + 1;
    uploadRequestIdRef.current = requestId;
    const startedSessionId = activeSessionId;
    if (!projectId) {
      setUploadStatus({ kind: "error", message: "当前没有可建立引用的项目。" });
      return;
    }
    setUploadStatus({ kind: "saving", message: null });
    try {
      const clipboardEntries = await readDesktopClipboardPathEntries();
      if (
        uploadRequestIdRef.current !== requestId ||
        activeProjectIdRef.current !== projectId ||
        activeSessionIdRef.current !== startedSessionId
      ) return;
      const pathEntries = clipboardEntries.length > 0
        ? clipboardEntries
        : filePathEntries(files);
      if (pathEntries.length > 0) {
        const referencedCount = referencePathEntries(pathEntries);
        setUploadStatus(referencedCount === pathEntries.length
          ? IDLE_UPLOAD_STATUS
          : { kind: "error", message: "部分文件路径无效，未能建立引用。" });
        return;
      }

      const imageFiles = files.filter((file) => file.type.startsWith("image/"));
      if (imageFiles.length === 0 || imageFiles.length !== files.length) {
        setUploadStatus({
          kind: "error",
          message: "无法读取所粘贴文件的本机路径，未建立引用。",
        });
        return;
      }
      for (const file of imageFiles) {
        const uploaded = await uploadProjectPastedImage(projectId, file);
        if (
          uploadRequestIdRef.current !== requestId ||
          activeProjectIdRef.current !== projectId ||
          activeSessionIdRef.current !== startedSessionId
        ) return;
        publishProjectFileMutation({
          projectId,
          node: buildUserUploadsRootNode(),
          sourceId: "chat-pasted-image",
        });
        publishProjectFileMutation({
          projectId,
          node: buildUserUploadImagesFolderNode(),
          sourceId: "chat-pasted-image",
        });
        publishProjectFileMutation({
          projectId,
          node: uploaded.node,
          sourceId: "chat-pasted-image",
        });
        onReferenceProjectFile?.({
          projectId,
          path: uploaded.path,
          name: uploaded.node.name,
          kind: "file",
        });
      }
      if (
        uploadRequestIdRef.current !== requestId ||
        activeSessionIdRef.current !== startedSessionId
      ) return;
      setUploadStatus(IDLE_UPLOAD_STATUS);
    } catch (error) {
      if (
        uploadRequestIdRef.current !== requestId ||
        activeSessionIdRef.current !== startedSessionId
      ) return;
      setUploadStatus({
        kind: "error",
        message: error instanceof Error ? error.message : "处理粘贴引用失败。",
      });
    }
  }, [
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    onReferenceProjectFile,
    projectId,
    referencePathEntries,
  ]);

  const handleDropProjectFile = useCallback((file: ProjectFileDragData) => {
    const requestId = uploadRequestIdRef.current + 1;
    uploadRequestIdRef.current = requestId;
    if (!projectId || file.projectId !== projectId) {
      setUploadStatus({ kind: "error", message: "只能拖入当前项目里的文件。" });
      return;
    }
    if (uploadRequestIdRef.current !== requestId) return;
    onReferenceProjectFile?.(file);
    setUploadStatus(IDLE_UPLOAD_STATUS);
  }, [onReferenceProjectFile, projectId]);

  const handleDropExternalPaths = useCallback((entries: EditorExternalPathReferenceRequest[]) => {
    if (entries.length === 0) return;
    uploadRequestIdRef.current += 1;
    const referencedCount = referencePathEntries(entries);
    setUploadStatus(referencedCount === entries.length
      ? IDLE_UPLOAD_STATUS
      : { kind: "error", message: "部分路径无效，未能建立引用。" });
  }, [referencePathEntries]);

  const handleExternalFileDrop = useCallback((event: DesktopFileDropEvent) => {
    if (event.kind === "resolved") {
      handleDropExternalPaths(event.entries);
      return;
    }
    setUploadStatus({
      kind: "error",
      message: "桌面壳未能读取所拖入文件的本机路径，未建立引用。",
    });
  }, [handleDropExternalPaths]);

  useEffect(() => {
    if (!projectFileReferenceRequest) return;
    if (
      handledProjectFileReferenceRequestIdRef.current ===
      projectFileReferenceRequest.requestId
    ) return;
    handledProjectFileReferenceRequestIdRef.current = projectFileReferenceRequest.requestId;
    showChatView();
    handleDropProjectFile(projectFileReferenceRequest);
  }, [handleDropProjectFile, projectFileReferenceRequest, showChatView]);

  return {
    handleDropExternalPaths,
    handleDropProjectFile,
    handleExternalFileDrop,
    handlePasteFiles,
    uploadStatus,
  };
}

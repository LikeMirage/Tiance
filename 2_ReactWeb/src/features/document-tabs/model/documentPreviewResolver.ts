import type { DocumentLanguage } from "../../../entities/editor/model/editorDocument";
import { isTextFile, resolveLanguageId } from "../../../entities/editor/model/languageMapping";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";

export type PreviewKind = "text" | "image" | "video" | "pdf" | "office" | "database" | "unsupported";

export type ResolvedPreview = {
  kind: PreviewKind;
  languageId: DocumentLanguage;
  extension: string;
};

export function resolveDocumentPreview(node: ExplorerNode | null): ResolvedPreview {
  if (!node || node.kind !== "file") {
    return { kind: "unsupported", languageId: "plaintext", extension: "" };
  }
  const dot = node.name.lastIndexOf(".");
  const extension = dot >= 0 ? node.name.slice(dot + 1) : "";
  if (isImageFileExtension(extension)) {
    return { kind: "image", languageId: "plaintext", extension };
  }
  if (isVideoFileExtension(extension)) {
    return { kind: "video", languageId: "plaintext", extension };
  }
  if (extension.toLowerCase() === "pdf") {
    return { kind: "pdf", languageId: "plaintext", extension };
  }
  if (isOfficeFileExtension(extension)) {
    return { kind: "office", languageId: "plaintext", extension };
  }
  if (isDatabaseFileExtension(extension)) {
    return { kind: "database", languageId: "plaintext", extension };
  }
  if (!isTextFile(node.name)) {
    return { kind: "unsupported", languageId: "plaintext", extension };
  }
  return {
    kind: "text",
    languageId: resolveLanguageId(node.name),
    extension,
  };
}

const imageFileExtensions = new Set([
  "bmp",
  "gif",
  "ico",
  "jpeg",
  "jpg",
  "png",
  "svg",
  "webp",
]);

const videoFileExtensions = new Set([
  "m4v",
  "mov",
  "mp4",
  "ogv",
  "webm",
]);

const officeFileExtensions = new Set([
  "docx",
  "xls",
  "xlsx",
  "pptx",
]);

function isImageFileExtension(extension: string) {
  return imageFileExtensions.has(extension.toLowerCase());
}

function isVideoFileExtension(extension: string) {
  return videoFileExtensions.has(extension.toLowerCase());
}

function isOfficeFileExtension(extension: string) {
  return officeFileExtensions.has(extension.toLowerCase());
}

function isDatabaseFileExtension(extension: string) {
  return ["db", "sqlite", "sqlite3"].includes(extension.toLowerCase());
}

import type {
  EditorImageReference,
  EditorReferenceViewerPayload,
  EditorTextReference,
} from "../../../entities/editor/model/editorReference";
import type { ConversationMessageReferences } from "../../../entities/llm-chat/model/chatCompletion";
import type { ChatMessage } from "./chatMessage";
import { isImageFileReference, textReferencePosition } from "./conversationReferences";

export type UserMessageReferenceKind =
  | "excel"
  | "file"
  | "folder"
  | "image"
  | "pdf"
  | "ppt"
  | "text";

export type UserMessageReferenceDisplay = {
  detail: string;
  index: number;
  kind: UserMessageReferenceKind;
  meta: string;
  title: string;
  viewerPayload: EditorReferenceViewerPayload;
};

export type ReferencedUserMessage = {
  references: UserMessageReferenceDisplay[];
  userContent: string;
};

export function buildReferencedUserMessage(
  message: Pick<ChatMessage, "content" | "references">,
): ReferencedUserMessage | null {
  if (!hasReferences(message.references)) return null;
  return {
    references: buildUserMessageReferenceDisplays(message.references),
    userContent: message.content,
  };
}

export function resolveUserMessageContent(
  message: Pick<ChatMessage, "content">,
): string {
  return message.content;
}

function buildUserMessageReferenceDisplays(
  references: ConversationMessageReferences | undefined,
): UserMessageReferenceDisplay[] {
  if (!references) return [];
  const displays: UserMessageReferenceDisplay[] = [];
  for (const [offset, item] of references.entries()) {
    const index = offset + 1;
    if (item.type === "file") {
      const reference = item.reference;
      const image = isImageFileReference(reference);
      displays.push({
        detail: reference.filePath,
        index,
        kind: image ? "image" : reference.kind,
        meta: image
          ? "图片"
          : reference.source === "external_path"
            ? `外部路径${reference.kind === "folder" ? "文件夹" : "文件"}`
            : `工作区${reference.kind === "folder" ? "文件夹" : "文件"}`,
        title: reference.fileName,
        viewerPayload: { kind: "file", reference },
      });
    } else if (item.type === "text") {
      displays.push(textReferenceDisplay(index, item.reference));
    } else {
      displays.push(imageReferenceDisplay(index, item.reference));
    }
  }

  return displays;
}

function textReferenceDisplay(
  index: number,
  reference: EditorTextReference,
): UserMessageReferenceDisplay {
  return {
    detail: compactText(reference.content),
    index,
    kind: "text",
    meta: textReferencePosition(reference),
    title: reference.fileName,
    viewerPayload: { kind: "text", reference },
  };
}

function imageReferenceDisplay(
  index: number,
  reference: EditorImageReference,
): UserMessageReferenceDisplay {
  const kind = imageReferenceKind(reference);
  return {
    detail: reference.imagePath,
    index,
    kind,
    meta: imageReferenceMeta(reference),
    title: reference.sourceFileName,
    viewerPayload: { kind: "image", reference },
  };
}

function imageReferenceKind(reference: EditorImageReference): UserMessageReferenceKind {
  if (reference.source === "pdf_page") return "pdf";
  if (reference.source === "ppt_slide") return "ppt";
  return "excel";
}

function imageReferenceMeta(reference: EditorImageReference) {
  if (reference.source === "pdf_page") {
    return reference.pageNumber ? `第${reference.pageNumber}页` : "第-页";
  }
  if (reference.source === "ppt_slide") {
    return reference.slideNumber ? `第${reference.slideNumber}页` : "第-页";
  }
  return [reference.sheetName, reference.rangeAddress].filter(Boolean).join(" ") || "Excel 选区";
}

function compactText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function hasReferences(references: ConversationMessageReferences | undefined) {
  return Boolean(references?.length);
}

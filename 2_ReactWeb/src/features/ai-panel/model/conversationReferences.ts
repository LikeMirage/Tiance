import type { EditorFileReference, EditorTextReference } from "../../../entities/editor/model/editorReference";
import { textReferenceLocationLabel } from "../../../entities/editor/model/editorTextReferenceLocation";
import type {
  ChatCompletionMessageContentPart,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";

export function hasConversationReferences(references: ConversationMessageReferences) {
  return references.length > 0;
}

export function buildConversationImageContentParts(
  references: ConversationMessageReferences,
  projectId: string | null,
): ChatCompletionMessageContentPart[] {
  if (!projectId) return [];
  const parts: ChatCompletionMessageContentPart[] = [];

  for (const item of references) {
    if (item.type === "file") {
      const reference = item.reference;
      const mimeType = supportedImageMimeType(reference.fileName, reference.filePath);
      if (!mimeType || reference.kind !== "file") continue;
      parts.push(imageRefPart({
        path: reference.filePath,
        mimeType,
        name: reference.fileName,
      }));
    } else if (item.type === "image") {
      const reference = item.reference;
      if (reference.projectId !== projectId) continue;
      const mimeType = supportedImageMimeType(
        reference.fileName,
        reference.imagePath,
        reference.mimeType,
      );
      if (!mimeType) continue;
      parts.push(imageRefPart({
        path: reference.imagePath,
        mimeType,
        name: reference.fileName,
        sizeBytes: reference.sizeBytes,
      }));
    }
  }

  return parts;
}

export function textReferencePosition(reference: EditorTextReference) {
  return textReferenceLocationLabel(reference);
}

export function isImageFileReference(reference: EditorFileReference) {
  if (reference.kind !== "file") return false;
  return (
    /(^|[/\\])\.Tiance[/\\]conversation_references[/\\]images[/\\]/i.test(reference.filePath) ||
    /\.(png|jpe?g|webp|gif|bmp|tiff?|svg)$/i.test(reference.fileName) ||
    /\.(png|jpe?g|webp|gif|bmp|tiff?|svg)$/i.test(reference.filePath)
  );
}

function imageRefPart({
  mimeType,
  name,
  path,
  sizeBytes,
}: {
  mimeType: string;
  name: string;
  path: string;
  sizeBytes?: number;
}): ChatCompletionMessageContentPart {
  return {
    type: "image_ref",
    image_ref: {
      path,
      mime_type: mimeType,
      detail: "auto",
      name,
      size_bytes: sizeBytes ?? null,
    },
  };
}

function supportedImageMimeType(
  fileName: string,
  filePath: string,
  explicitMimeType?: string,
) {
  const explicit = normalizeSupportedImageMimeType(explicitMimeType);
  if (explicit) return explicit;
  const value = `${fileName} ${filePath}`.toLowerCase();
  if (/\.(png)(\s|$)/i.test(value)) return "image/png";
  if (/\.(jpe?g)(\s|$)/i.test(value)) return "image/jpeg";
  if (/\.(webp)(\s|$)/i.test(value)) return "image/webp";
  if (/\.(gif)(\s|$)/i.test(value)) return "image/gif";
  if (/\.(bmp)(\s|$)/i.test(value)) return "image/bmp";
  return null;
}

function normalizeSupportedImageMimeType(value?: string) {
  const mimeType = value?.split(";", 1)[0]?.trim().toLowerCase();
  if (
    mimeType === "image/png" ||
    mimeType === "image/jpeg" ||
    mimeType === "image/webp" ||
    mimeType === "image/gif" ||
    mimeType === "image/bmp"
  ) {
    return mimeType;
  }
  return null;
}

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { HttpRequestError } from "../../../services/http/httpClient";


export type TextContentUnavailable = NonNullable<DocumentTab["textContentUnavailable"]>;


export function getTextContentUnavailable(error: unknown): TextContentUnavailable | null {
  if (!(error instanceof HttpRequestError) || error.code !== "editor_text_file_too_large") {
    return null;
  }
  const details = asRecord(error.details);
  const sizeBytes = asNonNegativeInteger(details?.size_bytes);
  const limitBytes = asNonNegativeInteger(details?.limit_bytes);
  if (sizeBytes === null || limitBytes === null) return null;
  return { reason: "too_large", sizeBytes, limitBytes };
}


function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}


function asNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

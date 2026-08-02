import type { OfficeKind } from "./officePreviewTypes";

export const OFFICE_PREVIEW_MIN_ZOOM = 0.35;
export const OFFICE_PREVIEW_MAX_ZOOM = 2.5;

export function resolveOfficeKind(fileName: string): OfficeKind {
  const extension = fileName.split(".").pop()?.toLowerCase() ?? "";
  if (extension === "docx") return "word";
  if (extension === "xlsx" || extension === "xls") return "spreadsheet";
  if (extension === "pptx") return "presentation";
  return "unsupported";
}

export function clampOfficeZoom(value: number) {
  return Math.max(
    OFFICE_PREVIEW_MIN_ZOOM,
    Math.min(OFFICE_PREVIEW_MAX_ZOOM, Math.round(value * 100) / 100),
  );
}

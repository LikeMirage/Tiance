import { fetchJson } from "../../../services/http/httpClient";

export type FilePreviewInspection = {
  mode: "inline" | "paged" | "blocked";
  version?: string;
  message?: string;
  size_bytes?: number;
  expanded_bytes?: number;
  sheets?: Array<{ name: string; rows: number; columns: number }>;
  page_rows?: number;
  page_columns?: number;
  delimited?: { encoding: string; delimiter: string };
};

export function isDelimitedFile(fileName: string) {
  return /\.(csv|tsv)$/i.test(fileName);
}

export function delimitedPreviewUrl(src: string, encoding: string, delimiter: string) {
  const url = new URL(src, window.location.href);
  url.searchParams.set("encoding", encoding);
  url.searchParams.set("delimiter", delimiter);
  return url.toString();
}

export function checkedPreviewUrl(src: string, inspection: FilePreviewInspection) {
  const url = new URL(src, window.location.href);
  if (inspection.version) url.searchParams.set("preview_version", inspection.version);
  if (inspection.delimited) {
    url.searchParams.set("encoding", inspection.delimited.encoding);
    url.searchParams.set("delimiter", inspection.delimited.delimiter);
  }
  return url.toString();
}

export type SpreadsheetPage = {
  version: string;
  sheet_name: string;
  row_start: number;
  column_start: number;
  values: string[][];
};

// Use the already resolved source URL: tool folders and projects retain their
// own identity/authorization. Never resolve against the currently visible project.
export function previewEndpoint(assetUrl: string, operation = "") {
  const url = new URL(assetUrl, window.location.href);
  if (!url.pathname.endsWith("/files/asset")) throw new Error("无效的文件预览来源。");
  url.pathname = url.pathname.slice(0, -5) + "preview" + operation;
  url.searchParams.delete("preview_version");
  return url.toString();
}

export function inspectFilePreview(src: string, signal: AbortSignal) {
  return fetchJson<FilePreviewInspection>(previewEndpoint(src), { signal });
}

export async function readSpreadsheetPage(
  src: string, version: string, sheet: number, row: number, column: number, signal: AbortSignal,
) {
  const url = new URL(previewEndpoint(src, "/spreadsheet"));
  for (const [key, value] of Object.entries({ version, sheet, row, column })) {
    url.searchParams.set(key, String(value));
  }
  const result = await fetchJson<SpreadsheetPage & { mode?: string; message?: string }>(url.toString(), { signal });
  if (result.mode === "blocked") throw new Error(result.message);
  if (result.version !== version) throw new Error("文件版本已变化，请重新打开预览。");
  return result;
}

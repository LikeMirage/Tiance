import type {
  ToolCallRecord,
  ToolCallRecordListResponse,
  ToolCallRecordOverviewResponse,
  ToolCallRecordSummaryResponse,
} from "../../entities/tool/model/toolCallRecord";
import { fetchJson } from "../http/httpClient";

export function getToolCallRecordOverview(init?: Pick<RequestInit, "signal">) {
  return fetchJson<ToolCallRecordOverviewResponse>("/api/tools/call-record-summary", {
    cache: "no-store",
    signal: init?.signal,
  });
}

export function getToolFolderCallRecords(
  toolsetId: string,
  folderId: string,
  options: { offset?: number; limit?: number; snapshot?: string | null; signal?: AbortSignal } = {},
) {
  const query = new URLSearchParams({
    offset: String(options.offset ?? 0),
    limit: String(options.limit ?? 50),
  });
  if (options.snapshot) query.set("snapshot", options.snapshot);
  return fetchJson<ToolCallRecordListResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/call-records?${query}`,
    {
      cache: "no-store",
      signal: options.signal,
    },
  );
}

export function getToolFolderCallRecord(
  toolsetId: string,
  folderId: string,
  recordId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ToolCallRecord>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/call-records/${encodeURIComponent(recordId)}`,
    { cache: "no-store", signal: init?.signal },
  );
}

export function getToolsetCallRecordSummary(
  toolsetId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ToolCallRecordSummaryResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/call-record-summary`,
    {
      signal: init?.signal,
    },
  );
}

import type {
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
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ToolCallRecordListResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/call-records`,
    {
      signal: init?.signal,
    },
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

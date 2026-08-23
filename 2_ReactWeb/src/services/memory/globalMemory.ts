import type {
  GlobalMemoryEventListResponse,
  GlobalMemoryOperationInput,
  GlobalMemoryOperationResponse,
  GlobalMemoryRecordListResponse,
  GlobalMemoryRecordView,
} from "../../entities/global-memory/model/globalMemory";
import { fetchJson } from "../http/httpClient";


export function getGlobalMemoryRecords({
  page,
  pageSize = 50,
  query = "",
  signal,
  status,
}: {
  page?: number;
  pageSize?: number;
  query?: string;
  signal?: AbortSignal;
  status: GlobalMemoryRecordView;
}) {
  const params = new URLSearchParams({
    page_size: String(pageSize),
    query,
    status,
  });
  if (page !== undefined) params.set("page", String(page));
  return fetchJson<GlobalMemoryRecordListResponse>(
    `/api/memory/global/records?${params.toString()}`,
    { signal },
  );
}


export function getGlobalMemoryEvents({
  page = 1,
  pageSize = 50,
  query = "",
  signal,
}: {
  page?: number;
  pageSize?: number;
  query?: string;
  signal?: AbortSignal;
}) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    query,
  });
  return fetchJson<GlobalMemoryEventListResponse>(
    `/api/memory/global/events?${params.toString()}`,
    { signal },
  );
}


export function applyGlobalMemoryOperation(input: GlobalMemoryOperationInput) {
  return fetchJson<GlobalMemoryOperationResponse>("/api/memory/global/operations", {
    body: JSON.stringify(input),
    method: "POST",
  });
}

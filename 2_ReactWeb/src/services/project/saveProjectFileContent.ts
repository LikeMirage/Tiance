import type { ProjectFileNode } from "../../entities/project/model/project";
import { isAbortError } from "../http/httpErrors";
import { fetchJson } from "../http/httpClient";

const SAVE_PROJECT_FILE_TIMEOUT_MS = 60000;

export function saveProjectFileContent(
  projectId: string,
  path: string,
  content: string,
  options?: Pick<RequestInit, "signal"> & { expectedMtimeMs?: number | null },
) {
  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = window.setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, SAVE_PROJECT_FILE_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (options?.signal?.aborted) {
    controller.abort();
  } else {
    options?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const payload: { content: string; expected_mtime_ms?: number } = { content };
  if (options?.expectedMtimeMs != null) {
    payload.expected_mtime_ms = options.expectedMtimeMs;
  }

  return fetchJson<ProjectFileNode>(
    `/api/projects/${encodeURIComponent(projectId)}/files/content?path=${encodeURIComponent(path)}`,
    { method: "PUT", body: JSON.stringify(payload), signal: controller.signal },
  ).catch((err) => {
    if (isAbortError(err) && didTimeout) {
      throw new Error("文件保存超时，请稍后重试。");
    }
    throw err;
  }).finally(() => {
    window.clearTimeout(timeoutId);
    options?.signal?.removeEventListener("abort", abortFromCaller);
  });
}

import type { ProjectFileNode } from "../../entities/project/model/project";
import { isAbortError } from "../http/httpErrors";
import { fetchJson } from "../http/httpClient";

const GENERATE_MARKDOWN_DOCX_TIMEOUT_MS = 120000;

export type ProjectMarkdownToDocxResponse = {
  project_id: string;
  source_path: string;
  output_path: string;
  node: ProjectFileNode;
  warnings: string[];
};

export type ProjectMarkdownToDocxRequest = {
  path: string;
  content: string;
  page_orientation?: "portrait" | "landscape";
  page_size?: "letter" | "a4";
};

export function generateProjectMarkdownDocx(
  projectId: string,
  payload: ProjectMarkdownToDocxRequest,
) {
  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = window.setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, GENERATE_MARKDOWN_DOCX_TIMEOUT_MS);

  return fetchJson<ProjectMarkdownToDocxResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files/markdown-to-docx`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      signal: controller.signal,
    },
  ).catch((err) => {
    if (isAbortError(err) && didTimeout) {
      throw new Error("Word 生成超时，请稍后重试。");
    }
    throw err;
  }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

import { fetchJson } from "../http/httpClient";
import { readFileAsBase64 } from "./readFileAsBase64";

export type ConversationImageAttachmentResponse = {
  project_id: string;
  session_id: string;
  attachment_id: string;
  path: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  source_kind: string;
  source_path: string | null;
};

export async function uploadConversationImageAttachment(
  projectId: string,
  sessionId: string,
  file: File,
  options?: Pick<RequestInit, "signal"> & {
    sourceKind?: "clipboard" | "preview_reference";
    sourcePath?: string | null;
  },
): Promise<ConversationImageAttachmentResponse> {
  if (!file.type.startsWith("image/")) {
    throw new Error("只能保存图片文件。");
  }
  const dataBase64 = await readFileAsBase64(file);
  return fetchJson<ConversationImageAttachmentResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/attachments/images`,
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name || null,
        mime_type: file.type,
        data_base64: dataBase64,
        source_kind: options?.sourceKind ?? "clipboard",
        source_path: options?.sourcePath ?? null,
      }),
      signal: options?.signal,
    },
  );
}

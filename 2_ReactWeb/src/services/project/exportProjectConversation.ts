import { fetchJson } from "../http/httpClient";

export type ProjectConversationExportPayload = {
  base_name: string;
  content: {
    assistant_content: boolean;
    error_messages: boolean;
    images: boolean;
    message_metadata: boolean;
    model_info: boolean;
    session_info: boolean;
    system_messages: boolean;
    thinking: boolean;
    timestamps: boolean;
    token_usage: boolean;
    tool_calls: boolean;
    tool_results: boolean;
    user_messages: boolean;
  };
  format: "docx" | "markdown" | "txt" | "html" | "json";
  message_id: string | null;
  open_after_export: boolean;
  range: "conversation" | "message" | "through-message" | "from-message";
  target_directory: string;
};

export type ProjectConversationExportResponse = {
  container_path: string;
  format: ProjectConversationExportPayload["format"];
  message_count: number;
  output_path: string;
  warnings: string[];
};

export function exportProjectConversation(
  projectId: string,
  sessionId: string,
  payload: ProjectConversationExportPayload,
) {
  return fetchJson<ProjectConversationExportResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/exports`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

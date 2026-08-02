import { fetchJson } from "../http/httpClient";

type StopChatCompletionStreamResponse = {
  stopped: boolean;
};

export async function stopChatCompletionStream(projectId: string, sessionId: string) {
  return fetchJson<StopChatCompletionStreamResponse>("/api/llm/chat/completions/stream/stop", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      session_id: sessionId,
    }),
  });
}

import type { ChatCompletionRequest } from "../../entities/llm-chat/model/chatCompletion";
import { fetchJson } from "../http/httpClient";

export function updateChatInjectionPreview(
  input: ChatCompletionRequest,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<{ ok: boolean }>("/api/llm/chat/injection-preview", {
    method: "POST",
    body: JSON.stringify(input),
    signal: init?.signal,
  });
}

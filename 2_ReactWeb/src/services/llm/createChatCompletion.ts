import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
} from "../../entities/llm-chat/model/chatCompletion";
import { fetchJson } from "../http/httpClient";

export function createChatCompletion(input: ChatCompletionRequest) {
  return fetchJson<ChatCompletionResponse>("/api/llm/chat/completions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

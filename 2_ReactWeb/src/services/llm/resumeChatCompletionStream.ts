import type { ChatStreamEvent } from "../../entities/llm-chat/model/chatCompletion";
import { resumeChatCompletionOverSocket } from "./chatCompletionSocket";

export async function resumeChatCompletionStream(
  projectId: string,
  sessionId: string,
  onEvent: (event: ChatStreamEvent) => void | Promise<void>,
  signal?: AbortSignal,
  checkpointMessageId?: string | null,
) {
  await resumeChatCompletionOverSocket(projectId, sessionId, onEvent, {
    checkpointMessageId,
    signal,
  });
}

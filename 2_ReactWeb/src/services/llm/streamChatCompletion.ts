import type { ChatCompletionRequest, ChatStreamEvent } from "../../entities/llm-chat/model/chatCompletion";
import { streamChatCompletionOverSocket } from "./chatCompletionSocket";

type StreamChatCompletionHandlers = {
  onEvent: (event: ChatStreamEvent) => void | Promise<void>;
  onOpen?: () => void;
};

export async function streamChatCompletion(
  input: ChatCompletionRequest,
  handlers: StreamChatCompletionHandlers,
  init?: Pick<RequestInit, "signal">,
) {
  await streamChatCompletionOverSocket(input, handlers.onEvent, {
    onOpen: handlers.onOpen,
    signal: init?.signal ?? undefined,
  });
}

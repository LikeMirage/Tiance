import type { ChatStreamEvent } from "../../entities/llm-chat/model/chatCompletion";
import { parseHttpErrorPayload } from "../http/httpClient";

type ChatStreamEventHandler = (event: ChatStreamEvent) => void | Promise<void>;

export async function readChatCompletionEventStream(
  response: Response,
  onEvent: ChatStreamEventHandler,
  signal?: AbortSignal,
) {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("响应流不可用。");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += normalizeSseChunk(decoder.decode(value, { stream: true }));
      buffer = await dispatchCompleteSseEvents(buffer, onEvent);
    }

    const finalChunk = decoder.decode();
    if (finalChunk) {
      buffer += normalizeSseChunk(finalChunk);
      buffer = await dispatchCompleteSseEvents(buffer, onEvent);
    }

    const tail = parseSseEvent(buffer);
    if (tail) {
      await onEvent(tail);
    }
  } finally {
    if (signal?.aborted) {
      await reader.cancel().catch(() => undefined);
    }
    try {
      reader.releaseLock();
    } catch {
      // The stream can already be released by the platform after an abort.
    }
  }
}

export async function buildChatStreamErrorMessage(response: Response) {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return parseHttpErrorPayload(await response.json())?.message
        ?? `Request failed with status ${response.status}.`;
    } catch {
      return `Request failed with status ${response.status}.`;
    }
  }
  return `Request failed with status ${response.status}.`;
}

async function dispatchCompleteSseEvents(
  buffer: string,
  onEvent: ChatStreamEventHandler,
) {
  const events = buffer.split(/\n\n+/);
  const tail = events.pop() ?? "";
  for (const eventBlock of events) {
    const event = parseSseEvent(eventBlock);
    if (event) {
      await onEvent(event);
    }
  }
  return tail;
}

function parseSseEvent(block: string): ChatStreamEvent | null {
  const dataLines = block
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) {
    return null;
  }

  const data = dataLines.join("\n");
  if (!data || data === "[DONE]") {
    return null;
  }

  try {
    return JSON.parse(data) as ChatStreamEvent;
  } catch {
    throw new Error("流式响应事件解析失败。");
  }
}

function normalizeSseChunk(chunk: string) {
  return chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

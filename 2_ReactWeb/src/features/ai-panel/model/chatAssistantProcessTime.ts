import type { ChatAssistantProcessItem, ChatMessage } from "./chatMessage";

export function findLastRunningThinkingId(items: ChatAssistantProcessItem[]) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.type === "thinking" && item.status === "running") {
      return item.id;
    }
  }
  return null;
}

export function resolveProcessElapsedSeconds(
  item: Extract<ChatAssistantProcessItem, { type: "thinking" }>,
  clockTick: number,
) {
  const end = item.finishedAt ?? clockTick;
  return Math.max(0, Math.floor((end - item.startedAt) / 1000));
}

export function resolveAssistantMessageElapsedSeconds(
  message: ChatMessage,
  clockTick: number,
) {
  const start = message.createdAt ?? findEarliestProcessTime(message.processItems ?? []);
  if (!start) return null;
  const isRunning = message.status === "running";
  const end = isRunning
    ? clockTick
    : message.updatedAt ?? findLatestProcessTime(message.processItems ?? []) ?? clockTick;
  if (!end || end < start) return null;
  return Math.max(0, Math.floor((end - start) / 1000));
}

function findEarliestProcessTime(items: ChatAssistantProcessItem[]) {
  const times: number[] = [];
  items.forEach((item) => {
    if (item.type === "thinking" || item.type === "tool_preparing") {
      times.push(item.startedAt);
      return;
    }
    if (item.type === "tool" && item.tool.startedAt !== null) {
      times.push(item.tool.startedAt);
    }
  });
  return times.length > 0 ? Math.min(...times) : null;
}

function findLatestProcessTime(items: ChatAssistantProcessItem[]) {
  const times: number[] = [];
  items.forEach((item) => {
    if (item.type === "thinking" && item.finishedAt !== null) {
      times.push(item.finishedAt);
      return;
    }
    if (item.type === "tool" && item.tool.finishedAt !== null) {
      times.push(item.tool.finishedAt);
    }
  });
  return times.length > 0 ? Math.max(...times) : null;
}

import type { ConversationRuntimeStatus, ConversationSession } from "../../../entities/llm-chat/model/conversation";

type RuntimeStatusLabels = Record<"error" | "idle" | "running", string>;

export function formatRuntimeStatus(
  status: ConversationRuntimeStatus,
  labels: RuntimeStatusLabels,
) {
  if (status === "running") return labels.running;
  if (status === "error") return labels.error;
  return labels.idle;
}

export function buildHistoryStatusClass(status: ConversationRuntimeStatus) {
  return [
    "ai-panel__history-status",
    `ai-panel__history-status--${status}`,
  ].join(" ");
}

export function formatSessionUpdatedAt(value: string, language: string, unknownTimeLabel: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return unknownTimeLabel;
  }

  const now = new Date();
  const isSameYear = date.getFullYear() === now.getFullYear();
  const isSameDay = isSameYear
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  const time = date.toLocaleTimeString(language, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  if (isSameDay) {
    return time;
  }

  const datePart = date.toLocaleDateString(language, {
    month: "2-digit",
    day: "2-digit",
  });
  if (isSameYear) {
    return `${datePart} ${time}`;
  }

  return `${date.getFullYear()}/${datePart} ${time}`;
}

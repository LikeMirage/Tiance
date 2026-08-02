export type ConversationExportFormat = "docx" | "markdown" | "txt" | "html" | "json";

export type ConversationExportRange =
  | "conversation"
  | "message"
  | "through-message"
  | "from-message";

export type ConversationExportContentKey =
  | "sessionInfo"
  | "assistantContent"
  | "userMessages"
  | "thinking"
  | "toolCalls"
  | "toolResults"
  | "errorMessages"
  | "systemMessages"
  | "timestamps"
  | "images"
  | "modelInfo"
  | "tokenUsage"
  | "messageMetadata";

export type ConversationExportContentSelection = Record<
  ConversationExportContentKey,
  boolean
>;

export type ConversationExportRequest = {
  initialDirectory: string;
  messageId: string | null;
  projectId: string;
  scope: "conversation" | "message";
  sessionId: string;
  sessionTitle: string;
};

export const CONVERSATION_EXPORT_FORMATS: ReadonlyArray<{
  extension: string;
  format: ConversationExportFormat;
}> = [
  { format: "docx", extension: ".docx" },
  { format: "markdown", extension: ".md" },
  { format: "txt", extension: ".txt" },
  { format: "html", extension: ".html" },
  { format: "json", extension: ".json" },
];

const COMMON_CONTENT_OPTIONS: ConversationExportContentKey[] = [
  "sessionInfo",
  "assistantContent",
  "userMessages",
  "thinking",
  "toolCalls",
  "toolResults",
  "errorMessages",
  "systemMessages",
  "timestamps",
  "modelInfo",
  "tokenUsage",
];

export const DEFAULT_CONVERSATION_EXPORT_CONTENT: ConversationExportContentSelection = {
  sessionInfo: true,
  assistantContent: true,
  userMessages: true,
  thinking: false,
  toolCalls: false,
  toolResults: false,
  errorMessages: true,
  systemMessages: false,
  timestamps: false,
  images: true,
  modelInfo: false,
  tokenUsage: false,
  messageMetadata: false,
};

export function getConversationExportContentOptions(
  format: ConversationExportFormat,
): ConversationExportContentKey[] {
  if (format === "json") {
    return [...COMMON_CONTENT_OPTIONS, "messageMetadata"];
  }
  if (format === "txt") {
    return COMMON_CONTENT_OPTIONS;
  }
  return [...COMMON_CONTENT_OPTIONS, "images"];
}

export function getDefaultConversationExportRange(
  request: ConversationExportRequest,
): ConversationExportRange {
  return request.scope === "conversation" ? "conversation" : "message";
}

export function buildConversationExportBaseName(
  request: ConversationExportRequest,
  now = new Date(),
) {
  const normalizedTitle = (request.sessionTitle.trim() || "会话")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/g, "")
    .replace(/_+$/g, "")
    .trim();
  return `${normalizedTitle || "会话"}_${formatExportTimestamp(now)}`;
}

function formatExportTimestamp(value: Date) {
  const date = [
    value.getFullYear(),
    padDatePart(value.getMonth() + 1),
    padDatePart(value.getDate()),
  ].join("-");
  const time = [
    padDatePart(value.getHours()),
    padDatePart(value.getMinutes()),
    padDatePart(value.getSeconds()),
  ].join("-");
  return `${date}_${time}`;
}

function padDatePart(value: number) {
  return String(value).padStart(2, "0");
}

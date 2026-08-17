export type JsonRecord = Record<string, unknown>;

export type CompressionItem = {
  content: string;
  keywords: string[];
};

export type CompressionFailure = {
  stage: string;
  reason: string;
  message: string;
};

export type CompressionRecord = {
  lineNumber: number;
  rawLine: string;
  raw: JsonRecord;
  status: string;
  handoff: string;
  compressionId: string;
  functionSessionId: string;
  sourceType: string;
  mode: string;
  attemptIndex: number;
  retryOf: string;
  sourceMessageCount: number;
  newlyCoveredMessageCount: number;
  supersedesCompressionId: string;
  sourceTokenCount: number;
  compressedTokenCount: number;
  compressionRatio: number;
  providerId: string;
  modelId: string;
  createdAt: string;
  completedAt: string;
  sourceMessageIds: string[];
  items: CompressionItem[];
  failure: CompressionFailure | null;
};

export type ParsedCompressionLine =
  | {
    kind: "record";
    record: CompressionRecord;
  }
  | {
    kind: "error";
    lineNumber: number;
    rawLine: string;
    message: string;
  };

export function parseCompressionLog(content: string): {
  parsedLines: ParsedCompressionLine[];
  totalLineCount: number;
} {
  const parsedLines: ParsedCompressionLine[] = [];
  let totalLineCount = 0;
  let lineNumber = 0;
  let lineStart = 0;

  while (lineStart <= content.length) {
    const newlineIndex = content.indexOf("\n", lineStart);
    const lineEnd = newlineIndex === -1 ? content.length : newlineIndex;
    const rawLine = content.slice(lineStart, lineEnd).replace(/\r$/, "");
    lineNumber += 1;
    lineStart = newlineIndex === -1 ? content.length + 1 : newlineIndex + 1;

    if (!rawLine.trim()) {
      continue;
    }

    totalLineCount += 1;
    parsedLines.push(parseCompressionLine(rawLine, lineNumber));
  }

  return {
    parsedLines,
    totalLineCount,
  };
}

export function formatSource(record: CompressionRecord) {
  const sourceCount = record.sourceMessageCount || record.sourceMessageIds.length;
  const newCount = record.newlyCoveredMessageCount;
  const scopeLabel =
    record.status === "pending" || record.status === "running"
      ? "计划覆盖"
      : record.status === "failed"
        ? "尝试覆盖"
        : "摘要覆盖";
  const absorbedLabel =
    record.status === "pending" || record.status === "running"
      ? "计划吸收"
      : "本次吸收";
  return newCount > 0
    ? `${scopeLabel} ${sourceCount} 条，${absorbedLabel} ${newCount} 条`
    : `${scopeLabel} ${sourceCount || "-"} 条原文`;
}

export function formatProviderModel(providerId: string, modelId: string) {
  if (providerId && modelId) return `${providerId} / ${modelId}`;
  return providerId || modelId || "-";
}

export function formatTime(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function parseCompressionLine(line: string, lineNumber: number): ParsedCompressionLine {
  try {
    const raw = JSON.parse(line) as unknown;
    if (!isRecord(raw)) {
      return {
        kind: "error",
        lineNumber,
        message: "该行不是 JSON 对象。",
        rawLine: line,
      };
    }
    return {
      kind: "record",
      record: normalizeCompressionRecord(raw, line, lineNumber),
    };
  } catch (error) {
    return {
      kind: "error",
      lineNumber,
      message: error instanceof Error ? error.message : "JSON 解析失败。",
      rawLine: line,
    };
  }
}

function normalizeCompressionRecord(
  raw: JsonRecord,
  rawLine: string,
  lineNumber: number,
): CompressionRecord {
  const result = toRecord(raw.result);
  const failure = toRecord(raw.failure);
  const items = normalizeCompressionItems(result.items);
  const sourceTokenCount = numberValue(raw.source_token_count);
  const compressedTokenCount = numberValue(raw.compressed_token_count);
  const compressionRatio = finiteNumberValue(raw.compression_ratio)
    || compressionRatioPercent(sourceTokenCount, compressedTokenCount);
  return {
    lineNumber,
    rawLine,
    raw,
    status: stringValue(raw.status),
    handoff: stringValue(result.handoff),
    compressionId: stringValue(raw.compression_id),
    functionSessionId: stringValue(raw.function_session_id),
    sourceType: stringValue(raw.source_type),
    mode: stringValue(raw.mode),
    attemptIndex: numberValue(raw.attempt_index),
    retryOf: stringValue(raw.retry_of),
    sourceMessageCount: numberValue(raw.source_message_count),
    newlyCoveredMessageCount: stringArray(raw.newly_covered_message_ids).length,
    supersedesCompressionId: stringValue(raw.supersedes_compression_id),
    sourceTokenCount,
    compressedTokenCount,
    compressionRatio,
    providerId: stringValue(raw.provider_id),
    modelId: stringValue(raw.model_id),
    createdAt: stringValue(raw.created_at),
    completedAt: stringValue(raw.completed_at),
    sourceMessageIds: stringArray(raw.source_message_ids),
    items,
    failure: failureMessage(failure),
  };
}

function failureMessage(value: JsonRecord): CompressionFailure | null {
  const stage = stringValue(value.stage);
  const reason = stringValue(value.reason);
  const message = stringValue(value.message);
  if (!stage && !reason && !message) return null;
  return { stage, reason, message };
}

function normalizeCompressionItems(value: unknown): CompressionItem[] {
  return arrayValue(value).map((item) => {
    const record = toRecord(item);
    return {
      content: stringValue(record.content),
      keywords: stringArray(record.keywords),
    };
  }).filter((item) => item.content || item.keywords.length > 0);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toRecord(value: unknown): JsonRecord {
  return isRecord(value) ? value : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringArray(value: unknown): string[] {
  return arrayValue(value)
    .map((item) => stringValue(item))
    .filter(Boolean);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value) : 0;
}

function finiteNumberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function compressionRatioPercent(sourceTokens: number, compressedTokens: number): number {
  if (sourceTokens <= 0) return 0;
  return Math.round((compressedTokens / sourceTokens) * 1000) / 10;
}

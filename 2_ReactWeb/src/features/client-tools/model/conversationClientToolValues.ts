import type { ClientToolExecutionResult } from "./clientToolBridge";

export type JsonRecord = Record<string, unknown>;

export function parseClientToolArguments(rawArguments: string): JsonRecord {
  let value: unknown;
  try {
    value = rawArguments.trim() ? JSON.parse(rawArguments) : {};
  } catch {
    throw new Error("工具参数不是合法 JSON。");
  }
  if (!isJsonRecord(value)) {
    throw new Error("工具参数必须是 JSON 对象。");
  }
  return value;
}

export function isJsonRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function readRequiredString(record: JsonRecord, key: string): string {
  const value = readOptionalString(record[key]);
  if (!value) {
    throw new Error(`缺少 ${key} 参数。`);
  }
  return value;
}

export function readOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function readPositiveInteger(value: unknown, fallback: number): number {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || Number(value) < 1) {
    throw new Error("消息深度必须是大于等于 1 的整数。");
  }
  return Number(value);
}

export function clientToolSuccess(content: JsonRecord): ClientToolExecutionResult {
  return { ok: true, content };
}

export function clientToolFailure(
  error: unknown,
  content: JsonRecord = {},
): ClientToolExecutionResult {
  return {
    ok: false,
    content,
    error: error instanceof Error ? error.message : String(error),
  };
}

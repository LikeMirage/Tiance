import type { DsLlmReasoningMode } from "./generationParams";

export const LLM_REASONING_MODE_LABELS: Record<DsLlmReasoningMode, string> = {
  default: "默认",
  auto: "自动",
  enabled: "开启",
  off: "关闭",
  low: "低",
  medium: "中",
  high: "高",
  max: "最大",
};

const LLM_REASONING_MODES = new Set<DsLlmReasoningMode>([
  "default",
  "auto",
  "enabled",
  "off",
  "low",
  "medium",
  "high",
  "max",
]);

export function normalizeLlmReasoningMode(value: unknown): DsLlmReasoningMode | null {
  return typeof value === "string" && LLM_REASONING_MODES.has(value as DsLlmReasoningMode)
    ? value as DsLlmReasoningMode
    : null;
}

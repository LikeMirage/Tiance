type ProviderUsageLike = {
  completion_tokens?: number | null;
  cost_amount?: number | null;
  cost_currency?: string | null;
  prompt_cache_hit_tokens?: number | null;
  prompt_tokens?: number | null;
  total_tokens?: number | null;
};

export type ProviderUsageMetric = {
  key: ProviderUsageMetricKey;
  value: string;
};

export type ProviderUsageMetricKey =
  | "total"
  | "input"
  | "cacheHit"
  | "output"
  | "cost";

export type ProviderUsageFeatureKey =
  | "mainChat"
  | "conversationNaming"
  | "globalMemoryManagement"
  | "memoryCompression"
  | "projectMemoryManagement"
  | "providerWebSearch";

export function formatModelSetUsage(
  summary: ProviderUsageLike | null | undefined,
  labels: Record<ProviderUsageMetricKey, string>,
) {
  return getModelSetUsageMetrics(summary)
    .map((metric) => `${labels[metric.key]} ${metric.value}`)
    .join(" · ");
}

export function formatModelSetUsageTokenValue(
  summary: ProviderUsageLike | null | undefined,
) {
  return formatModelSetTokenCount(summary?.total_tokens);
}

export function getModelSetUsageMetrics(
  summary: ProviderUsageLike | null | undefined,
): ProviderUsageMetric[] {
  return [
    { key: "total", value: formatModelSetTokenCount(summary?.total_tokens) },
    { key: "input", value: formatModelSetTokenCount(summary?.prompt_tokens) },
    { key: "cacheHit", value: formatModelSetTokenCount(summary?.prompt_cache_hit_tokens) },
    { key: "output", value: formatModelSetTokenCount(summary?.completion_tokens) },
    { key: "cost", value: formatModelSetCost(summary) },
  ];
}

export function resolveProviderUsageFeatureKey(
  value: string | null | undefined,
): ProviderUsageFeatureKey {
  if (value === "conversation_naming") return "conversationNaming";
  if (value === "global_memory_management") return "globalMemoryManagement";
  if (value === "memory_compression") return "memoryCompression";
  if (value === "project_memory_management") return "projectMemoryManagement";
  if (value === "provider_web_search") return "providerWebSearch";
  return "mainChat";
}

function formatModelSetTokenCount(value: number | null | undefined) {
  const normalizedValue = Math.max(0, value ?? 0);
  if (normalizedValue > 999_000) {
    return `${trimUsageNumber(normalizedValue / 1_000_000)}M`;
  }
  if (normalizedValue > 999) {
    return `${trimUsageNumber(normalizedValue / 1_000)}k`;
  }
  return String(normalizedValue);
}

function trimUsageNumber(value: number) {
  return value >= 10
    ? value.toFixed(1).replace(/\.0$/, "")
    : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function formatModelSetCost(summary: ProviderUsageLike | null | undefined) {
  if (summary?.cost_amount === null || summary?.cost_amount === undefined) {
    return "--";
  }
  const prefix = summary.cost_currency === "CNY"
    ? "¥"
    : summary.cost_currency === "USD"
      ? "$"
      : `${summary.cost_currency ?? ""} `;
  return `${prefix}${formatModelSetCostValue(summary.cost_amount)}`;
}

function formatModelSetCostValue(value: number) {
  if (value === 0) {
    return "0";
  }
  const fixed = Math.abs(value) < 0.01 ? value.toFixed(6) : value.toFixed(4);
  return fixed.replace(/0+$/, "").replace(/\.$/, "");
}

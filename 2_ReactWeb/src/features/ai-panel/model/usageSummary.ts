import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ConversationUsageModelSummary,
  ConversationUsageSummary,
} from "../../../services/project/getProjectConversationUsageSummary";

export {
  formatCostAmount,
  formatTokenCount,
} from "../../../shared/model/usageFormatting";

export type UsageScopeOption = {
  label: string;
  providerLabel?: string;
  value: string;
};

export type UsageDisplaySummary = ChatUsage & {
  cost_amount?: number | null;
  cost_currency?: string | null;
  estimated_record_count?: number;
};

export function buildUsageScopeOptions(
  summary: ConversationUsageSummary | undefined,
): UsageScopeOption[] {
  return aggregateModelSummaries(summary).map((item) => ({
    label: item.model_id,
    providerLabel: item.provider_display_name || item.provider_id,
    value: buildUsageModelScopeKey(item.provider_id, item.model_id),
  }));
}

export function resolveUsageScopeSummary(
  summary: ConversationUsageSummary | undefined,
  scopeKey: string,
): UsageDisplaySummary | undefined {
  const modelSummaries = aggregateModelSummaries(summary);
  return modelSummaries.find((item) =>
    buildUsageModelScopeKey(item.provider_id, item.model_id) === scopeKey
  ) ?? modelSummaries[0] ?? summary;
}

function buildUsageModelScopeKey(
  providerId: string,
  modelId: string,
) {
  return `model:${providerId}:${modelId}`;
}

function aggregateModelSummaries(
  summary: ConversationUsageSummary | undefined,
): ConversationUsageModelSummary[] {
  const grouped = new Map<string, ConversationUsageModelSummary>();
  for (const item of summary?.by_models ?? []) {
    const key = buildUsageModelScopeKey(item.provider_id, item.model_id);
    const current = grouped.get(key);
    if (!current) {
      grouped.set(key, {
        ...item,
        usage_feature_key: null,
        usage_feature_display_name: null,
      });
      continue;
    }
    grouped.set(key, mergeModelSummaries(current, item));
  }
  return [...grouped.values()];
}

function mergeModelSummaries(
  current: ConversationUsageModelSummary,
  incoming: ConversationUsageModelSummary,
): ConversationUsageModelSummary {
  return {
    ...current,
    prompt_tokens: sumOptional(current.prompt_tokens, incoming.prompt_tokens),
    completion_tokens: sumOptional(current.completion_tokens, incoming.completion_tokens),
    total_tokens: sumOptional(current.total_tokens, incoming.total_tokens),
    prompt_cache_hit_tokens: sumOptional(
      current.prompt_cache_hit_tokens,
      incoming.prompt_cache_hit_tokens,
    ),
    prompt_cache_miss_tokens: sumOptional(
      current.prompt_cache_miss_tokens,
      incoming.prompt_cache_miss_tokens,
    ),
    reasoning_tokens: sumOptional(current.reasoning_tokens, incoming.reasoning_tokens),
    estimated_fields: [
      ...new Set([...(current.estimated_fields ?? []), ...(incoming.estimated_fields ?? [])]),
    ],
    cost_amount: sumOptional(current.cost_amount, incoming.cost_amount),
    record_count: current.record_count + incoming.record_count,
    estimated_record_count:
      current.estimated_record_count + incoming.estimated_record_count,
  };
}

function sumOptional(
  left: number | null | undefined,
  right: number | null | undefined,
): number | null {
  if (left == null && right == null) return null;
  return (left ?? 0) + (right ?? 0);
}

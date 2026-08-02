import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import type { ConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";

export {
  formatCostAmount,
  formatTokenCount,
} from "../../../shared/model/usageFormatting";

export const USAGE_TOTAL_SCOPE_KEY = "__total__";

export type UsageScopeOption = {
  label: string;
  featureLabel?: string;
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
  const modelSummaries = summary?.by_models ?? [];
  return [
    { label: "全部总计", value: USAGE_TOTAL_SCOPE_KEY },
    ...modelSummaries.map((item) => ({
      label: item.model_id,
      featureLabel: item.usage_feature_display_name || formatUsageFeatureLabel(item.usage_feature_key),
      providerLabel: item.provider_display_name || item.provider_id,
      value: buildUsageModelScopeKey(item.provider_id, item.model_id, item.usage_feature_key),
    })),
  ];
}

export function resolveUsageScopeSummary(
  summary: ConversationUsageSummary | undefined,
  scopeKey: string,
): UsageDisplaySummary | undefined {
  if (!summary || scopeKey === USAGE_TOTAL_SCOPE_KEY) {
    return summary;
  }
  return summary.by_models.find((item) =>
    buildUsageModelScopeKey(item.provider_id, item.model_id, item.usage_feature_key) === scopeKey
  ) ?? summary;
}

function buildUsageModelScopeKey(
  providerId: string,
  modelId: string,
  usageFeatureKey: string | null | undefined,
) {
  return `model:${providerId}:${modelId}:${usageFeatureKey || "main_chat"}`;
}

function formatUsageFeatureLabel(value: string | null | undefined) {
  if (value === "conversation_naming") return "会话命名模型";
  if (value === "global_memory_management") return "全局记忆管理模型";
  if (value === "memory_compression") return "记忆压缩模型";
  if (value === "project_memory_management") return "项目记忆管理模型";
  if (value === "provider_web_search") return "内置网络搜索";
  return "主会话";
}

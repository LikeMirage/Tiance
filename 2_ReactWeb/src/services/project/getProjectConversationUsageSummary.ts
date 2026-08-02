import type { ChatUsage } from "../../entities/llm-chat/model/chatCompletion";
import { fetchJson } from "../http/httpClient";

export type ConversationUsageSummary = ChatUsage & {
  provider_id?: string | null;
  provider_display_name?: string | null;
  model_id?: string | null;
  usage_feature_key?: string | null;
  usage_feature_display_name?: string | null;
  cost_amount?: number | null;
  cost_currency?: string | null;
  record_count: number;
  estimated_record_count: number;
  by_models: ConversationUsageModelSummary[];
};

export type ConversationUsageModelSummary = ChatUsage & {
  provider_id: string;
  provider_display_name?: string | null;
  model_id: string;
  usage_feature_key?: string | null;
  usage_feature_display_name?: string | null;
  cost_amount?: number | null;
  cost_currency?: string | null;
  record_count: number;
  estimated_record_count: number;
};

export function getProjectConversationUsageSummary(
  projectId: string,
  sessionId: string,
) {
  return fetchJson<ConversationUsageSummary>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/usage-summary`,
  );
}

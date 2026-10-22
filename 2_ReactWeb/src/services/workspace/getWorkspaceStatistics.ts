import { fetchJson } from "../http/httpClient";

export type WorkspaceStatisticsKind = "tokens" | "runtime" | "tools";
export type DailyStatistic = { date: string; value: number };
export type StatisticRanking = {
  id: string;
  value: number;
  label: string | null;
  detail: string | null;
  project_id?: string | null;
  session_id?: string | null;
  user_message_id?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
};
export type WorkspaceStatistics = {
  total: number;
  daily: DailyStatistic[];
  ranking: StatisticRanking[];
  conversation_count: number | null;
  sent_message_count: number | null;
  success_count: number | null;
  failure_count: number | null;
};

export function getWorkspaceStatistics(kind: WorkspaceStatisticsKind, month: string, signal: AbortSignal) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const query = new URLSearchParams({ month, timezone });
  return fetchJson<WorkspaceStatistics>(`/api/workspace/statistics/${kind}?${query}`, { cache: "no-store", signal });
}

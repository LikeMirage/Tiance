import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ProjectOverviewSession,
  ProjectOverviewUsage,
} from "../../../entities/project/model/project";

export type LiveUsageBySessionKey = Record<string, ProjectOverviewUsage>;

export type ProjectOverviewSessionWithDisplayUsage = ProjectOverviewSession & {
  displayUsage: ProjectOverviewUsage;
};

export function buildOverviewSessionKey(projectId: string, sessionId: string) {
  return `${projectId}:${sessionId}`;
}

export function getDisplaySessionUsage(
  projectId: string,
  session: ProjectOverviewSession,
  liveUsageBySessionKey: LiveUsageBySessionKey,
) {
  const liveUsage = liveUsageBySessionKey[buildOverviewSessionKey(projectId, session.session_id)];
  return liveUsage ? mergeProjectOverviewUsage(session.usage, liveUsage) : session.usage;
}

export function sumLiveUsageForProject(
  projectId: string,
  sessions: ProjectOverviewSession[],
  liveUsageBySessionKey: LiveUsageBySessionKey,
) {
  return sessions.reduce<ProjectOverviewUsage>((total, session) => {
    const liveUsage = liveUsageBySessionKey[buildOverviewSessionKey(projectId, session.session_id)];
    return liveUsage ? mergeProjectOverviewUsage(total, liveUsage) : total;
  }, createEmptyProjectOverviewUsage());
}

export function chatUsageToProjectOverviewUsage(usage: ChatUsage): ProjectOverviewUsage {
  return {
    prompt_tokens: safeUsageNumber(usage.prompt_tokens),
    completion_tokens: safeUsageNumber(usage.completion_tokens),
    total_tokens: safeUsageNumber(usage.total_tokens),
    reasoning_tokens: safeUsageNumber(usage.reasoning_tokens),
    prompt_cache_hit_tokens: safeUsageNumber(usage.prompt_cache_hit_tokens),
    prompt_cache_miss_tokens: safeUsageNumber(usage.prompt_cache_miss_tokens),
    cost_amount: null,
    cost_currency: null,
    record_count: 0,
  };
}

export function mergeProjectOverviewUsage(
  base: ProjectOverviewUsage,
  extra: ProjectOverviewUsage,
): ProjectOverviewUsage {
  return {
    prompt_tokens: base.prompt_tokens + extra.prompt_tokens,
    completion_tokens: base.completion_tokens + extra.completion_tokens,
    total_tokens: base.total_tokens + extra.total_tokens,
    reasoning_tokens: base.reasoning_tokens + extra.reasoning_tokens,
    prompt_cache_hit_tokens: base.prompt_cache_hit_tokens + extra.prompt_cache_hit_tokens,
    prompt_cache_miss_tokens: base.prompt_cache_miss_tokens + extra.prompt_cache_miss_tokens,
    cost_amount: mergeCostAmount(base, extra),
    cost_currency: base.cost_currency ?? extra.cost_currency,
    record_count: base.record_count + extra.record_count,
  };
}

function mergeCostAmount(base: ProjectOverviewUsage, extra: ProjectOverviewUsage) {
  if (base.cost_amount === null) return extra.cost_amount;
  if (extra.cost_amount === null) return base.cost_amount;
  if (base.cost_currency && extra.cost_currency && base.cost_currency !== extra.cost_currency) {
    return base.cost_amount;
  }
  return base.cost_amount + extra.cost_amount;
}

function createEmptyProjectOverviewUsage(): ProjectOverviewUsage {
  return {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    reasoning_tokens: 0,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 0,
    cost_amount: null,
    cost_currency: null,
    record_count: 0,
  };
}

function safeUsageNumber(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

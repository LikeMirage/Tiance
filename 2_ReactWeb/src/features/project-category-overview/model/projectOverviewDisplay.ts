import type { ProjectOverviewSession } from "../../../entities/project/model/project";

export function normalizeRuntimeStatus(status: string) {
  return status === "running" || status === "error" ? status : "idle";
}

export function resolveEnterSessionId(
  sessions: ProjectOverviewSession[],
  visibleSessionId: string | null,
  savedActiveSessionId: string | null,
) {
  if (visibleSessionId && sessions.some((session) => session.session_id === visibleSessionId)) {
    return visibleSessionId;
  }
  if (savedActiveSessionId && sessions.some((session) => session.session_id === savedActiveSessionId)) {
    return savedActiveSessionId;
  }
  return sessions[0]?.session_id ?? null;
}

export function formatProjectCreatedAt(
  createdAt: string,
  locale: string,
  fallback: string,
) {
  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) return fallback;
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(timestamp));
}

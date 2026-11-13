import type { ProjectOverviewItem } from "../../../entities/project/model/project";
import { conversationRuntime } from "../../../entities/llm-chat/model/conversationRuntime";

export function projectOverviewRuntime(item: ProjectOverviewItem): ProjectOverviewItem {
  const sessions = item.sessions.map((session) => ({
    ...session,
    runtime_status: conversationRuntime.status(item.project.project_id, session.session_id, session.runtime_status),
  }));
  return {
    ...item, sessions,
    active_count: sessions.filter((session) => session.runtime_status === "running").length,
    idle_count: sessions.filter((session) => session.runtime_status === "idle").length,
    error_count: sessions.filter((session) => session.runtime_status === "error").length,
  };
}

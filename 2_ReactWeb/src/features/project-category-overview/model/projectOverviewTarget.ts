import type { Project } from "../../../entities/project/model/project";

export type ProjectOverviewSessionTarget = {
  projectId: string;
  sessionId: string | null;
};

export function resolveProjectOverviewTarget(
  projects: readonly Project[],
  visibleSession: ProjectOverviewSessionTarget | null,
  rememberedProjectId: string | null,
): ProjectOverviewSessionTarget | null {
  const projectIds = new Set(projects.map((project) => project.project_id));
  if (visibleSession && projectIds.has(visibleSession.projectId)) {
    return visibleSession;
  }
  if (rememberedProjectId && projectIds.has(rememberedProjectId)) {
    return { projectId: rememberedProjectId, sessionId: null };
  }
  const firstProjectId = projects[0]?.project_id;
  return firstProjectId ? { projectId: firstProjectId, sessionId: null } : null;
}

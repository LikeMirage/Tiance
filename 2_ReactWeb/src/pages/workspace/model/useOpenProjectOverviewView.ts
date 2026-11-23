import { useCallback } from "react";
import type { ProjectOverviewView, WorkspaceLayoutPreferenceUpdate } from "../../../entities/workspace/model/workspaceLayoutPreferences";
import type { ProjectNavigationOptions } from "../../../entities/project/model/project";

export function useOpenProjectOverviewView(
  onActivateProject: ((id: string, options?: ProjectNavigationOptions) => boolean | void | Promise<boolean | void>) | undefined,
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void,
) {
  return useCallback(async (
    categoryId: string,
    targetProjectId: string,
    view: Exclude<ProjectOverviewView, "projects">,
    sessionId?: string | null,
  ) => {
    const didActivate = await onActivateProject?.(targetProjectId, { sessionId });
    if (didActivate === false) return;
    onLayoutPreferenceChange({
      projectOverviewMaximized: {
        categoryId,
        projectId: targetProjectId,
      },
      projectOverviewView: {
        categoryId,
        view,
      },
    });
  }, [onActivateProject, onLayoutPreferenceChange]);
}

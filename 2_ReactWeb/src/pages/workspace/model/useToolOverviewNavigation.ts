import { useCallback, useMemo } from "react";

import type { Project } from "../../../entities/project/model/project";
import type {
  ToolOverviewView,
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

type UseToolOverviewNavigationOptions = {
  layoutPreferences: WorkspaceLayoutPreferences;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onSelectProject: (projectId: string) => boolean | void;
  projects: Project[];
  selectedProjectId: string | null;
  selectedToolsetId: string | null;
};

export function useToolOverviewNavigation({
  layoutPreferences,
  onLayoutPreferenceChange,
  onSelectProject,
  projects,
  selectedProjectId,
  selectedToolsetId,
}: UseToolOverviewNavigationOptions) {
  const activeView: ToolOverviewView = selectedToolsetId
    ? layoutPreferences.toolOverviewViews[selectedToolsetId] ?? "tools"
    : "tools";
  const commonView = activeView === "tools" || activeView === "online"
    ? selectedToolsetId
      ? layoutPreferences.projectOverviewViews[selectedToolsetId] ?? "projects"
      : "projects"
    : activeView;
  const commonLayoutPreferences = useMemo(() => {
    if (!selectedToolsetId) return layoutPreferences;
    return {
      ...layoutPreferences,
      projectOverviewViews: {
        ...layoutPreferences.projectOverviewViews,
        [selectedToolsetId]: commonView,
      },
    };
  }, [commonView, layoutPreferences, selectedToolsetId]);

  const selectView = useCallback((
    view: ToolOverviewView,
    targetProjectId?: string | null,
  ) => {
    if (!selectedToolsetId) return false;
    if (view === "tools" || view === "online") {
      onLayoutPreferenceChange({
        toolOverviewView: {
          categoryId: selectedToolsetId,
          view,
        },
      });
      return true;
    }

    const categoryProjects = projects.filter(
      (project) => project.category_id === selectedToolsetId,
    );
    const rememberedProjectId =
      layoutPreferences.projectOverviewMaximizedProjectIds[selectedToolsetId] ?? null;
    const nextProjectId = targetProjectId
      ?? (
        selectedProjectId
        && categoryProjects.some((project) => project.project_id === selectedProjectId)
          ? selectedProjectId
          : null
      )
      ?? (
        rememberedProjectId
        && categoryProjects.some((project) => project.project_id === rememberedProjectId)
          ? rememberedProjectId
          : null
      )
      ?? categoryProjects[0]?.project_id
      ?? null;
    if (view !== "projects" && !nextProjectId) return false;
    if (nextProjectId) {
      onSelectProject(nextProjectId);
    }
    onLayoutPreferenceChange({
      projectOverviewMaximized: nextProjectId ? {
        categoryId: selectedToolsetId,
        projectId: nextProjectId,
      } : undefined,
      projectOverviewView: {
        categoryId: selectedToolsetId,
        view,
      },
      toolOverviewView: {
        categoryId: selectedToolsetId,
        view,
      },
    });
    return true;
  }, [
    layoutPreferences.projectOverviewMaximizedProjectIds,
    onLayoutPreferenceChange,
    onSelectProject,
    projects,
    selectedProjectId,
    selectedToolsetId,
  ]);

  const handleCommonLayoutPreferenceChange = useCallback((
    update: WorkspaceLayoutPreferenceUpdate,
  ) => {
    if (
      selectedToolsetId
      && update.projectOverviewView?.categoryId === selectedToolsetId
    ) {
      onLayoutPreferenceChange({
        ...update,
        toolOverviewView: {
          categoryId: selectedToolsetId,
          view: update.projectOverviewView.view,
        },
      });
      return;
    }
    onLayoutPreferenceChange(update);
  }, [onLayoutPreferenceChange, selectedToolsetId]);

  return {
    activeView,
    commonLayoutPreferences,
    handleCommonLayoutPreferenceChange,
    selectView,
  };
}

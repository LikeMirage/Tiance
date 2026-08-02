import { useCallback, useMemo } from "react";

import type { Project } from "../../../entities/project/model/project";
import type {
  CollectionOverviewView,
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

type UseCollectionOverviewNavigationOptions = {
  categoryId: string | null;
  layoutPreferences: WorkspaceLayoutPreferences;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onSelectProject: (projectId: string) => boolean | void | Promise<boolean | void>;
  projects: Project[];
  selectedProjectId: string | null;
};

export function useCollectionOverviewNavigation({
  categoryId,
  layoutPreferences,
  onLayoutPreferenceChange,
  onSelectProject,
  projects,
  selectedProjectId,
}: UseCollectionOverviewNavigationOptions) {
  const activeView: CollectionOverviewView = categoryId
    ? layoutPreferences.collectionOverviewViews[categoryId] ?? "specialized"
    : "specialized";
  const commonView = activeView === "specialized" || activeView === "online"
    ? "projects"
    : activeView;
  const commonLayoutPreferences = useMemo(() => {
    if (!categoryId) return layoutPreferences;
    return {
      ...layoutPreferences,
      projectOverviewViews: {
        ...layoutPreferences.projectOverviewViews,
        [categoryId]: commonView,
      },
    };
  }, [categoryId, commonView, layoutPreferences]);

  const selectView = useCallback((
    view: CollectionOverviewView,
    targetProjectId?: string | null,
  ) => {
    if (!categoryId) return false;
    if (view === "specialized" || view === "online") {
      onLayoutPreferenceChange({
        collectionOverviewView: { categoryId, view },
      });
      return true;
    }

    const categoryProjects = projects.filter(
      (project) => project.category_id === categoryId,
    );
    const rememberedProjectId =
      layoutPreferences.projectOverviewMaximizedProjectIds[categoryId] ?? null;
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
    if (view === "conversation" && !nextProjectId) return false;
    if (nextProjectId) {
      void onSelectProject(nextProjectId);
    }
    onLayoutPreferenceChange({
      projectOverviewMaximized: nextProjectId ? {
        categoryId,
        projectId: nextProjectId,
      } : undefined,
      projectOverviewView: { categoryId, view },
      collectionOverviewView: { categoryId, view },
    });
    return true;
  }, [
    categoryId,
    layoutPreferences.projectOverviewMaximizedProjectIds,
    onLayoutPreferenceChange,
    onSelectProject,
    projects,
    selectedProjectId,
  ]);

  const handleCommonLayoutPreferenceChange = useCallback((
    update: WorkspaceLayoutPreferenceUpdate,
  ) => {
    if (
      categoryId
      && update.projectOverviewView?.categoryId === categoryId
      && update.projectOverviewView.view !== "branches"
    ) {
      onLayoutPreferenceChange({
        ...update,
        collectionOverviewView: {
          categoryId,
          view: update.projectOverviewView.view,
        },
      });
      return;
    }
    onLayoutPreferenceChange(update);
  }, [categoryId, onLayoutPreferenceChange]);

  return {
    activeView,
    commonLayoutPreferences,
    handleCommonLayoutPreferenceChange,
    selectView,
  };
}

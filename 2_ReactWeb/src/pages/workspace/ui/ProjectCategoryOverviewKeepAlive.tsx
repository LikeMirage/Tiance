import { useCallback, useEffect, useMemo, useState } from "react";

import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import type {
  ProjectOverviewView,
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import {
  DEFAULT_PROJECT_OVERVIEW_LAYOUT,
  type ProjectOverviewLayoutMode,
} from "../../../features/project-category-overview/model/projectOverviewLayout";
import { resolveProjectOverviewTarget } from "../../../features/project-category-overview/model/projectOverviewTarget";
import { ProjectCategoryOverview } from "../../../features/project-category-overview/ui/ProjectCategoryOverview";
import { ProjectOverviewViewTabs } from "../../../features/project-category-overview/ui/ProjectOverviewViewTabs";
import { ProjectMarketBoard } from "../../../features/project-market/ui/ProjectMarketBoard";
import type { ProjectMarketScope } from "../../../features/project-market/model/projectMarket";
import type { ProjectEntryWarmupOptions } from "../../../features/project-entry/model/projectEntryWarmup";
import { ProjectBranchOverviewPanel } from "./ProjectBranchOverviewPanel";

type ProjectCategoryOverviewKeepAliveProps = {
  activeConversationMessageId?: string | null;
  categories: ProjectCategory[];
  isActive: boolean;
  layoutPreferences: WorkspaceLayoutPreferences;
  marketScope?: ProjectMarketScope | null;
  onCreateProject?: () => Promise<void>;
  onCreateSession: (projectId: string) => Promise<void>;
  onEnterSession: (projectId: string, sessionId: string) => Promise<boolean>;
  onImportProjectFolder?: (rootPath: string) => Promise<void>;
  onActivateProject?: (
    projectId: string,
    options?: ProjectEntryWarmupOptions,
  ) => boolean | void | Promise<boolean | void>;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onOpenConversationBranches: (projectId: string, sessionId: string | null) => Promise<void>;
  onPrepareProject?: (projectId: string) => void;
  onRevealProject: (projectId: string) => Promise<void>;
  onSelectConversationMessage?: (
    projectId: string,
    sessionId: string,
    messageId: string,
  ) => void;
  onSelectExportDirectory?: () => Promise<string | null>;
  onSelectCategory: (categoryId: string) => void;
  onSelectSession: (projectId: string, sessionId: string) => Promise<boolean>;
  projects: Project[];
  selectedCategoryId: string | null;
  showOverviewTabs?: boolean;
  visibleSession: { projectId: string; sessionId: string | null } | null;
  enableExternalOverviewViews?: boolean;
  enableExternalBranchView?: boolean;
};

export function ProjectCategoryOverviewKeepAlive({
  activeConversationMessageId = null,
  categories,
  isActive,
  layoutPreferences,
  marketScope = "project",
  onCreateProject,
  onCreateSession,
  onEnterSession,
  onImportProjectFolder,
  onActivateProject,
  onLayoutPreferenceChange,
  onOpenConversationBranches,
  onPrepareProject,
  onRevealProject,
  onSelectConversationMessage,
  onSelectExportDirectory,
  onSelectCategory,
  onSelectSession,
  projects,
  selectedCategoryId,
  showOverviewTabs = false,
  visibleSession,
  enableExternalOverviewViews,
  enableExternalBranchView,
}: ProjectCategoryOverviewKeepAliveProps) {
  const usesExternalOverviewViews =
    showOverviewTabs || enableExternalOverviewViews === true;
  const usesExternalBranchView =
    enableExternalBranchView ?? usesExternalOverviewViews;
  const [visitedCategoryIds, setVisitedCategoryIds] = useState<ReadonlySet<string>>(
    () => selectedCategoryId ? new Set([selectedCategoryId]) : new Set<string>(),
  );
  const handleLayoutModeChange = useCallback(
    (nextLayoutMode: ProjectOverviewLayoutMode) => {
      if (!selectedCategoryId) return;
      onLayoutPreferenceChange({
        projectOverviewLayout: {
          categoryId: selectedCategoryId,
          layoutMode: nextLayoutMode,
        },
      });
    },
    [onLayoutPreferenceChange, selectedCategoryId],
  );
  const selectedLayoutMode = selectedCategoryId
    ? layoutPreferences.projectOverviewLayoutModes[selectedCategoryId]
      ?? DEFAULT_PROJECT_OVERVIEW_LAYOUT
    : DEFAULT_PROJECT_OVERVIEW_LAYOUT;
  const handleMaximizedProjectChange = useCallback(
    (projectId: string | null) => {
      if (!selectedCategoryId) return;
      onLayoutPreferenceChange({
        projectOverviewMaximized: {
          categoryId: selectedCategoryId,
          projectId,
        },
      });
    },
    [onLayoutPreferenceChange, selectedCategoryId],
  );
  const selectedMaximizedProjectId = selectedCategoryId
    ? layoutPreferences.projectOverviewMaximizedProjectIds[selectedCategoryId] ?? null
    : null;
  const storedOverviewView = selectedCategoryId
    ? layoutPreferences.projectOverviewViews[selectedCategoryId] ?? "projects"
    : "projects";
  const selectedOverviewView = storedOverviewView === "online" && !marketScope
    ? "projects"
    : storedOverviewView;
  const openProjectView = useCallback(async (
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
  const openConversationBranches = useCallback(async (
    categoryId: string,
    targetProjectId: string,
    sessionId: string | null,
  ) => {
    if (!usesExternalBranchView) {
      await onOpenConversationBranches(targetProjectId, sessionId);
      return;
    }
    await openProjectView(categoryId, targetProjectId, "branches", sessionId);
  }, [onOpenConversationBranches, openProjectView, usesExternalBranchView]);
  const handleOverviewViewChange = useCallback((view: ProjectOverviewView) => {
    if (!selectedCategoryId) return;
    if (view === "online" && !marketScope) return;
    if (view === "projects" || view === "online") {
      onLayoutPreferenceChange({
        projectOverviewView: {
          categoryId: selectedCategoryId,
          view,
        },
      });
      return;
    }
    const selectedCategoryProjects = projects.filter(
      (project) => project.category_id === selectedCategoryId,
    );
    const target = resolveProjectOverviewTarget(
      selectedCategoryProjects,
      visibleSession,
      selectedMaximizedProjectId,
    );
    if (!target) return;
    void openProjectView(
      selectedCategoryId,
      target.projectId,
      view,
      target.sessionId,
    );
  }, [
    onLayoutPreferenceChange,
    marketScope,
    openProjectView,
    projects,
    selectedCategoryId,
    selectedMaximizedProjectId,
    visibleSession?.projectId,
    visibleSession?.sessionId,
  ]);

  useEffect(() => {
    if (!selectedCategoryId) return;
    setVisitedCategoryIds((current) => {
      if (current.has(selectedCategoryId)) return current;
      return new Set([...current, selectedCategoryId]);
    });
  }, [selectedCategoryId]);

  useEffect(() => {
    setVisitedCategoryIds((current) => {
      const existingCategoryIds = new Set(categories.map((category) => category.category_id));
      const next = [...current].filter((categoryId) => existingCategoryIds.has(categoryId));
      if (selectedCategoryId && !next.includes(selectedCategoryId)) {
        next.push(selectedCategoryId);
      }
      if (next.length === current.size && next.every((categoryId) => current.has(categoryId))) {
        return current;
      }
      return new Set(next);
    });
  }, [categories, selectedCategoryId]);

  const categoryIds = useMemo(() => {
    const existingCategoryIds = new Set(categories.map((category) => category.category_id));
    const ids = [...visitedCategoryIds].filter((categoryId) => existingCategoryIds.has(categoryId));
    if (selectedCategoryId && existingCategoryIds.has(selectedCategoryId) && !ids.includes(selectedCategoryId)) {
      ids.push(selectedCategoryId);
    }
    return ids;
  }, [categories, selectedCategoryId, visitedCategoryIds]);

  if (!selectedCategoryId || categoryIds.length === 0) {
    return (
      <ProjectCategoryOverview
        categories={categories}
        categoryId={selectedCategoryId}
        isActive={isActive}
        layoutMode={selectedLayoutMode}
        marketScope={marketScope}
        maximizedProjectId={
          !usesExternalOverviewViews || selectedOverviewView === "conversation"
            ? selectedMaximizedProjectId
            : null
        }
        onCreateProject={onCreateProject}
        onCreateSession={onCreateSession}
        onEnterSession={onEnterSession}
        onImportProjectFolder={onImportProjectFolder}
        onLayoutModeChange={handleLayoutModeChange}
        onMaximizedProjectChange={usesExternalOverviewViews
          ? (projectId) => {
              if (!selectedCategoryId) return;
              if (projectId) {
                void openProjectView(
                  selectedCategoryId,
                  projectId,
                  "conversation",
                );
              } else {
                onLayoutPreferenceChange({
                    projectOverviewView: {
                      categoryId: selectedCategoryId,
                      view: "projects",
                    },
                  });
              }
            }
          : handleMaximizedProjectChange}
        onOverviewViewChange={handleOverviewViewChange}
        onOpenConversationBranches={(targetProjectId, sessionId) =>
          openConversationBranches(
            selectedCategoryId ?? "",
            targetProjectId,
            sessionId,
          )}
        onPrepareProject={onPrepareProject}
        onRevealProject={onRevealProject}
        onSelectCategory={onSelectCategory}
        onSelectSession={onSelectSession}
        orderedProjects={[]}
        overviewView={selectedOverviewView}
        refreshKey={buildCategoryOverviewRefreshKey(null, [])}
        showOverviewTabs={showOverviewTabs}
        visibleSession={visibleSession}
      />
    );
  }

  return (
    <div className="project-category-overview-keepalive">
      {categoryIds.map((categoryId) => {
        const isCurrentCategory = categoryId === selectedCategoryId;
        const category = categories.find((item) => item.category_id === categoryId) ?? null;
        const categoryProjects = projects.filter((project) => project.category_id === categoryId);
        const categoryLayoutMode = layoutPreferences.projectOverviewLayoutModes[categoryId]
          ?? DEFAULT_PROJECT_OVERVIEW_LAYOUT;
        const categoryMaximizedProjectId =
          layoutPreferences.projectOverviewMaximizedProjectIds[categoryId] ?? null;
        const storedCategoryOverviewView =
          layoutPreferences.projectOverviewViews[categoryId] ?? "projects";
        const categoryOverviewView = storedCategoryOverviewView === "online" && !marketScope
          ? "projects"
          : storedCategoryOverviewView;
        const branchProject = categoryOverviewView === "branches"
          ? categoryProjects.find(
              (project) => project.project_id === categoryMaximizedProjectId,
            )
            ?? categoryProjects.find(
              (project) => project.project_id === visibleSession?.projectId,
            )
            ?? categoryProjects[0]
            ?? null
          : null;
        return (
          <div
            key={categoryId}
            className={
              isCurrentCategory
                ? "project-category-overview-keepalive__view project-category-overview-keepalive__view--active"
                : "project-category-overview-keepalive__view"
            }
            aria-hidden={isCurrentCategory ? undefined : "true"}
          >
            {categoryOverviewView === "online" && showOverviewTabs ? (
              <div className="project-category-overview-market-host">
                <ProjectOverviewViewTabs
                  activeView={categoryOverviewView}
                  disabled={categoryProjects.length === 0}
                  marketScope={marketScope}
                  onChange={handleOverviewViewChange}
                />
                <ProjectMarketBoard
                  categories={categories}
                  isActive={isActive && isCurrentCategory}
                  marketScope={marketScope ?? "project"}
                  selectedCategoryId={categoryId}
                />
              </div>
            ) : categoryOverviewView === "branches" && usesExternalBranchView ? (
              <ProjectBranchOverviewPanel
                activeMessageId={
                  visibleSession?.projectId === branchProject?.project_id
                    ? activeConversationMessageId
                    : null
                }
                activeSessionId={
                  visibleSession?.projectId === branchProject?.project_id
                    ? visibleSession?.sessionId ?? null
                    : null
                }
                isActive={isActive && isCurrentCategory}
                onOverviewViewChange={handleOverviewViewChange}
                onSelectExportDirectory={onSelectExportDirectory}
                onSelectMessage={(sessionId, messageId) => {
                  if (!branchProject) return;
                  onSelectConversationMessage?.(
                    branchProject.project_id,
                    sessionId,
                    messageId,
                  );
                }}
                projectId={branchProject?.project_id ?? null}
                projectRootPath={branchProject?.root_path ?? ""}
                marketScope={marketScope}
                showOverviewTabs={showOverviewTabs}
              />
            ) : (
            <ProjectCategoryOverview
              categories={categories}
              categoryId={categoryId}
              isActive={isActive && isCurrentCategory}
              layoutMode={categoryLayoutMode}
              marketScope={marketScope}
              maximizedProjectId={
                !usesExternalOverviewViews || categoryOverviewView === "conversation"
                  ? categoryMaximizedProjectId
                  : null
              }
              onCreateProject={onCreateProject}
              onCreateSession={onCreateSession}
              onEnterSession={onEnterSession}
              onImportProjectFolder={onImportProjectFolder}
              onLayoutModeChange={handleLayoutModeChange}
              onMaximizedProjectChange={(projectId) => {
                if (usesExternalOverviewViews) {
                  if (projectId) {
                    void openProjectView(
                      categoryId,
                      projectId,
                      "conversation",
                    );
                  } else {
                    onLayoutPreferenceChange({
                      projectOverviewView: {
                        categoryId,
                        view: "projects",
                      },
                    });
                  }
                  return;
                }
                onLayoutPreferenceChange({
                  projectOverviewMaximized: {
                    categoryId,
                    projectId,
                  },
                });
              }}
              onOverviewViewChange={handleOverviewViewChange}
              onOpenConversationBranches={(targetProjectId, sessionId) =>
                openConversationBranches(
                  categoryId,
                  targetProjectId,
                  sessionId,
                )}
              onPrepareProject={onPrepareProject}
              onRevealProject={onRevealProject}
              onSelectCategory={onSelectCategory}
              onSelectSession={onSelectSession}
              orderedProjects={categoryProjects}
              overviewView={categoryOverviewView}
              refreshKey={buildCategoryOverviewRefreshKey(category, categoryProjects)}
              showOverviewTabs={showOverviewTabs}
              visibleSession={visibleSession}
            />
            )}
          </div>
        );
      })}
    </div>
  );
}

function buildCategoryOverviewRefreshKey(
  category: ProjectCategory | null,
  projects: readonly Project[],
) {
  return [
    category ? `${category.category_id}:${category.name}:${category.updated_at}` : "",
    ...projects.map((project) =>
      `${project.project_id}:${project.category_id}:${project.name}:${project.updated_at}`,
    ),
  ].join("|");
}

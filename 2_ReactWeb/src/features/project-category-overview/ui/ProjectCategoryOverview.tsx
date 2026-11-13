import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { FolderPlus, Plus } from "@phosphor-icons/react";

import type {
  ProjectOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import type {
  Project,
  ProjectCategory,
  ProjectOverviewItem,
} from "../../../entities/project/model/project";
import { useDesktopShell } from "../../desktop-shell/model/useDesktopShell";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import { useI18n } from "../../../shared/i18n";
import { useProjectCategoryOverview } from "../model/useProjectCategoryOverview";
import { useProjectOverviewSessionActions } from "../model/useProjectOverviewSessionActions";
import { ProjectOverviewCard } from "./ProjectOverviewCard";
import { ProjectOverviewViewTabs } from "./ProjectOverviewViewTabs";
import type { ProjectMarketScope } from "../../project-market/model/projectMarket";
import { ProjectOverviewSessionContextMenu } from "./ProjectOverviewSessionContextMenu";
import { ProjectConversationDeleteModal } from "./ProjectConversationDeleteModal";

import "./project-category-overview.css";

type ProjectCategoryOverviewProps = {
  categories: ProjectCategory[];
  categoryId: string | null;
  isActive?: boolean;
  maximizedProjectId: string | null;
  marketScope?: ProjectMarketScope | null;
  onCreateProject?: () => Promise<void>;
  onCreateSession: (projectId: string) => Promise<void>;
  onEnterSession: (projectId: string, sessionId: string) => Promise<boolean>;
  onImportProjectFolder?: (rootPath: string) => Promise<void>;
  onMaximizedProjectChange: (projectId: string | null) => void;
  onMaximizedProjectFollow: (projectId: string) => void;
  onOverviewViewChange?: (view: ProjectOverviewView) => void;
  onOpenConversationBranches: (projectId: string, sessionId: string | null) => Promise<void>;
  onPrepareProject?: (projectId: string) => void;
  onRevealProject: (projectId: string) => Promise<void>;
  onSelectCategory: (categoryId: string) => void;
  onSelectSession: (projectId: string, sessionId: string) => Promise<boolean>;
  orderedProjects: Project[];
  overviewView?: ProjectOverviewView;
  refreshKey: string;
  showOverviewTabs?: boolean;
  visibleSession: { projectId: string; sessionId: string | null } | null;
};

type ProjectCategoryOption = OptionSelectItem<string>;

export const ProjectCategoryOverview = memo(function ProjectCategoryOverview({
  categories,
  categoryId,
  isActive = true,
  maximizedProjectId,
  marketScope = "project",
  onCreateProject,
  onCreateSession,
  onEnterSession,
  onImportProjectFolder,
  onMaximizedProjectChange,
  onMaximizedProjectFollow,
  onOverviewViewChange,
  onOpenConversationBranches,
  onPrepareProject,
  onRevealProject,
  onSelectCategory,
  onSelectSession,
  orderedProjects,
  overviewView = "projects",
  refreshKey,
  showOverviewTabs = false,
  visibleSession,
}: ProjectCategoryOverviewProps) {
  const { t } = useI18n();
  const [creatingProjectId, setCreatingProjectId] = useState<string | null>(null);
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [isImportingProject, setIsImportingProject] = useState(false);
  const [openUsageProjectId, setOpenUsageProjectId] = useState<string | null>(null);
  const desktopShell = useDesktopShell();
  const {
    error,
    liveUsageBySessionKey,
    loadOverview,
    overview,
    projects,
    state,
    updateActiveSession,
  } = useProjectCategoryOverview({
    categoryId,
    isActive,
    orderedProjects,
    refreshKey,
  });
  const {
    cancelDeleteSession,
    cancelRenameSession,
    confirmDeleteSession,
    confirmRenameSession,
    contextMenuSession,
    deletingSession,
    openSessionContextMenu,
    renamingSession,
    requestDeleteSession,
    requestRenameSession,
    sessionActionBusy,
    sessionActionError,
    setSessionActionError,
    sessionContextMenu,
    setSessionContextMenu,
    toggleSessionPinned,
  } = useProjectOverviewSessionActions({
    loadOverview,
    onSelectSession,
    projects,
    t,
    updateActiveSession,
    visibleSession,
  });
  const isOverviewLoadingVisible = state === "loading";
  const projectIdsKey = projects.map((item) => item.project.project_id).join("|");

  useEffect(() => {
    if (!isActive || !maximizedProjectId) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onMaximizedProjectChange(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isActive, maximizedProjectId, onMaximizedProjectChange]);

  useEffect(() => {
    const selectedProjectId = visibleSession?.projectId ?? null;
    if (
      !isActive
      || !maximizedProjectId
      || !selectedProjectId
      || selectedProjectId === maximizedProjectId
      || !projects.some((item) => item.project.project_id === selectedProjectId)
    ) {
      return;
    }
    setOpenUsageProjectId(null);
    // Following selection only updates the layout; it must not navigate again.
    onMaximizedProjectFollow(selectedProjectId);
  }, [
    isActive,
    maximizedProjectId,
    onMaximizedProjectFollow,
    projectIdsKey,
    projects,
    visibleSession?.projectId,
  ]);

  useEffect(() => {
    if (
      state === "ready"
      && maximizedProjectId
      && !projects.some((item) => item.project.project_id === maximizedProjectId)
    ) {
      onMaximizedProjectChange(null);
    }
  }, [
    maximizedProjectId,
    onMaximizedProjectChange,
    projectIdsKey,
    projects,
    state,
  ]);

  const categoryOptions = useMemo<ProjectCategoryOption[]>(
    () => categories.map((category) => ({
      label: category.name,
      value: category.category_id,
    })),
    [categories],
  );
  const selectedCategoryKind = categories.find(
    (category) => category.category_id === categoryId,
  )?.category_kind;
  const overviewKind = selectedCategoryKind ?? categories[0]?.category_kind ?? "project";

  const handleCreateSession = useCallback(async (projectId: string) => {
    if (creatingProjectId) return;
    setCreatingProjectId(projectId);
    try {
      await onCreateSession(projectId);
      await loadOverview("refresh");
    } finally {
      setCreatingProjectId((current) => current === projectId ? null : current);
    }
  }, [creatingProjectId, loadOverview, onCreateSession]);

  const handleSelectSession = useCallback(async (projectId: string, sessionId: string) => {
    if (await onSelectSession(projectId, sessionId)) {
      updateActiveSession(projectId, sessionId);
    }
  }, [onSelectSession, updateActiveSession]);

  const handleEnterSession = useCallback(async (projectId: string, sessionId: string) => {
    if (await onEnterSession(projectId, sessionId)) {
      updateActiveSession(projectId, sessionId);
    }
  }, [onEnterSession, updateActiveSession]);

  const handleCreateProject = useCallback(async () => {
    if (!onCreateProject || isCreatingProject) return;
    setIsCreatingProject(true);
    try {
      await onCreateProject();
      await loadOverview("refresh");
    } finally {
      setIsCreatingProject(false);
    }
  }, [isCreatingProject, loadOverview, onCreateProject]);

  const handleImportProjectFolder = useCallback(async () => {
    if (!onImportProjectFolder || isImportingProject) return;
    setIsImportingProject(true);
    try {
      const rootPath = await desktopShell.selectProjectFolder();
      if (!rootPath) return;
      await onImportProjectFolder(rootPath);
      await loadOverview("refresh");
    } finally {
      setIsImportingProject(false);
    }
  }, [desktopShell, isImportingProject, loadOverview, onImportProjectFolder]);

  const handleSelectCategory = useCallback((nextCategoryId: string) => {
    if (nextCategoryId === categoryId) return;
    onSelectCategory(nextCategoryId);
  }, [categoryId, onSelectCategory]);

  if (!categoryId) {
    return (
      <div className="project-category-overview__status">
        {t(
          overviewKind === "role"
            ? "projectOverview.noRoleCategory"
            : "projectOverview.noCategory",
        )}
      </div>
    );
  }

  if (isOverviewLoadingVisible) {
    return (
      <LoadingStrip
        ariaLabel={t("projectOverview.loadingAria")}
        className="project-category-overview__loading"
        mode="fill"
        visual="ring"
      />
    );
  }

  if (state === "error") {
    return (
      <div className="project-category-overview__status project-category-overview__status--error">
        <span>
          {error ?? t(
            overviewKind === "role"
              ? "projectOverview.roleLoadFailed"
              : "projectOverview.loadFailed",
          )}
        </span>
        <button type="button" onClick={() => void loadOverview()}>
          {t("common.actions.retry")}
        </button>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="project-category-overview__status">
        {t(
          overviewKind === "role"
            ? "projectOverview.emptyRoleCategory"
            : "projectOverview.emptyCategory",
        )}
      </div>
    );
  }

  const maximizedProject = maximizedProjectId
    ? projects.find((item) => item.project.project_id === maximizedProjectId) ?? null
    : null;

  const renderProjectCard = (project: ProjectOverviewItem) => (
    <ProjectOverviewCard
      key={project.project.project_id}
      creating={creatingProjectId === project.project.project_id}
      isMaximized={maximizedProjectId === project.project.project_id}
      item={project}
      onCreateSession={handleCreateSession}
      onEnterSession={handleEnterSession}
      onOpenSessionContextMenu={openSessionContextMenu}
      onOpenConversationBranches={onOpenConversationBranches}
      onPrepareProject={onPrepareProject}
      onRevealProject={onRevealProject}
      onSelectSession={handleSelectSession}
      onCancelSessionRename={cancelRenameSession}
      onCommitSessionRename={confirmRenameSession}
      onToggleUsage={() => {
        setOpenUsageProjectId((current) =>
          current === project.project.project_id ? null : project.project.project_id,
        );
      }}
      onToggleMaximized={() => {
        setOpenUsageProjectId(null);
        onMaximizedProjectChange(
          maximizedProjectId === project.project.project_id
            ? null
            : project.project.project_id,
        );
      }}
      onCloseUsage={() => {
        setOpenUsageProjectId((current) =>
          current === project.project.project_id ? null : current,
        );
      }}
      liveUsageBySessionKey={liveUsageBySessionKey}
      renameError={
        renamingSession?.projectId === project.project.project_id
          ? sessionActionError
          : null
      }
      renamingSessionId={
        renamingSession?.projectId === project.project.project_id
          ? renamingSession.sessionId
          : null
      }
      renamingSessionBusy={sessionActionBusy}
      usageOpen={openUsageProjectId === project.project.project_id}
      visibleSession={visibleSession}
    />
  );

  return (
    <section
      className={[
        "project-category-overview",
        showOverviewTabs
          ? "project-category-overview--with-view-tabs"
          : "",
        maximizedProject
          ? "project-category-overview--project-maximized"
          : "",
      ].filter(Boolean).join(" ")}
      aria-label={t(
        overviewKind === "role"
          ? "projectOverview.roleSectionAria"
          : "projectOverview.sectionAria", {
        category: overview.category_name,
        },
      )}
    >
      {showOverviewTabs ? (
        <ProjectOverviewViewTabs
          activeView={overviewView}
          disabled={projects.length === 0}
          marketScope={marketScope}
          onChange={(view) => onOverviewViewChange?.(view)}
        />
      ) : null}
      <header className="project-category-overview__header">
        <div className="project-category-overview__header-main">
          <OptionSelect
            ariaLabel={t(
              overviewKind === "role"
                ? "projectOverview.switchRoleCategory"
                : "projectOverview.switchCategory",
            )}
            className="project-category-overview__category-select"
            onChange={handleSelectCategory}
            options={categoryOptions}
            value={overview.category_id}
            variant="integrated-overlay"
          />
          <p className="project-category-overview__summary">
            {t(overviewKind === "role"
              ? "projectOverview.roleCount"
              : "projectOverview.projectCount", {
              count: overview.project_count,
            })}
          </p>
        </div>
        <div className="project-category-overview__header-side">
          <div className="project-category-overview__totals" aria-label={t("projectOverview.totalsAria")}>
            <span className="project-category-overview__total project-category-overview__total--running">
              {t("projectOverview.activeSessions", {
                count: overview.active_session_count,
              })}
            </span>
            <span className="project-category-overview__total project-category-overview__total--idle">
              {t("projectOverview.idleSessions", {
                count: overview.idle_session_count,
              })}
            </span>
            <span className="project-category-overview__total project-category-overview__total--error">
              {t("projectOverview.errorSessions", {
                count: overview.error_session_count,
              })}
            </span>
          </div>
          <div
            className="project-category-overview__actions"
            aria-label={t(
              overviewKind === "role"
                ? "projectOverview.roleActions"
                : "projectOverview.projectActions",
            )}
          >
            {onImportProjectFolder ? (
              <button
                className="project-category-overview__action"
                type="button"
                aria-label={t("workspace.projectsPanel.importFolder")}
                title={t("workspace.projectsPanel.importExternalFolder")}
                disabled={isImportingProject}
                onClick={() => void handleImportProjectFolder()}
              >
                <FolderPlus size={13} weight="bold" aria-hidden="true" />
              </button>
            ) : null}
            {onCreateProject ? (
              <button
                className="project-category-overview__action"
                type="button"
                aria-label={
                  selectedCategoryKind === "role"
                    ? t("workspace.projectsPanel.createRole")
                    : t("workspace.projectsPanel.createProject")
                }
                title={
                  selectedCategoryKind === "role"
                    ? t("workspace.projectsPanel.createRole")
                    : t("workspace.projectsPanel.createProject")
                }
                disabled={isCreatingProject}
                onClick={() => void handleCreateProject()}
              >
                <Plus size={13} weight="bold" aria-hidden="true" />
              </button>
            ) : null}
          </div>
        </div>
      </header>

      {sessionActionError && !renamingSession && !deletingSession ? (
        <p
          className="project-category-overview__session-action-error"
          role="alert"
        >
          {sessionActionError}
        </p>
      ) : null}

      {projects.length > 0 ? (
        <div
          className={[
            "project-category-overview__grid",
            maximizedProject
              ? "project-category-overview__grid--project-maximized"
              : "project-category-overview__grid--grid",
          ].join(" ")}
        >
          {maximizedProject
            ? renderProjectCard(maximizedProject)
            : projects.map(renderProjectCard)}
        </div>
      ) : (
        <div className="project-category-overview__empty-category">
          {t(
            overviewKind === "role"
              ? "projectOverview.emptyRoleCategory"
              : "projectOverview.emptyCategory",
          )}
        </div>
      )}
      {isActive && sessionContextMenu && contextMenuSession ? (
        <ProjectOverviewSessionContextMenu
          busy={sessionActionBusy}
          contextMenu={sessionContextMenu}
          onClose={() => setSessionContextMenu(null)}
          onError={setSessionActionError}
          onRequestDelete={requestDeleteSession}
          onRequestRename={requestRenameSession}
          onTogglePinned={(projectId, session) => {
            void toggleSessionPinned(projectId, session);
          }}
          session={contextMenuSession}
        />
      ) : null}
      {isActive && deletingSession ? (
        <ProjectConversationDeleteModal
          busy={sessionActionBusy}
          error={sessionActionError}
          onCancel={cancelDeleteSession}
          onConfirm={(sessionIds) => void confirmDeleteSession(sessionIds)}
          projectId={deletingSession.projectId}
          sessionId={deletingSession.sessionId}
          title={deletingSession.title}
        />
      ) : null}
    </section>
  );
});

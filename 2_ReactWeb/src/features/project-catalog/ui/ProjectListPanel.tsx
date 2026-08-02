import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowSquareIn, Check } from "@phosphor-icons/react";

import type { UseProjectCatalogResult } from "../model/useProjectCatalog";
import { runSequentialProjectBatchAction } from "../model/projectBatchActions";
import { useProjectListSelection } from "../model/useProjectListSelection";
import { useI18n } from "../../../shared/i18n";
import { useReorderListAnimation } from "../../../shared/model/reorder-list-animation/useReorderListAnimation";
import { ProjectDeleteConfirmModal } from "./ProjectDeleteConfirmModal";
import { ProjectListContextMenu } from "./ProjectListContextMenu";
import type { PendingProjectDelete, ProjectContextMenuState } from "./projectListPanelTypes";
import type { ProjectKind } from "../../../entities/project/model/project";

import "../../../shared/ui/catalog-list-entry/catalog-list-entry.css";
import "./project-list-panel.css";

// ------------------------------------------------------------------
// Props
// ------------------------------------------------------------------

export type ProjectListPanelProjectCatalog = Pick<
  UseProjectCatalogResult,
  | "categories"
  | "clearPendingRenameProject"
  | "deleteProject"
  | "error"
  | "getReorderedProjectIds"
  | "items"
  | "moveProjectToCategory"
  | "pendingRenameProjectId"
  | "pinProjectToCategoryTop"
  | "persistProjectOrder"
  | "previewProjectOrder"
  | "revealProject"
  | "reload"
  | "renameProject"
  | "selectedCategoryProjects"
  | "selectedCategoryId"
  | "selectedProjectId"
  | "state"
> & {
  expandProject: (projectId: string) => boolean | void | Promise<boolean | void>;
  selectProject: (projectId: string) => boolean | void | Promise<boolean | void>;
  prepareProject?: (projectId: string) => void;
};

export type ProjectListPanelProps = {
  itemKind?: ProjectKind;
  projectCatalog: ProjectListPanelProjectCatalog;
  searchKeyword: string;
};

// ------------------------------------------------------------------
// Component
// ------------------------------------------------------------------

export const ProjectListPanel = memo(function ProjectListPanel({
  itemKind = "project",
  projectCatalog,
  searchKeyword,
}: ProjectListPanelProps) {
  const { language, t } = useI18n();
  const normalizedKeyword = searchKeyword.trim().toLowerCase();
  const categoryProjects = projectCatalog.selectedCategoryProjects;
  const filteredProjects = useMemo(
    () =>
      normalizedKeyword.length === 0
        ? categoryProjects
        : categoryProjects.filter((p) =>
            p.name.toLowerCase().includes(normalizedKeyword),
          ),
    [categoryProjects, normalizedKeyword],
  );
  const {
    replaceSelection,
    resetSelection,
    retainSelection,
    selectedProjectIds,
    selectedProjectIdsRef,
    toggleSelection,
  } = useProjectListSelection();

  // ---- 拖拽排序 ----
  const projectItemNodesRef = useRef(new Map<string, HTMLElement>());
  const [draggingProjectId, setDraggingProjectId] = useState<string | null>(null);
  const [dragHoverTarget, setDragHoverTarget] = useState<{
    projectId: string; position: "before" | "after";
  } | null>(null);
  const dragStartProjectIdsRef = useRef<string[]>([]);
  const dragPreviewProjectIdsRef = useRef<string[]>([]);

  const orderedProjectIds = useRef<string[]>([]);
  orderedProjectIds.current = filteredProjects.map((p) => p.project_id);

  const listAnimation = useReorderListAnimation(orderedProjectIds.current, draggingProjectId);

  const getDropPosition = useCallback((projectId: string, clientY: number): "before" | "after" => {
    const node = projectItemNodesRef.current.get(projectId);
    if (!node) return "after";
    const rect = node.getBoundingClientRect();
    return clientY < rect.top + rect.height / 2 ? "before" : "after";
  }, []);

  const restoreDrag = useCallback(() => {
    projectCatalog.previewProjectOrder(dragStartProjectIdsRef.current);
    listAnimation.clearAnimationSnapshot();
  }, [projectCatalog, listAnimation]);

  const commitDrop = useCallback(async () => {
    try {
      await projectCatalog.persistProjectOrder(dragPreviewProjectIdsRef.current.slice());
    } finally {
      listAnimation.clearAnimationSnapshot();
    }
  }, [projectCatalog, listAnimation]);

  // ---- 右键菜单 ----
  const [contextMenu, setContextMenu] = useState<ProjectContextMenuState>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingProjectDelete>(null);
  const [isDeletingProject, setIsDeletingProject] = useState(false);
  const [isBatchActionBusy, setIsBatchActionBusy] = useState(false);
  const [projectActionError, setProjectActionError] = useState<string | null>(null);
  const [projectDeleteError, setProjectDeleteError] = useState<string | null>(null);
  const categoryProjectIdsKey = useMemo(
    () => categoryProjects.map((project) => project.project_id).join("\n"),
    [categoryProjects],
  );

  useEffect(() => {
    setContextMenu(null);
  }, [categoryProjectIdsKey, normalizedKeyword]);

  useEffect(() => {
    resetSelection();
    setProjectActionError(null);
    setProjectDeleteError(null);
  }, [normalizedKeyword, projectCatalog.selectedCategoryId, resetSelection]);

  useEffect(() => {
    retainSelection(new Set(categoryProjects.map((project) => project.project_id)));
  }, [categoryProjectIdsKey, categoryProjects, retainSelection]);

  const activeProjectId = projectCatalog.selectedProjectId;
  const activeProjectBelongsToCategory = Boolean(
    activeProjectId
    && categoryProjects.some((project) => project.project_id === activeProjectId),
  );
  useEffect(() => {
    if (!activeProjectId || !activeProjectBelongsToCategory) return;
    const currentSelection = selectedProjectIdsRef.current;
    if (currentSelection.size === 1 && currentSelection.has(activeProjectId)) return;
    replaceSelection([activeProjectId]);
  }, [
    activeProjectBelongsToCategory,
    activeProjectId,
    replaceSelection,
    selectedProjectIdsRef,
  ]);

  const moveProjectsToCategory = useCallback(async (
    projectIds: string[],
    categoryId: string,
  ) => {
    if (isBatchActionBusy || projectIds.length === 0) return;
    setIsBatchActionBusy(true);
    setProjectActionError(null);
    try {
      const result = await runSequentialProjectBatchAction(
        projectIds,
        (projectId) => projectCatalog.moveProjectToCategory(projectId, categoryId),
      );
      replaceSelection(result.remainingProjectIds);
      if (result.error) {
        setProjectActionError(
          result.error instanceof Error
            ? result.error.message
            : t("projectList.batchActionFailed"),
        );
      }
    } finally {
      setIsBatchActionBusy(false);
    }
  }, [isBatchActionBusy, projectCatalog, replaceSelection, t]);

  const confirmProjectDelete = useCallback(async (
    pending: NonNullable<PendingProjectDelete>,
  ) => {
    if (isDeletingProject) return;
    setIsDeletingProject(true);
    setProjectDeleteError(null);
    try {
      const result = await runSequentialProjectBatchAction(
        pending.projectIds,
        (projectId) => projectCatalog.deleteProject(projectId, {
            deleteFiles: pending.mode === "delete-local",
          }),
      );
      replaceSelection(result.remainingProjectIds);
      if (result.error) {
        setPendingDelete({
          ...pending,
          projectIds: result.remainingProjectIds,
          projectNames: pending.projectNames.slice(result.completedProjectIds.length),
        });
        setProjectDeleteError(
          result.error instanceof Error
            ? result.error.message
            : t("projectList.batchActionFailed"),
        );
        return;
      }
      setPendingDelete(null);
    } finally {
      setIsDeletingProject(false);
    }
  }, [isDeletingProject, projectCatalog, replaceSelection, t]);

  // ---- 重命名 ----
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const isCommittingRenameRef = useRef(false);

  useEffect(() => {
    if (renamingId) {
      setTimeout(() => { renameInputRef.current?.focus(); renameInputRef.current?.select(); }, 0);
    }
  }, [renamingId]);

  const pendingRenameProjectId = projectCatalog.pendingRenameProjectId;
  useEffect(() => {
    if (!pendingRenameProjectId) return;
    setRenamingId(pendingRenameProjectId);
    projectCatalog.clearPendingRenameProject();
  }, [pendingRenameProjectId]);

  const commitProjectRename = async (projectId: string, currentName: string, nextName: string) => {
    if (isCommittingRenameRef.current) return;
    const name = nextName.trim();
    if (!name || name === currentName) {
      setRenamingId(null);
      return;
    }
    isCommittingRenameRef.current = true;
    try {
      await projectCatalog.renameProject(projectId, name);
      setRenamingId(null);
    } catch {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    } finally {
      isCommittingRenameRef.current = false;
    }
  };

  // ---- 渲染 ----

  if (projectCatalog.state === "loading") {
    return (
      <div className="project-list-panel__status">
        {t(itemKind === "role" ? "projectList.roleLoading" : "projectList.loading")}
      </div>
    );
  }
  if (projectCatalog.state === "error") {
    return (
      <div className="project-list-panel__status project-list-panel__status--error">
        <span>
          {projectCatalog.error ?? t(
            itemKind === "role" ? "projectList.roleLoadFailed" : "projectList.loadFailed",
          )}
        </span>
        <button className="project-list-panel__status-action" type="button" onClick={projectCatalog.reload}>
          {t("common.actions.retry")}
        </button>
      </div>
    );
  }
  if (projectCatalog.items.length === 0) {
    return (
      <div className="project-list-panel__status">
        {t(itemKind === "role" ? "projectList.emptyAllRoles" : "projectList.emptyAll")}
      </div>
    );
  }
  if (categoryProjects.length === 0) {
    return (
      <div className="project-list-panel__status">
        {t(
          itemKind === "role"
            ? "projectList.emptyRoleCategory"
            : "projectList.emptyCategory",
        )}
      </div>
    );
  }
  if (filteredProjects.length === 0) {
    return (
      <div className="project-list-panel__status">
        {t(itemKind === "role" ? "projectList.emptyRoleSearch" : "projectList.emptySearch")}
      </div>
    );
  }

  return (
    <>
      {projectActionError ? (
        <div className="project-list-panel__action-error" role="alert">
          {projectActionError}
        </div>
      ) : null}
      <nav
        className="project-list-panel__list"
        aria-label={t(itemKind === "role" ? "projectList.roleAriaList" : "projectList.ariaList")}
        onDragOver={(e) => {
          if (!draggingProjectId) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}>
        {filteredProjects.map((proj) => {
          const isActive = proj.project_id === projectCatalog.selectedProjectId;
          const isSelected = selectedProjectIds.has(proj.project_id);
          const isDragging = draggingProjectId === proj.project_id;
          const showBefore = dragHoverTarget?.projectId === proj.project_id && dragHoverTarget.position === "before";
          const showAfter = dragHoverTarget?.projectId === proj.project_id && dragHoverTarget.position === "after";
          const isRenaming = renamingId === proj.project_id;

          return (
            <article key={proj.project_id}
              ref={(node) => {
                if (node) {
                  projectItemNodesRef.current.set(proj.project_id, node);
                  listAnimation.registerAnimatedItem(proj.project_id, node as HTMLDivElement);
                }
              }}
              className={[
                "catalog-list-entry",
                "project-list-panel__item",
                isDragging ? "project-list-panel__item--dragging" : "",
                isActive ? "project-list-panel__item--active" : "",
                isSelected ? "project-list-panel__item--selected" : "",
              ].filter(Boolean).join(" ")}
              draggable={selectedProjectIds.size <= 1}
              onDragStart={(e) => {
                if (selectedProjectIdsRef.current.size > 1) {
                  e.preventDefault();
                  return;
                }
                setDraggingProjectId(proj.project_id);
                dragStartProjectIdsRef.current = projectCatalog.items.map((x) => x.project_id);
                dragPreviewProjectIdsRef.current = dragStartProjectIdsRef.current.slice();
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", proj.project_id);
              }}
              onDragOver={(e) => {
                if (!draggingProjectId) return;
                e.preventDefault();
                if (isDragging) return;
                const pos = getDropPosition(proj.project_id, e.clientY);
                setDragHoverTarget({ projectId: proj.project_id, position: pos });
                const nextIds = projectCatalog.getReorderedProjectIds(draggingProjectId, proj.project_id, pos);
                const prevIds = dragPreviewProjectIdsRef.current;
                if (prevIds.length === 0 || nextIds.some((id, i) => id !== prevIds[i])) {
                  listAnimation.captureAnimationSnapshot();
                  dragPreviewProjectIdsRef.current = nextIds;
                  projectCatalog.previewProjectOrder(nextIds);
                }
              }}
              onDragLeave={() => {
                if (dragHoverTarget?.projectId === proj.project_id) setDragHoverTarget(null);
              }}
              onDragEnd={() => {
                const preview = dragPreviewProjectIdsRef.current;
                const start = dragStartProjectIdsRef.current;
                if (preview.length > 0 && preview.some((id, i) => id !== start[i])) {
                  void commitDrop();
                } else {
                  restoreDrag();
                }
                setDraggingProjectId(null);
                setDragHoverTarget(null);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                const currentSelection = selectedProjectIdsRef.current;
                const useCurrentSelection = currentSelection.has(proj.project_id) && currentSelection.size > 1;
                const actionProjectIds = useCurrentSelection
                  ? filteredProjects
                      .map((project) => project.project_id)
                      .filter((projectId) => currentSelection.has(projectId))
                  : [proj.project_id];
                if (!useCurrentSelection) replaceSelection(actionProjectIds);
                setContextMenu({
                  primaryProjectId: proj.project_id,
                  projectIds: actionProjectIds,
                  x: e.clientX,
                  y: e.clientY,
                });
              }}
              onPointerEnter={() => projectCatalog.prepareProject?.(proj.project_id)}>
              {showBefore && <div className="project-list-panel__drop-indicator" />}

              {isRenaming ? (
                <div className="catalog-list-entry__main project-list-panel__item-main">
                  <span className="catalog-list-entry__copy">
                    <span className="project-list-panel__rename-field">
                      <input ref={renameInputRef}
                        className="project-list-panel__rename-input"
                        defaultValue={proj.name}
                        onBlur={(e) => {
                          void commitProjectRename(proj.project_id, proj.name, e.target.value);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            void commitProjectRename(
                              proj.project_id,
                              proj.name,
                              e.currentTarget.value,
                            );
                          } else if (e.key === "Escape") {
                            setRenamingId(null);
                          }
                        }}
                      />
                      <button
                        className="project-list-panel__rename-save"
                        type="button"
                        aria-label={t(
                          itemKind === "role"
                            ? "projectList.saveRoleName"
                            : "projectList.saveProjectName",
                        )}
                        onMouseDown={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                        }}
                        onClick={(event) => {
                          event.stopPropagation();
                          void commitProjectRename(
                            proj.project_id,
                            proj.name,
                            renameInputRef.current?.value ?? proj.name,
                          );
                        }}
                      >
                        <Check className="project-list-panel__rename-save-glyph" weight="bold" />
                      </button>
                    </span>
                    <span className="catalog-list-entry__meta">
                      {formatProjectCreatedAt(proj.created_at, language, t("projectList.createdUnknown"))}
                    </span>
                  </span>
                </div>
              ) : (
                <button
                  className="catalog-list-entry__main project-list-panel__item-main"
                  type="button"
                  aria-pressed={isSelected}
                  onFocus={() => projectCatalog.prepareProject?.(proj.project_id)}
                  onClick={(event) => {
                    if (event.ctrlKey || event.metaKey) {
                      toggleSelection(proj.project_id);
                      return;
                    }
                    if (event.detail > 1) return;
                    replaceSelection([proj.project_id]);
                    void projectCatalog.selectProject(proj.project_id);
                  }}
                  onDoubleClick={() => {
                    replaceSelection([proj.project_id]);
                    void projectCatalog.expandProject(proj.project_id);
                  }}
                >
                  <span className="catalog-list-entry__copy">
                    <span className="catalog-list-entry__name">{proj.name}</span>
                    <span className="catalog-list-entry__meta">
                      {formatProjectCreatedAt(proj.created_at, language, t("projectList.createdUnknown"))}
                    </span>
                  </span>
                </button>
              )}
              {!isRenaming ? (
                <button
                  className="catalog-list-entry__enter project-list-panel__enter"
                  type="button"
                  aria-label={t(
                    itemKind === "role"
                      ? "projectList.enterRole"
                      : "projectList.enterProject",
                    { project: proj.name },
                  )}
                  title={t(
                    itemKind === "role"
                      ? "projectList.enterRole"
                      : "projectList.enterProject",
                    { project: proj.name },
                  )}
                  onClick={(event) => {
                    event.stopPropagation();
                    replaceSelection([proj.project_id]);
                    void projectCatalog.expandProject(proj.project_id);
                  }}
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  <ArrowSquareIn size={15} weight="regular" aria-hidden="true" />
                </button>
              ) : null}

              {showAfter && <div className="project-list-panel__drop-indicator" />}
            </article>
          );
        })}
      </nav>

      {/* 右键菜单 */}
      {contextMenu && (
        <ProjectListContextMenu
          categories={projectCatalog.categories}
          contextMenu={contextMenu}
          onClose={() => setContextMenu(null)}
          onMoveProjectsToCategory={(projectIds, categoryId) => {
            void moveProjectsToCategory(projectIds, categoryId);
          }}
          onPinProjectToTop={(projectId) => {
            void projectCatalog.pinProjectToCategoryTop(projectId).catch(() => undefined);
          }}
          onRevealProject={(projectId) => {
            void projectCatalog.revealProject(projectId).catch(() => undefined);
          }}
          onRequestDelete={(nextPendingDelete) => {
            setProjectDeleteError(null);
            setPendingDelete(nextPendingDelete);
          }}
          onStartRename={setRenamingId}
          projects={projectCatalog.items}
        />
      )}

      {/* 删除确认 */}
      {pendingDelete && (
        <ProjectDeleteConfirmModal
          error={projectDeleteError}
          itemKind={itemKind}
          isDeleting={isDeletingProject}
          onCancel={() => {
            setPendingDelete(null);
            setProjectDeleteError(null);
          }}
          onConfirm={(pending) => void confirmProjectDelete(pending)}
          pendingDelete={pendingDelete}
        />
      )}
    </>
  );
});

function formatProjectCreatedAt(createdAt: string, language: string, fallback: string) {
  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) return fallback;
  return new Intl.DateTimeFormat(language, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

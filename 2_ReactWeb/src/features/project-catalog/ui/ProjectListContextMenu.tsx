import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSubmenu,
} from "../../../shared/ui/context-menu";
import { useI18n } from "../../../shared/i18n";
import type { PendingProjectDelete, ProjectContextMenuState } from "./projectListPanelTypes";

type ProjectListContextMenuProps = {
  categories: ProjectCategory[];
  contextMenu: NonNullable<ProjectContextMenuState>;
  onClose: () => void;
  onMoveProjectsToCategory: (projectIds: string[], categoryId: string) => void;
  onPinProjectToTop: (projectId: string) => void;
  onRevealProject: (projectId: string) => void;
  onRequestDelete: (pendingDelete: NonNullable<PendingProjectDelete>) => void;
  onStartRename: (projectId: string) => void;
  projects: Project[];
};

export function ProjectListContextMenu({
  categories,
  contextMenu,
  onClose,
  onMoveProjectsToCategory,
  onPinProjectToTop,
  onRevealProject,
  onRequestDelete,
  onStartRename,
  projects,
}: ProjectListContextMenuProps) {
  const { t } = useI18n();
  const contextProject = projects.find(
    (project) => project.project_id === contextMenu.primaryProjectId,
  );
  if (!contextProject) return null;
  const selectedProjects = contextMenu.projectIds
    .map((projectId) => projects.find((project) => project.project_id === projectId))
    .filter((project): project is Project => Boolean(project));
  if (selectedProjects.length === 0) return null;

  const targetCategories = categories.filter(
    (category) => category.category_id !== contextProject.category_id,
  );
  const isBatch = selectedProjects.length > 1;
  const allImported = selectedProjects.every((project) => !project.is_managed);
  const allManaged = selectedProjects.every((project) => project.is_managed);
  const requestDelete = (pendingDelete: NonNullable<PendingProjectDelete>) => {
    onRequestDelete(pendingDelete);
    onClose();
  };
  const isCategoryFirstProject =
    projects.find((project) => project.category_id === contextProject.category_id)
      ?.project_id === contextProject.project_id;

  return (
    <ContextMenu onClose={onClose} position={{ x: contextMenu.x, y: contextMenu.y }}>
      {!isBatch ? (
        <>
          <ContextMenuItem
            disabled={isCategoryFirstProject}
            onSelect={() => {
              onPinProjectToTop(contextMenu.primaryProjectId);
              onClose();
            }}
          >
            {t("projectList.context.pinTop")}
          </ContextMenuItem>
          <ContextMenuItem
            onSelect={() => {
              onStartRename(contextMenu.primaryProjectId);
              onClose();
            }}
          >
            {t("common.actions.rename")}
          </ContextMenuItem>
          <ContextMenuItem
            onSelect={() => {
              onRevealProject(contextMenu.primaryProjectId);
              onClose();
            }}
          >
            {t("projectList.context.reveal")}
          </ContextMenuItem>
        </>
      ) : null}
      {targetCategories.length > 0 ? (
        <>
          <ContextMenuSeparator />
          <ContextMenuSubmenu label={t("projectList.context.moveTo")}>
            {targetCategories.map((category) => (
              <ContextMenuItem
                key={category.category_id}
                onSelect={() => {
                  onMoveProjectsToCategory(contextMenu.projectIds, category.category_id);
                  onClose();
                }}
              >
                {category.name}
              </ContextMenuItem>
            ))}
          </ContextMenuSubmenu>
        </>
      ) : null}
      <ContextMenuSeparator />
      {allImported ? (
        <>
          <ContextMenuItem
            activation="click"
            onSelect={() => {
              requestDelete({
                mode: "remove",
                projectIds: contextMenu.projectIds,
                projectNames: selectedProjects.map((project) => project.name),
              });
            }}
          >
            {t("projectList.context.removeProject")}
          </ContextMenuItem>
          <ContextMenuItem
            activation="click"
            danger
            onSelect={() => {
              requestDelete({
                mode: "delete-local",
                projectIds: contextMenu.projectIds,
                projectNames: selectedProjects.map((project) => project.name),
              });
            }}
          >
            {t("projectList.context.deleteLocalFiles")}
          </ContextMenuItem>
        </>
      ) : allManaged ? (
        <ContextMenuItem
          activation="click"
          danger
          onSelect={() => {
            requestDelete({
              mode: "delete",
              projectIds: contextMenu.projectIds,
              projectNames: selectedProjects.map((project) => project.name),
            });
          }}
        >
          {t("common.actions.delete")}
        </ContextMenuItem>
      ) : (
        <ContextMenuItem
          activation="click"
          danger
          onSelect={() => {
            requestDelete({
              mode: "mixed",
              projectIds: contextMenu.projectIds,
              projectNames: selectedProjects.map((project) => project.name),
            });
          }}
        >
          {t("common.actions.delete")}
        </ContextMenuItem>
      )}
    </ContextMenu>
  );
}

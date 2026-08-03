import {
  ArrowClockwise,
  CaretLeft,
  FilePlus,
  FolderPlus,
  Plus,
} from "@phosphor-icons/react";
import { useMemo, type ReactNode } from "react";

import {
  PROJECT_FILE_DRAG_MIME_TYPE,
  serializeProjectFileDragData,
  type ProjectFileDragData,
} from "../../../entities/project/model/projectFileDragData";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import { useDesktopFileDropTarget } from "../../../features/desktop-shell/model/useDesktopFileDropTarget";
import type { FileWorkspaceBrowserNode } from "../../../features/file-workspace/model/fileWorkspaceBrowserTreeModel";
import { ExternalFileWorkspaceTree } from "../../../features/file-workspace/ui";
import type { UseProjectCatalogResult } from "../../../features/project-catalog/model/useProjectCatalog";
import { useProjectFolderDropImport } from "../../../features/project-catalog/model/useProjectFolderDropImport";
import {
  ProjectListPanel,
  type ProjectListPanelProjectCatalog,
} from "../../../features/project-catalog/ui/ProjectListPanel";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { SlidingViewStage } from "../../../shared/ui/sliding-view-stage/SlidingViewStage";
import {
  useWorkspaceProjectsPanelController,
  type WorkspaceProjectsPanelControllerProjectCatalog,
  type WorkspaceProjectPanelView,
} from "../model/useWorkspaceProjectsPanelController";
import "./workspace-projects-panel.css";

export type WorkspaceProjectsPanelProjectCatalog =
  ProjectListPanelProjectCatalog &
  WorkspaceProjectsPanelControllerProjectCatalog &
  Pick<
    UseProjectCatalogResult,
    | "collapseProject"
    | "createProjectsFromFolders"
    | "dismissImportConflict"
    | "duplicateImportConflict"
    | "expandedProject"
    | "isCreatingProject"
    | "jumpToImportConflictProject"
    | "selectedCategory"
  >;

type WorkspaceProjectsPanelProps = {
  allowCreateProject?: boolean;
  allowExternalImport?: boolean;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
};

type WorkspaceProjectsPanelController = ReturnType<
  typeof useWorkspaceProjectsPanelController
>;

export function WorkspaceProjectsPanel({
  allowCreateProject = true,
  allowExternalImport = true,
  documentTabs,
  onReferenceProjectFile,
  projectCatalog,
}: WorkspaceProjectsPanelProps) {
  const { t } = useI18n();
  const controller = useWorkspaceProjectsPanelController({
    documentTabs,
    projectCatalog,
  });

  const listContent = (
    <WorkspaceProjectList
      allowExternalImport={allowExternalImport}
      projectCatalog={projectCatalog}
      searchKeyword={controller.searchKeyword}
    />
  );
  const detailContent = (
    <WorkspaceProjectDetail
      controller={controller}
      documentTabs={documentTabs}
      onReferenceProjectFile={onReferenceProjectFile}
      projectCatalog={projectCatalog}
    />
  );
  const renderViewContent = (view: WorkspaceProjectPanelView) =>
    view === "detail" ? detailContent : listContent;
  const currentViewContent = renderViewContent(controller.activeView);

  return (
    <aside
      className="workspace-projects-panel"
      aria-label={projectCatalog.selectedCategory?.name ?? t("workspace.projectsPanel.fallbackTitle")}
    >
        <WorkspaceProjectsHeader
        allowCreateProject={allowCreateProject}
        allowExternalImport={allowExternalImport}
        controller={controller}
        projectCatalog={projectCatalog}
      />
      <WorkspaceProjectsSearch
        controller={controller}
        projectCatalog={projectCatalog}
      />
      <WorkspaceProjectsBody
        controller={controller}
        currentViewContent={currentViewContent}
      />

      {projectCatalog.error && projectCatalog.state === "ready" ? (
        <div className="workspace-projects-panel__footer-error" role="status">
          {projectCatalog.error}
        </div>
      ) : null}
      {controller.workspaceStateError ? (
        <div className="workspace-projects-panel__footer-error" role="status">
          {controller.workspaceStateError}
        </div>
      ) : null}

      {projectCatalog.duplicateImportConflict ? (
        <ConfirmModal
          title={t("workspace.projectsPanel.duplicateTitle")}
          message={t("workspace.projectsPanel.duplicateMessage", {
            categoryName: projectCatalog.duplicateImportConflict.categoryName,
            projectName: projectCatalog.duplicateImportConflict.projectName,
          })}
          confirmLabel={t("workspace.projectsPanel.jump")}
          onCancel={projectCatalog.dismissImportConflict}
          onConfirm={projectCatalog.jumpToImportConflictProject}
        />
      ) : null}
    </aside>
  );
}

function WorkspaceProjectsHeader({
  allowCreateProject,
  allowExternalImport,
  controller,
  projectCatalog,
}: {
  allowCreateProject: boolean;
  allowExternalImport: boolean;
  controller: WorkspaceProjectsPanelController;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
}) {
  const { t } = useI18n();
  return (
    <header className="workspace-projects-panel__header">
      <div className="workspace-projects-panel__titleblock">
        <h2 className="workspace-projects-panel__title">
          {controller.activeView === "detail" && projectCatalog.expandedProject
            ? projectCatalog.expandedProject.name
            : projectCatalog.selectedCategory?.name ?? t("workspace.projectsPanel.fallbackTitle")}
        </h2>
      </div>
      <div className="workspace-projects-panel__tools">
        {controller.activeView === "detail" ? (
          <WorkspaceProjectDetailTools
            controller={controller}
            projectCatalog={projectCatalog}
          />
        ) : (
          <WorkspaceProjectListTools
            allowCreateProject={allowCreateProject}
            allowExternalImport={allowExternalImport}
            controller={controller}
            projectCatalog={projectCatalog}
          />
        )}
      </div>
    </header>
  );
}

function WorkspaceProjectDetailTools({
  controller,
  projectCatalog,
}: {
  controller: WorkspaceProjectsPanelController;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
}) {
  const { t } = useI18n();
  return (
    <>
      <button
        className="workspace-projects-panel__tool"
        type="button"
        aria-label={t("workspace.projectsPanel.createFile")}
        title={t("workspace.projectsPanel.createFile")}
        onPointerDown={(event) =>
          controller.handleCreatePointerDown(event, "file")
        }
        onClick={() => controller.handleCreateClick("file")}
      >
        <span className="workspace-projects-panel__icon-wrap">
          <FilePlus size={14} weight="bold" />
        </span>
      </button>
      <button
        className="workspace-projects-panel__tool"
        type="button"
        aria-label={t("workspace.projectsPanel.createFolder")}
        title={t("workspace.projectsPanel.createFolder")}
        onPointerDown={(event) =>
          controller.handleCreatePointerDown(event, "folder")
        }
        onClick={() => controller.handleCreateClick("folder")}
      >
        <span className="workspace-projects-panel__icon-wrap">
          <FolderPlus size={14} weight="bold" />
        </span>
      </button>
      <button
        className="workspace-projects-panel__tool"
        type="button"
        aria-label={t("workspace.projectsPanel.refreshFiles")}
        title={t("common.actions.refresh")}
        onClick={controller.handleRefreshTreeClick}
      >
        <span className="workspace-projects-panel__icon-wrap">
          <ArrowClockwise size={14} weight="bold" />
        </span>
      </button>
      <button
        className="workspace-projects-panel__tool"
        type="button"
        aria-label={t("workspace.projectsPanel.backToProjectList")}
        title={t("workspace.projectsPanel.collapse")}
        onClick={projectCatalog.collapseProject}
      >
        <span className="workspace-projects-panel__icon-wrap">
          <CaretLeft size={14} weight="bold" />
        </span>
      </button>
    </>
  );
}

function WorkspaceProjectListTools({
  allowCreateProject,
  allowExternalImport,
  controller,
  projectCatalog,
}: {
  allowCreateProject: boolean;
  allowExternalImport: boolean;
  controller: WorkspaceProjectsPanelController;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
}) {
  const { t } = useI18n();
  const createEntryLabel = projectCatalog.selectedCategory?.category_kind === "role"
    ? t("workspace.projectsPanel.createRole")
    : t("workspace.projectsPanel.createProject");
  return (
    <>
      {allowExternalImport ? (
        <button
          className="workspace-projects-panel__tool workspace-projects-panel__tool--dashboard-action"
          type="button"
          aria-label={t("workspace.projectsPanel.importFolder")}
          title={t("workspace.projectsPanel.importExternalFolder")}
          disabled={controller.isImporting}
          onClick={() => void controller.handleImportFolder()}
        >
          <FolderPlus size={13} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
      {allowCreateProject ? (
        <button
          className="workspace-projects-panel__tool workspace-projects-panel__tool--dashboard-action"
          type="button"
          aria-label={createEntryLabel}
          title={createEntryLabel}
          disabled={projectCatalog.isCreatingProject}
          onClick={controller.handleCreateProject}
        >
          <Plus size={13} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
    </>
  );
}

function WorkspaceProjectsSearch({
  controller,
  projectCatalog,
}: {
  controller: WorkspaceProjectsPanelController;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
}) {
  const { t } = useI18n();
  const searchPlaceholder =
    controller.activeView === "detail"
      ? t("workspace.projectsPanel.searchFiles")
      : projectCatalog.selectedCategory?.category_kind === "role"
        ? t("workspace.projectsPanel.searchRoles")
        : projectCatalog.selectedCategory?.category_kind === "theme"
          ? t("workspace.projectsPanel.searchThemes")
        : t("workspace.projectsPanel.searchProjects");

  return (
    <label className="workspace-projects-panel__search">
      <span className="workspace-projects-panel__search-label">
        {searchPlaceholder}
      </span>
      <input
        className="workspace-projects-panel__search-input"
        type="search"
        value={controller.searchInputValue}
        placeholder={searchPlaceholder}
        onChange={(event) => controller.handleSearchChange(event.target.value)}
      />
    </label>
  );
}

function WorkspaceProjectsBody({
  controller,
  currentViewContent,
}: {
  controller: WorkspaceProjectsPanelController;
  currentViewContent: ReactNode;
}) {
  return (
    <div className="workspace-projects-panel__body-shell">
      <div
        ref={controller.projectScrollbar.scrollRef}
        className={
          controller.activeView === "detail"
            ? "workspace-projects-panel__body workspace-projects-panel__body--detail"
            : "workspace-projects-panel__body"
        }
        onScroll={controller.projectScrollbar.handleScroll}
      >
        <SlidingViewStage
          className="workspace-projects-panel__view-stage"
          direction={controller.activeView === "detail" ? "forward" : "back"}
          keepLeavingView={false}
          viewKey={controller.activeView}
        >
          {currentViewContent}
        </SlidingViewStage>
      </div>

      <WorkspaceProjectsScrollbar controller={controller} />
    </div>
  );
}

function WorkspaceProjectsScrollbar({
  controller,
}: {
  controller: WorkspaceProjectsPanelController;
}) {
  const scrollbar = controller.projectScrollbar;

  if (!scrollbar.isVisible) {
    return null;
  }

  return (
    <div
      className={
        scrollbar.isActive
          ? "workspace-projects-panel__scrollbar workspace-projects-panel__scrollbar--active"
          : "workspace-projects-panel__scrollbar"
      }
      aria-hidden="true"
      onPointerDown={scrollbar.handleTrackPointerDown}
    >
      <div
        className="workspace-projects-panel__scrollbar-thumb"
        style={{
          height: `${scrollbar.thumbHeight}px`,
          transform: `translateY(${scrollbar.thumbTop}px)`,
        }}
        onPointerCancel={scrollbar.handleThumbPointerCancel}
        onPointerDown={scrollbar.handleThumbPointerDown}
        onPointerMove={scrollbar.handleThumbPointerMove}
        onPointerUp={scrollbar.handleThumbPointerUp}
      />
    </div>
  );
}

function WorkspaceProjectDetail({
  controller,
  documentTabs,
  onReferenceProjectFile,
  projectCatalog,
}: {
  controller: WorkspaceProjectsPanelController;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
}) {
  const { t } = useI18n();
  const projectFileDragData = useMemo(() => {
    const projectId = projectCatalog.expandedProjectId;
    if (!projectId) return undefined;
    return {
      mimeType: PROJECT_FILE_DRAG_MIME_TYPE,
      getData: (node: FileWorkspaceBrowserNode) => serializeProjectFileDragData({
        projectId,
        path: node.path,
        name: node.name,
        kind: node.kind,
      }),
    };
  }, [projectCatalog.expandedProjectId]);

  return (
    <div
      className="workspace-projects-panel__detail"
    >
      <ExternalFileWorkspaceTree
        browser={controller.browser}
        emptyMessage={t("workspace.projectsPanel.emptyProjectFiles")}
        nodeDragData={projectFileDragData}
        rootAriaLabel={t("workspace.projectsPanel.rootDirectory")}
        treeAriaLabel={t("workspace.projectsPanel.projectFiles")}
        onCreateFile={(parentId) => void controller.browser.createFile(parentId)}
        onCreateFolder={(parentId) => void controller.browser.createFolder(parentId)}
        onDeleteNode={(nodeId) => controller.browser.deleteNode(nodeId)}
        onNodeRenamed={(previousNode, renamedNode) => {
          if (!projectCatalog.expandedProjectId) {
            return;
          }

          documentTabs.renameProjectPath(
            projectCatalog.expandedProjectId,
            previousNode.path,
            renamedNode.path,
          );
        }}
        onOpenFile={(node) => {
          void documentTabs.openNode(
            node,
            {
              projectFilePath: node.path,
              projectId: projectCatalog.expandedProjectId,
            },
          );
        }}
        onReferenceNode={(node) => {
          if (!projectCatalog.expandedProjectId) return;
          onReferenceProjectFile?.({
            projectId: projectCatalog.expandedProjectId,
            path: node.path,
            name: node.name,
            kind: node.kind,
          });
        }}
        onRenameStart={controller.browser.startInlineEdit}
        surfaceAriaLabel={t("workspace.projectsPanel.projectFiles")}
        workspaceKey={
          projectCatalog.expandedProjectId
            ? `project:${projectCatalog.expandedProjectId}`
            : null
        }
        workspaceRoot={projectCatalog.expandedProject?.root_path ?? null}
      />
    </div>
  );
}

function WorkspaceProjectList({
  allowExternalImport,
  projectCatalog,
  searchKeyword,
}: {
  allowExternalImport: boolean;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
  searchKeyword: string;
}) {
  const { t } = useI18n();
  const folderImport = useProjectFolderDropImport({
    categoryId: projectCatalog.selectedCategoryId,
    createProjectsFromFolders: projectCatalog.createProjectsFromFolders,
  });
  const { isFileDragOver, targetRef } = useDesktopFileDropTarget<HTMLDivElement>({
    enabled: allowExternalImport,
    onFileDrop: folderImport.handleFileDrop,
    scopeKey: projectCatalog.selectedCategoryId,
  });
  const notice = folderImport.notice === "folders_only"
    ? t("workspace.projectsPanel.externalProjectFoldersOnly")
    : folderImport.notice === "native_paths_unavailable"
      ? t("workspace.projectsPanel.externalProjectFolderPathsUnavailable")
      : folderImport.notice === "import_failed"
        ? t("workspace.projectsPanel.externalProjectFolderImportFailed")
        : null;

  return (
    <div
      ref={targetRef}
      className={isFileDragOver
        ? "workspace-projects-panel__list-drop-target workspace-projects-panel__list-drop-target--active"
        : "workspace-projects-panel__list-drop-target"}
    >
      {isFileDragOver ? (
        <div className="workspace-projects-panel__external-file-notice" role="status">
          {t("workspace.projectsPanel.externalProjectFolderDropHint")}
        </div>
      ) : folderImport.isImporting ? (
        <div className="workspace-projects-panel__external-file-notice" role="status">
          {t("workspace.projectsPanel.externalProjectFolderImporting")}
        </div>
      ) : notice ? (
        <div
          className="workspace-projects-panel__external-file-notice workspace-projects-panel__external-file-notice--error"
          role="status"
        >
          {notice}
        </div>
      ) : null}
      <ProjectListPanel
        itemKind={projectCatalog.selectedCategory?.category_kind ?? "project"}
        projectCatalog={projectCatalog}
        searchKeyword={searchKeyword}
      />
    </div>
  );
}

import { FolderOpen } from "@phosphor-icons/react";
import type { CSSProperties } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { Project } from "../../../entities/project/model/project";
import { getToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";
import type { UseToolFoldersResult } from "../../../features/tool-catalog/model/useToolFolders";
import { revealProjectFile } from "../../../services/project/revealProjectFile";
import { usePageStatusBar } from "../../../widgets/app-frame/model/appStatusBar";
import type { HoverSidebarSectionId } from "../../../widgets/hover-sidebar/model/sidebarSections";
import {
  getWorkspaceProjectKind,
  type WorkspaceProjectCollection,
  type WorkspaceProjectKind,
} from "../model/useWorkspaceProjectCollections";

const PRIMARY_SIDEBAR_COLLAPSED_WIDTH = 52;
const APP_STATUS_BAR_INLINE_PADDING = 12;

type WorkspaceStatusPathOptions = {
  section: HoverSidebarSectionId;
  collections: Record<WorkspaceProjectKind, WorkspaceProjectCollection>;
  toolFolders: Pick<UseToolFoldersResult, "displayedToolsetId" | "expandedFolder" | "selectedFolder">;
  projectTab: DocumentTab | null;
  toolTab: DocumentTab | null;
  sidePanelWidth: number;
};

export function useWorkspaceStatusPath({
  section, collections, toolFolders, projectTab, toolTab, sidePanelWidth,
}: WorkspaceStatusPathOptions) {
  const kind = getWorkspaceProjectKind(section);
  const collection = section === "tools" ? {
    selectedCategoryId: toolFolders.displayedToolsetId,
    expandedProject: toolFolders.expandedFolder,
    selectedProject: toolFolders.selectedFolder,
  } : kind ? collections[kind] : null;
  const item = collection?.expandedProject ?? collection?.selectedProject;
  const projectId = item && item.category_id === collection?.selectedCategoryId ? item.project_id : null;
  const filePath = getExpandedFilePath(collection?.expandedProject, section === "tools" ? toolTab : projectTab);
  const label = item ? buildStatusPathLabel(item.root_path, filePath) : "";
  const maxWidth = Math.max(0, PRIMARY_SIDEBAR_COLLAPSED_WIDTH + sidePanelWidth - APP_STATUS_BAR_INLINE_PADDING);

  usePageStatusBar(() => ({
    left: projectId ? (
      <button
        className="workspace-status-path"
        type="button"
        title={label}
        style={{ "--workspace-status-path-max-width": `${maxWidth}px` } as CSSProperties}
        onClick={() => { void revealProjectFile(projectId, { path: filePath }).catch(() => undefined); }}
      >
        <FolderOpen size={14} weight="bold" />
        <span>{label}</span>
      </button>
    ) : null,
  }), [filePath, label, maxWidth, projectId]);
}

function getExpandedFilePath(
  project: Pick<Project, "category_id" | "project_id"> | null | undefined,
  tab: DocumentTab | null,
) {
  const source = tab?.fileSource;
  if (!project || !source || !tab.filePath) return "";
  if (source.kind === "project" && source.id === project.project_id) return tab.filePath;
  if (source.kind === "tool-folder" && source.key === getToolFolderWorkspaceKey(project.category_id, project.project_id)) {
    return tab.filePath;
  }
  return "";
}

function buildStatusPathLabel(rootPath: string, filePath: string) {
  if (!filePath) return rootPath;
  const separator = rootPath.includes("\\") ? "\\" : "/";
  return rootPath.replace(/[/\\]+$/, "") + separator + filePath.replace(/^[/\\]+/, "").replace(/[/\\]+/g, separator);
}

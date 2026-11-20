import { useEffect, useMemo, useRef, useState } from "react";

import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import {
  isProjectConversationOverviewTab,
  isProjectKnowledgeContentTab,
  isProjectRoleConfigurationTab,
  isProjectThemeConfigurationTab,
} from "../../../features/document-tabs/model/documentTabUtils";
import { getCachedProjectEntryWarmup } from "../../../features/project-entry/model/projectEntryWarmup";
import { snapshotWorkspaceTabs } from "../../../features/document-tabs/model/workspaceTabEntries";
import { patchProjectWorkspaceState, readWorkspaceAfterWrites } from "../../../services/project/saveProjectWorkspaceState";

type ProjectWorkspaceTabsPersistenceOptions = {
  documentTabs: ReturnType<typeof useDocumentTabs>;
  isKnowledgeProject: boolean;
  isRoleProject: boolean;
  isThemeProject: boolean;
  projectId: string | null;
};

export function useProjectWorkspaceTabsPersistence({
  documentTabs,
  isKnowledgeProject,
  isRoleProject,
  isThemeProject,
  projectId,
}: ProjectWorkspaceTabsPersistenceOptions) {
  const [error, setError] = useState<string | null>(null);
  const [readyProject, setReadyProject] = useState<string | null>(null);
  const restoring = useRef(false);
  const workspaceStateSnapshot = useMemo(() => {
    const openFilePaths = documentTabs.tabs
      .filter((tab) => tab.projectId === projectId && tab.projectFilePath)
      .map((tab) => tab.projectFilePath!);
    const activeFilePath = documentTabs.activeTab?.projectId === projectId
      ? documentTabs.activeTab.projectFilePath
      : null;
    const activeDashboard =
      documentTabs.activeTab?.projectId === projectId
      && isProjectConversationOverviewTab(documentTabs.activeTab)
        ? "conversation_overview" as const
        : documentTabs.activeTab?.projectId === projectId
          && isProjectKnowledgeContentTab(documentTabs.activeTab)
          ? "knowledge_content" as const
        : documentTabs.activeTab?.projectId === projectId
          && isProjectRoleConfigurationTab(documentTabs.activeTab)
          ? "role_configuration" as const
        : documentTabs.activeTab?.projectId === projectId
          && isProjectThemeConfigurationTab(documentTabs.activeTab)
          ? "theme_configuration" as const
        : null;

    return {
      active_dashboard: activeDashboard,
      active_file_path: activeFilePath,
      open_file_paths: openFilePaths,
      open_tabs: snapshotWorkspaceTabs(documentTabs.tabs, documentTabs.activeTab?.id ?? null, projectId),
    };
  }, [documentTabs.activeTab, documentTabs.tabs, projectId]);

  useEffect(() => {
    let disposed = false;
    setReadyProject(null);
    restoring.current = true;
    setError(null);

    if (!projectId) {
      documentTabs.resetWorkspaceFiles();
      return;
    }

    const warmedProject = getCachedProjectEntryWarmup(projectId);
    readWorkspaceAfterWrites(projectId, warmedProject?.workspaceState)
      .then(async (state) => {
        if (disposed) return undefined;
        const activeWebId = await documentTabs.restoreTabs(
          projectId,
          state.open_file_paths,
          state.active_file_path,
          { fileContents: warmedProject?.fileContents, entries: state.open_tabs },
        );
        if (disposed) return undefined;
        documentTabs.ensureProjectConversationOverview(projectId, {
          activate: !activeWebId && (
            state.active_dashboard === "conversation_overview"
            || (!isKnowledgeProject && !isRoleProject && !isThemeProject && state.active_file_path === null)),
        });
        if (isKnowledgeProject) {
          documentTabs.ensureProjectKnowledgeContent(projectId, {
            activate: !activeWebId && (
              state.active_dashboard === "knowledge_content"
              || state.active_file_path === null),
          });
        }
        if (isRoleProject) {
          documentTabs.ensureProjectRoleConfiguration(projectId, {
            activate: !activeWebId && (
              state.active_dashboard === "role_configuration"
              || state.active_file_path === null),
          });
        }
        if (isThemeProject) {
          documentTabs.ensureProjectThemeConfiguration(projectId, {
            activate: !activeWebId && (
              state.active_dashboard === "theme_configuration"
              || state.active_file_path === null),
          });
        }
        return undefined;
      })
      .then(() => {
        if (!disposed) {
          restoring.current = false;
          setReadyProject(projectId);
        }
      })
      .catch((restoreError: unknown) => {
        if (disposed) return;
        documentTabs.resetWorkspaceFiles();
        setError(formatWorkspaceTabsError("工作区标签恢复失败", restoreError));
      });

    return () => {
      disposed = true;
    };
  }, [
    documentTabs.resetWorkspaceFiles,
    documentTabs.ensureProjectConversationOverview,
    documentTabs.ensureProjectKnowledgeContent,
    documentTabs.ensureProjectRoleConfiguration,
    documentTabs.ensureProjectThemeConfiguration,
    documentTabs.restoreTabs,
    isKnowledgeProject,
    isRoleProject,
    isThemeProject,
    projectId,
  ]);

  const snapshotKey = JSON.stringify(workspaceStateSnapshot);
  useEffect(() => {
    if (!projectId || readyProject !== projectId || restoring.current) return;
    let disposed = false;
    let retryTimer: number | undefined;

    const saveSnapshot = (attempt: number) => {
      patchProjectWorkspaceState(projectId, workspaceStateSnapshot)
        .then(() => {
          if (!disposed) {
            setError(null);
          }
        })
        .catch((saveError: unknown) => {
          if (disposed) {
            return;
          }

          if (attempt === 0) {
            retryTimer = window.setTimeout(() => {
              saveSnapshot(1);
            }, 600);
            return;
          }

          setError(formatWorkspaceTabsError("工作区标签保存失败", saveError));
        });
    };

    saveSnapshot(0);

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
    };
  }, [projectId, readyProject, snapshotKey]);

  return { error };
}

function formatWorkspaceTabsError(prefix: string, error: unknown) {
  const message = error instanceof Error ? error.message : "未知错误";
  return `${prefix}：${message}`;
}

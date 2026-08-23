import { useEffect, useMemo, useRef, useState } from "react";

import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import {
  isProjectConversationOverviewTab,
  isProjectKnowledgeContentTab,
  isProjectRoleConfigurationTab,
  isProjectThemeConfigurationTab,
} from "../../../features/document-tabs/model/documentTabUtils";
import { getCachedProjectEntryWarmup } from "../../../features/project-entry/model/projectEntryWarmup";
import { getProjectWorkspaceState } from "../../../services/project/getProjectWorkspaceState";
import { patchProjectWorkspaceState } from "../../../services/project/saveProjectWorkspaceState";

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
  const retryTimerRef = useRef<number | null>(null);
  const saveRequestIdRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const isRestoringTabsRef = useRef(false);
  const canPersistTabsRef = useRef(false);
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
      activeDashboard,
      activeFilePath,
      key: JSON.stringify({ activeDashboard, activeFilePath, openFilePaths }),
      openFilePaths,
    };
  }, [documentTabs.activeTab, documentTabs.tabs, projectId]);

  useEffect(() => {
    let disposed = false;
    canPersistTabsRef.current = false;
    setError(null);

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    if (!projectId) {
      documentTabs.closeAllTabs();
      return;
    }

    const warmedProject = getCachedProjectEntryWarmup(projectId);
    isRestoringTabsRef.current = true;
    Promise.resolve(warmedProject?.workspaceState ?? getProjectWorkspaceState(projectId))
      .then(async (state) => {
        if (disposed) return undefined;
        await documentTabs.restoreTabs(
          projectId,
          state.open_file_paths,
          state.active_file_path,
          { fileContents: warmedProject?.fileContents },
        );
        if (disposed) return undefined;
        documentTabs.ensureProjectConversationOverview(projectId, {
          activate:
            state.active_dashboard === "conversation_overview"
            || (!isKnowledgeProject && !isRoleProject && !isThemeProject && state.active_file_path === null),
        });
        if (isKnowledgeProject) {
          documentTabs.ensureProjectKnowledgeContent(projectId, {
            activate:
              state.active_dashboard === "knowledge_content"
              || state.active_file_path === null,
          });
        }
        if (isRoleProject) {
          documentTabs.ensureProjectRoleConfiguration(projectId, {
            activate:
              state.active_dashboard === "role_configuration"
              || state.active_file_path === null,
          });
        }
        if (isThemeProject) {
          documentTabs.ensureProjectThemeConfiguration(projectId, {
            activate:
              state.active_dashboard === "theme_configuration"
              || state.active_file_path === null,
          });
        }
        return undefined;
      })
      .then(() => {
        if (!disposed) {
          canPersistTabsRef.current = true;
        }
      })
      .catch((restoreError: unknown) => {
        if (disposed) return;
        documentTabs.closeAllTabs();
        setError(formatWorkspaceTabsError("工作区标签恢复失败", restoreError));
      })
      .finally(() => {
        if (!disposed) {
          isRestoringTabsRef.current = false;
        }
      });

    return () => {
      disposed = true;
    };
  }, [
    documentTabs.closeAllTabs,
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

  useEffect(() => {
    if (!projectId || isRestoringTabsRef.current || !canPersistTabsRef.current) {
      return;
    }
    let disposed = false;
    saveRequestIdRef.current += 1;
    const requestId = saveRequestIdRef.current;

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    const { activeDashboard, activeFilePath, openFilePaths } = workspaceStateSnapshot;

    const saveSnapshot = (attempt: number) => {
      patchProjectWorkspaceState(projectId, {
        open_file_paths: openFilePaths,
        active_file_path: activeFilePath,
        active_dashboard: activeDashboard,
      })
        .then(() => {
          if (!disposed && saveRequestIdRef.current === requestId) {
            setError(null);
          }
        })
        .catch((saveError: unknown) => {
          if (disposed || saveRequestIdRef.current !== requestId) {
            return;
          }

          if (attempt === 0) {
            retryTimerRef.current = window.setTimeout(() => {
              saveSnapshot(1);
            }, 600);
            return;
          }

          setError(formatWorkspaceTabsError("工作区标签保存失败", saveError));
        });
    };

    saveTimerRef.current = window.setTimeout(() => {
      saveSnapshot(0);
    }, 500);

    return () => {
      disposed = true;
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [projectId, workspaceStateSnapshot.key]);

  return { error };
}

function formatWorkspaceTabsError(prefix: string, error: unknown) {
  const message = error instanceof Error ? error.message : "未知错误";
  return `${prefix}：${message}`;
}

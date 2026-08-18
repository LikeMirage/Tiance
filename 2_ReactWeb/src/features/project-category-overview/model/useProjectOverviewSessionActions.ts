import { useCallback, useMemo, useState } from "react";

import type {
  ProjectOverviewItem,
  ProjectOverviewSession,
} from "../../../entities/project/model/project";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import type { useI18n } from "../../../shared/i18n";
import { deleteProjectConversation } from "../../../services/project/deleteProjectConversation";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import { setProjectConversationPinned } from "../../../services/project/setProjectConversationPinned";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";

export type ProjectOverviewSessionContextMenuState = {
  projectId: string;
  sessionId: string;
  x: number;
  y: number;
};

type PendingSessionAction = {
  projectId: string;
  sessionId: string;
  title: string;
};

type UseProjectOverviewSessionActionsInput = {
  loadOverview: (mode?: "initial" | "refresh") => Promise<void>;
  onSelectSession: (projectId: string, sessionId: string) => Promise<boolean>;
  projects: ProjectOverviewItem[];
  t: ReturnType<typeof useI18n>["t"];
  updateActiveSession: (projectId: string, sessionId: string) => void;
  visibleSession: { projectId: string; sessionId: string | null } | null;
};

export function useProjectOverviewSessionActions({
  loadOverview,
  onSelectSession,
  projects,
  t,
  updateActiveSession,
  visibleSession,
}: UseProjectOverviewSessionActionsInput) {
  const [sessionContextMenu, setSessionContextMenu] =
    useState<ProjectOverviewSessionContextMenuState | null>(null);
  const [renamingSession, setRenamingSession] =
    useState<PendingSessionAction | null>(null);
  const [deletingSession, setDeletingSession] =
    useState<PendingSessionAction | null>(null);
  const [sessionActionBusy, setSessionActionBusy] = useState(false);
  const [sessionActionError, setSessionActionError] = useState<string | null>(null);

  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) return null;
    const project = projects.find(
      (item) => item.project.project_id === sessionContextMenu.projectId,
    );
    return project?.sessions.find(
      (session) => session.session_id === sessionContextMenu.sessionId,
    ) ?? null;
  }, [projects, sessionContextMenu]);

  const openSessionContextMenu = useCallback((
    projectId: string,
    session: ProjectOverviewSession,
    position: { x: number; y: number },
  ) => {
    setSessionActionError(null);
    setSessionContextMenu({
      projectId,
      sessionId: session.session_id,
      x: position.x,
      y: position.y,
    });
  }, []);

  const requestRenameSession = useCallback((
    projectId: string,
    session: ProjectOverviewSession,
  ) => {
    setSessionActionError(null);
    setRenamingSession({
      projectId,
      sessionId: session.session_id,
      title: displaySessionTitle(session.title, t),
    });
  }, [t]);

  const requestDeleteSession = useCallback((
    projectId: string,
    session: ProjectOverviewSession,
  ) => {
    setSessionActionError(null);
    setDeletingSession({
      projectId,
      sessionId: session.session_id,
      title: displaySessionTitle(session.title, t),
    });
  }, [t]);

  const toggleSessionPinned = useCallback(async (
    projectId: string,
    session: ProjectOverviewSession,
  ) => {
    if (sessionActionBusy) return;
    setSessionActionBusy(true);
    setSessionActionError(null);
    try {
      await setProjectConversationPinned(
        projectId,
        session.session_id,
        !session.pinned,
      );
      dispatchProjectConversationUpdated({
        kind: "structure",
        projectId,
        sessionId: session.session_id,
      });
      await loadOverview("refresh");
    } catch (error) {
      setSessionActionError(
        error instanceof Error ? error.message : t("projectOverview.pinFailed"),
      );
    } finally {
      setSessionActionBusy(false);
    }
  }, [loadOverview, sessionActionBusy, t]);

  const confirmRenameSession = useCallback(async (nextValue: string) => {
    if (!renamingSession || sessionActionBusy) return;
    const nextTitle = normalizeSessionTitle(nextValue, t);
    if (nextTitle === renamingSession.title) {
      setRenamingSession(null);
      return;
    }
    setSessionActionBusy(true);
    setSessionActionError(null);
    try {
      await updateProjectConversation(
        renamingSession.projectId,
        renamingSession.sessionId,
        { title: nextTitle },
      );
      dispatchProjectConversationUpdated({
        kind: "structure",
        projectId: renamingSession.projectId,
        sessionId: renamingSession.sessionId,
      });
      await loadOverview("refresh");
      setRenamingSession(null);
    } catch (error) {
      setSessionActionError(
        error instanceof Error ? error.message : t("projectOverview.renameFailed"),
      );
    } finally {
      setSessionActionBusy(false);
    }
  }, [loadOverview, renamingSession, sessionActionBusy, t]);

  const confirmDeleteSession = useCallback(async (sessionIds: string[]) => {
    if (!deletingSession || sessionActionBusy) return;
    setSessionActionBusy(true);
    setSessionActionError(null);
    try {
      await deleteProjectConversation(
        deletingSession.projectId,
        deletingSession.sessionId,
        sessionIds,
      );
      dispatchProjectConversationUpdated({
        kind: "structure",
        projectId: deletingSession.projectId,
        sessionId: deletingSession.sessionId,
      });
      const sessionList = await getProjectConversations(deletingSession.projectId);
      const nextSessionId =
        sessionList.active_session_id ?? sessionList.items[0]?.session_id ?? null;
      const shouldSelectNext =
        visibleSession?.projectId === deletingSession.projectId &&
        visibleSession.sessionId === deletingSession.sessionId;

      if (shouldSelectNext && nextSessionId) {
        await onSelectSession(deletingSession.projectId, nextSessionId);
        updateActiveSession(deletingSession.projectId, nextSessionId);
      }

      await loadOverview("refresh");
      setDeletingSession(null);
    } catch (error) {
      setSessionActionError(
        error instanceof Error ? error.message : t("projectOverview.deleteFailed"),
      );
    } finally {
      setSessionActionBusy(false);
    }
  }, [
    deletingSession,
    loadOverview,
    onSelectSession,
    sessionActionBusy,
    t,
    updateActiveSession,
    visibleSession,
  ]);

  const cancelRenameSession = useCallback(() => {
    if (sessionActionBusy) return;
    setRenamingSession(null);
    setSessionActionError(null);
  }, [sessionActionBusy]);

  const cancelDeleteSession = useCallback(() => {
    if (sessionActionBusy) return;
    setDeletingSession(null);
    setSessionActionError(null);
  }, [sessionActionBusy]);

  return {
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
    sessionContextMenu,
    setSessionContextMenu,
    toggleSessionPinned,
  };
}

function displaySessionTitle(
  title: string,
  t: ReturnType<typeof useI18n>["t"],
) {
  return title.trim() || t("projectOverview.newConversation");
}

function normalizeSessionTitle(
  value: string,
  t: ReturnType<typeof useI18n>["t"],
) {
  return value.trim().replace(/\s+/g, " ") || t("projectOverview.newConversation");
}

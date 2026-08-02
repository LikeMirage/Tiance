import { memo, useCallback, useMemo, useState } from "react";

import type { ProjectOverviewSession } from "../../../entities/project/model/project";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { useI18n } from "../../../shared/i18n";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { deleteProjectConversation } from "../../../services/project/deleteProjectConversation";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import { setProjectConversationPinned } from "../../../services/project/setProjectConversationPinned";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import { useProjectConversationOverview } from "../model/useProjectConversationOverview";
import type { ProjectOverviewSessionContextMenuState } from "../model/useProjectOverviewSessionActions";
import { ProjectOverviewCard } from "./ProjectOverviewCard";
import { ProjectOverviewSessionContextMenu } from "./ProjectOverviewSessionContextMenu";

import "./project-category-overview.css";
import "./project-conversation-overview-dashboard.css";

type PendingSessionAction = {
  sessionId: string;
  title: string;
};

type ProjectConversationOverviewDashboardProps = {
  isActive: boolean;
  onCreateSession: (projectId: string) => Promise<void>;
  onOpenConversationBranches: (
    projectId: string,
    sessionId: string | null,
  ) => Promise<void>;
  onRevealProject: (projectId: string) => Promise<void>;
  onSelectSession: (projectId: string, sessionId: string) => Promise<boolean>;
  projectId: string | null;
  visibleSession: { projectId: string; sessionId: string | null } | null;
};

export const ProjectConversationOverviewDashboard = memo(
  function ProjectConversationOverviewDashboard({
    isActive,
    onCreateSession,
    onOpenConversationBranches,
    onRevealProject,
    onSelectSession,
    projectId,
    visibleSession,
  }: ProjectConversationOverviewDashboardProps) {
    const { t } = useI18n();
    const {
      error,
      liveUsageBySessionKey,
      loadOverview,
      overview,
      state,
      updateActiveSession,
    } = useProjectConversationOverview(projectId, isActive);
    const [creating, setCreating] = useState(false);
    const [usageOpen, setUsageOpen] = useState(false);
    const [sessionContextMenu, setSessionContextMenu] =
      useState<ProjectOverviewSessionContextMenuState | null>(null);
    const [renamingSession, setRenamingSession] =
      useState<PendingSessionAction | null>(null);
    const [deletingSession, setDeletingSession] =
      useState<PendingSessionAction | null>(null);
    const [sessionActionBusy, setSessionActionBusy] = useState(false);
    const [sessionActionError, setSessionActionError] = useState<string | null>(null);
    const isLoadingVisible = useMinimumLoading(state === "loading", 240);

    const contextMenuSession = useMemo(() => {
      if (!overview || !sessionContextMenu) return null;
      return overview.sessions.find(
        (session) => session.session_id === sessionContextMenu.sessionId,
      ) ?? null;
    }, [overview, sessionContextMenu]);

    const handleCreateSession = useCallback(async (targetProjectId: string) => {
      if (creating) return;
      setCreating(true);
      try {
        await onCreateSession(targetProjectId);
        await loadOverview();
      } finally {
        setCreating(false);
      }
    }, [creating, loadOverview, onCreateSession]);

    const handleSelectSession = useCallback(async (
      targetProjectId: string,
      sessionId: string,
    ) => {
      if (await onSelectSession(targetProjectId, sessionId)) {
        updateActiveSession(sessionId);
      }
    }, [onSelectSession, updateActiveSession]);

    const handleOpenSessionContextMenu = useCallback((
      targetProjectId: string,
      session: ProjectOverviewSession,
      position: { x: number; y: number },
    ) => {
      setSessionActionError(null);
      setSessionContextMenu({
        projectId: targetProjectId,
        sessionId: session.session_id,
        x: position.x,
        y: position.y,
      });
    }, []);

    const handleToggleSessionPinned = useCallback(async (
      targetProjectId: string,
      session: ProjectOverviewSession,
    ) => {
      if (sessionActionBusy) return;
      setSessionActionBusy(true);
      setSessionActionError(null);
      try {
        await setProjectConversationPinned(
          targetProjectId,
          session.session_id,
          !session.pinned,
        );
        dispatchProjectConversationUpdated({
          kind: "structure",
          projectId: targetProjectId,
          sessionId: session.session_id,
        });
        await loadOverview();
      } catch (actionError) {
        setSessionActionError(
          actionError instanceof Error
            ? actionError.message
            : t("projectOverview.pinFailed"),
        );
      } finally {
        setSessionActionBusy(false);
      }
    }, [loadOverview, sessionActionBusy, t]);

    const handleCommitSessionRename = useCallback(async (nextValue: string) => {
      if (!projectId || !renamingSession || sessionActionBusy) return;
      const nextTitle = normalizeSessionTitle(nextValue, t);
      if (nextTitle === renamingSession.title) {
        setRenamingSession(null);
        return;
      }
      setSessionActionBusy(true);
      setSessionActionError(null);
      try {
        await updateProjectConversation(projectId, renamingSession.sessionId, {
          title: nextTitle,
        });
        dispatchProjectConversationUpdated({
          kind: "structure",
          projectId,
          sessionId: renamingSession.sessionId,
        });
        await loadOverview();
        setRenamingSession(null);
      } catch (actionError) {
        setSessionActionError(
          actionError instanceof Error
            ? actionError.message
            : t("projectOverview.renameFailed"),
        );
      } finally {
        setSessionActionBusy(false);
      }
    }, [loadOverview, projectId, renamingSession, sessionActionBusy, t]);

    const handleConfirmDeleteSession = useCallback(async () => {
      if (!projectId || !deletingSession || sessionActionBusy) return;
      setSessionActionBusy(true);
      setSessionActionError(null);
      try {
        await deleteProjectConversation(projectId, deletingSession.sessionId);
        dispatchProjectConversationUpdated({
          kind: "structure",
          projectId,
          sessionId: deletingSession.sessionId,
        });
        const sessionList = await getProjectConversations(projectId);
        const nextSessionId =
          sessionList.active_session_id ?? sessionList.items[0]?.session_id ?? null;
        const deletedVisibleSession =
          visibleSession?.projectId === projectId
          && visibleSession.sessionId === deletingSession.sessionId;
        if (deletedVisibleSession && nextSessionId) {
          await onSelectSession(projectId, nextSessionId);
          updateActiveSession(nextSessionId);
        }
        await loadOverview();
        setDeletingSession(null);
      } catch (actionError) {
        setSessionActionError(
          actionError instanceof Error
            ? actionError.message
            : t("projectOverview.deleteFailed"),
        );
      } finally {
        setSessionActionBusy(false);
      }
    }, [
      deletingSession,
      loadOverview,
      onSelectSession,
      projectId,
      sessionActionBusy,
      t,
      updateActiveSession,
      visibleSession,
    ]);

    if (isLoadingVisible) {
      return (
        <LoadingStrip
          ariaLabel={t("projectOverview.loadingAria")}
          className="project-conversation-overview-dashboard__loading"
          mode="fill"
          visual="ring"
        />
      );
    }

    if (state === "error" || !overview) {
      return (
        <div className="project-conversation-overview-dashboard__status">
          <span>{error ?? t("projectOverview.loadFailed")}</span>
          <button type="button" onClick={() => void loadOverview()}>
            {t("common.actions.retry")}
          </button>
        </div>
      );
    }

    return (
      <section
        className="project-conversation-overview-dashboard"
        aria-label={t("projectOverview.card.sessionsAria")}
      >
        {sessionActionError && !renamingSession && !deletingSession ? (
          <p className="project-category-overview__session-action-error" role="alert">
            {sessionActionError}
          </p>
        ) : null}
        <div className="project-conversation-overview-dashboard__card">
          <ProjectOverviewCard
            creating={creating}
            isMaximized={false}
            item={overview}
            liveUsageBySessionKey={liveUsageBySessionKey}
            onCancelSessionRename={() => {
              if (sessionActionBusy) return;
              setRenamingSession(null);
              setSessionActionError(null);
            }}
            onCloseUsage={() => setUsageOpen(false)}
            onCommitSessionRename={handleCommitSessionRename}
            onCreateSession={handleCreateSession}
            onEnterSession={handleSelectSession}
            onOpenConversationBranches={onOpenConversationBranches}
            onOpenSessionContextMenu={handleOpenSessionContextMenu}
            onRevealProject={onRevealProject}
            onSelectSession={handleSelectSession}
            onToggleMaximized={() => undefined}
            onToggleUsage={() => setUsageOpen((current) => !current)}
            renameError={renamingSession ? sessionActionError : null}
            renamingSessionBusy={sessionActionBusy}
            renamingSessionId={renamingSession?.sessionId ?? null}
            showMaximizeAction={false}
            usageOpen={usageOpen}
            visibleSession={visibleSession}
          />
        </div>

        {isActive && sessionContextMenu && contextMenuSession ? (
          <ProjectOverviewSessionContextMenu
            busy={sessionActionBusy}
            contextMenu={sessionContextMenu}
            onClose={() => setSessionContextMenu(null)}
            onRequestDelete={(_targetProjectId, session) => {
              setSessionActionError(null);
              setDeletingSession({
                sessionId: session.session_id,
                title: displaySessionTitle(session.title, t),
              });
            }}
            onRequestRename={(_targetProjectId, session) => {
              setSessionActionError(null);
              setRenamingSession({
                sessionId: session.session_id,
                title: displaySessionTitle(session.title, t),
              });
            }}
            onTogglePinned={(targetProjectId, session) => {
              void handleToggleSessionPinned(targetProjectId, session);
            }}
            session={contextMenuSession}
          />
        ) : null}

        {isActive && deletingSession ? (
          <ConfirmModal
            cancelDisabled={sessionActionBusy}
            confirmDisabled={sessionActionBusy}
            confirmLabel={sessionActionBusy
              ? t("projectOverview.deleteSessionDeleting")
              : t("common.actions.delete")}
            danger
            message={t("projectOverview.deleteSessionMessage", {
              title: deletingSession.title,
            })}
            onCancel={() => {
              if (sessionActionBusy) return;
              setDeletingSession(null);
              setSessionActionError(null);
            }}
            onConfirm={() => void handleConfirmDeleteSession()}
            title={t("projectOverview.deleteSessionTitle")}
          >
            {sessionActionError ? (
              <p className="project-category-overview__session-action-error">
                {sessionActionError}
              </p>
            ) : null}
          </ConfirmModal>
        ) : null}
      </section>
    );
  },
);

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

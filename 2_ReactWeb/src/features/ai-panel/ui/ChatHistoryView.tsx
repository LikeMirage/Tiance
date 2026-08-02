import type {
  ConversationSession,
  ConversationSessionState,
} from "../../../entities/llm-chat/model/conversation";
import { PushPin } from "@phosphor-icons/react";
import { useI18n } from "../../../shared/i18n";
import {
  buildHistoryStatusClass,
  formatRuntimeStatus,
  formatSessionUpdatedAt,
} from "../model/sessionDisplay";
import { SessionDisplayTitle } from "./SessionDisplayTitle";

type Props = {
  activeSessionId: string | null;
  confirmingDeleteSessionId: string | null;
  deletingSessionId: string | null;
  isSessionStreaming: (sessionId: string) => boolean;
  onActivateSession: (sessionId: string) => void;
  onConfirmDeleteSession: (sessionId: string) => void;
  onToggleDeleteConfirm: (sessionId: string) => void;
  onTogglePinned: (session: ConversationSession) => void;
  pinErrorMessage: string | null;
  pinningSessionId: string | null;
  sessions: ConversationSession[];
  sessionStates: Record<string, ConversationSessionState>;
};

export function ChatHistoryView({
  activeSessionId,
  confirmingDeleteSessionId,
  deletingSessionId,
  isSessionStreaming,
  onActivateSession,
  onConfirmDeleteSession,
  onToggleDeleteConfirm,
  onTogglePinned,
  pinErrorMessage,
  pinningSessionId,
  sessions,
  sessionStates,
}: Props) {
  const { language, t } = useI18n();
  const runtimeLabels = {
    error: t("aiPanel.history.runtime.error"),
    idle: t("aiPanel.history.runtime.idle"),
    running: t("aiPanel.history.runtime.running"),
  };

  return (
    <div className="ai-panel__tab-view">
      <h3 className="ai-panel__tab-title">{t("aiPanel.history.title")}</h3>
      {pinErrorMessage ? (
        <p className="ai-panel__history-error" role="alert">
          {pinErrorMessage}
        </p>
      ) : null}
      {sessions.length === 0 ? (
        <p className="ai-panel__tab-empty">{t("aiPanel.history.empty")}</p>
      ) : (
        <div className="ai-panel__history-list">
          {sessions.map((session) => {
            const isDeleting = deletingSessionId === session.session_id;
            const isConfirmingDelete = confirmingDeleteSessionId === session.session_id;
            const runtimeStatus = sessionStates[session.session_id]?.runtime_status ?? "idle";
            const isDeleteDisabled =
              isDeleting ||
              runtimeStatus === "running" ||
              isSessionStreaming(session.session_id);
            return (
              <div
                key={session.session_id}
                className={session.session_id === activeSessionId ? "ai-panel__history-item ai-panel__history-item--active" : "ai-panel__history-item"}
              >
                <button
                  className="ai-panel__history-main"
                  type="button"
                  onClick={() => onActivateSession(session.session_id)}
                >
                  <span className="ai-panel__history-text">
                    {session.pinned ? (
                      <PushPin
                        className="ai-panel__history-pin-icon"
                        size={13}
                        weight="fill"
                        aria-hidden="true"
                      />
                    ) : null}
                    <SessionDisplayTitle session={session} />
                  </span>
                  <span className="ai-panel__history-meta-row">
                    <span className={buildHistoryStatusClass(runtimeStatus)}>
                      <span className="ai-panel__history-status-dot" aria-hidden="true" />
                      {formatRuntimeStatus(runtimeStatus, runtimeLabels)}
                    </span>
                    <span className="ai-panel__history-role">
                      {t("aiPanel.history.messageCount", { count: session.message_count })} · {session.model_id ?? t("aiPanel.history.noModel")}
                    </span>
                    <span className="ai-panel__history-time">
                      {formatSessionUpdatedAt(
                        session.updated_at,
                        language,
                        t("aiPanel.history.unknownTime"),
                      )}
                    </span>
                  </span>
                </button>
                <div className="ai-panel__history-actions">
                  <button
                    className="ai-panel__history-pin-toggle"
                    type="button"
                    disabled={pinningSessionId !== null}
                    onClick={() => onTogglePinned(session)}
                  >
                    {session.pinned
                      ? t("common.actions.unpin")
                      : t("common.actions.pin")}
                  </button>
                  <div className={isConfirmingDelete ? "ai-panel__history-delete ai-panel__history-delete--confirming" : "ai-panel__history-delete"}>
                    <button
                      className="ai-panel__history-delete-confirm"
                      type="button"
                      disabled={!isConfirmingDelete || isDeleteDisabled}
                      onClick={() => onConfirmDeleteSession(session.session_id)}
                    >
                      {isDeleting ? t("aiPanel.history.deleting") : t("common.actions.confirm")}
                    </button>
                    <button
                      className={isConfirmingDelete ? "ai-panel__history-delete-toggle ai-panel__history-delete-toggle--cancel" : "ai-panel__history-delete-toggle"}
                      type="button"
                      disabled={isDeleting}
                      onClick={() => onToggleDeleteConfirm(session.session_id)}
                    >
                      {isConfirmingDelete ? t("common.actions.cancel") : t("common.actions.delete")}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

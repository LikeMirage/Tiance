import {
  GearSix,
  NotePencil,
} from "@phosphor-icons/react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import { SessionDisplayTitle } from "./SessionDisplayTitle";

export type ChatPanelView = "chat" | "settings";

type Props = {
  activeSession: ConversationSession | null;
  activeView: ChatPanelView;
  canCreateConversation: boolean;
  isLoadingSession: boolean;
  onCreateConversation: () => void;
  onShowChat: () => void;
  onToggleSettings: () => void;
};

export function ChatHeader({
  activeSession,
  activeView,
  canCreateConversation,
  isLoadingSession,
  onCreateConversation,
  onShowChat,
  onToggleSettings,
}: Props) {
  const { t } = useI18n();
  const title = activeSession
    ? <SessionDisplayTitle session={activeSession} />
    : isLoadingSession
      ? ""
      : t("aiPanel.header.noSession");

  return (
    <header className="ai-panel__header">
      <div className="ai-panel__title-group">
        <div className="ai-panel__title-copy">
          <h2 className="ai-panel__title">
            {activeView === "settings" ? (
              <button
                className="ai-panel__title-button"
                type="button"
                aria-label={t("aiPanel.header.backToChat")}
                title={t("aiPanel.header.backToChat")}
                onClick={onShowChat}
              >
                {title}
              </button>
            ) : (
              title
            )}
          </h2>
        </div>
      </div>
      <div className="ai-panel__actions" aria-label={t("aiPanel.header.actions")}>
        <button
          className={activeView === "settings" ? "ai-panel__action ai-panel__action--active" : "ai-panel__action"}
          type="button"
          aria-label={t("aiPanel.header.settings")}
          title={t("aiPanel.header.settings")}
          onClick={onToggleSettings}
        >
          <GearSix size={15} weight="regular" aria-hidden="true" />
        </button>
        <button
          className="ai-panel__action"
          type="button"
          aria-label={t("aiPanel.header.newConversation")}
          title={t("aiPanel.header.newConversation")}
          disabled={!canCreateConversation}
          onClick={onCreateConversation}
        >
          <NotePencil size={15} weight="regular" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

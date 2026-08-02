import { useLayoutEffect, useRef, useState } from "react";

import type { ConversationSession, ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { useI18n } from "../../../shared/i18n";
import type { OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import { ChatBasicSettingsPanel } from "./ChatBasicSettingsPanel";
import { ChatDataDashboardPanel, type ConversationDataFileName } from "./ChatDataDashboardPanel";
import { ChatGlobalMemoryPanel } from "./ChatGlobalMemoryPanel";
import { ChatMemorySettingsPanel } from "./ChatMemorySettingsPanel";
import { ChatToolSettingsPanel } from "./ChatToolSettingsPanel";

export type ChatSettingsPanel = "basic" | "memory" | "globalMemory" | "tools" | "data";

type Props = {
  activeReasoningMode: DsLlmReasoningMode;
  activeConversationDataFile?: ConversationDataFileName | null;
  activeSession: ConversationSession | null;
  activeSettingsPanel: ChatSettingsPanel;
  activeSessionSettings: ConversationSessionSettings;
  projectId: string | null;
  onOpenConversationDataFile?: (sessionId: string, fileName: ConversationDataFileName) => void;
  onRoleSessionUpdated: (session: ConversationSession) => void;
  onSaveSessionTitle: () => void;
  onSaveSystemPrompt: () => void;
  onSessionTitleDraftChange: (value: string) => void;
  onSystemPromptDraftChange: (value: string) => void;
  onUpdateReasoningMode: (mode: DsLlmReasoningMode | null) => void;
  onUpdateSessionSettings: (patch: Partial<ConversationSessionSettings>) => void;
  reasoningOptions: Array<OptionSelectItem<DsLlmReasoningMode>>;
  saveErrorMessage: string | null;
  sessionTitleDraft: string;
  shouldShowReasoningControl: boolean;
  systemPromptDraft: string;
};

type SettingsPanelTransition = {
  direction: "forward" | "back";
} | null;

const SETTINGS_PANEL_ORDER: ChatSettingsPanel[] = ["basic", "memory", "globalMemory", "tools", "data"];

export function ChatSettingsView({
  activeReasoningMode,
  activeConversationDataFile,
  activeSession,
  activeSettingsPanel,
  activeSessionSettings,
  projectId,
  onOpenConversationDataFile,
  onRoleSessionUpdated,
  onSaveSessionTitle,
  onSaveSystemPrompt,
  onSessionTitleDraftChange,
  onSystemPromptDraftChange,
  onUpdateReasoningMode,
  onUpdateSessionSettings,
  reasoningOptions,
  saveErrorMessage,
  sessionTitleDraft,
  shouldShowReasoningControl,
  systemPromptDraft,
}: Props) {
  const { t } = useI18n();
  const previousPanelRef = useRef<ChatSettingsPanel>(activeSettingsPanel);
  const [transition, setTransition] = useState<SettingsPanelTransition>(null);

  const basicPanel = activeSession && projectId ? (
    <ChatBasicSettingsPanel
      activeReasoningMode={activeReasoningMode}
      activeSession={activeSession}
      activeSessionSettings={activeSessionSettings}
      projectId={projectId}
      onRoleSessionUpdated={onRoleSessionUpdated}
      onSaveSessionTitle={onSaveSessionTitle}
      onSaveSystemPrompt={onSaveSystemPrompt}
      onSessionTitleDraftChange={onSessionTitleDraftChange}
      onSystemPromptDraftChange={onSystemPromptDraftChange}
      onUpdateReasoningMode={onUpdateReasoningMode}
      onUpdateSessionSettings={onUpdateSessionSettings}
      reasoningOptions={reasoningOptions}
      sessionTitleDraft={sessionTitleDraft}
      shouldShowReasoningControl={shouldShowReasoningControl}
      systemPromptDraft={systemPromptDraft}
    />
  ) : null;
  const memoryPanel = activeSession ? (
    <ChatMemorySettingsPanel
      settings={activeSessionSettings}
      onChange={onUpdateSessionSettings}
      onOpenDataFile={onOpenConversationDataFile
        ? (fileName) => onOpenConversationDataFile(activeSession.session_id, fileName)
        : undefined}
    />
  ) : null;
  const globalMemoryPanel = activeSession ? (
    <ChatGlobalMemoryPanel
      projectId={projectId}
      settings={activeSessionSettings}
      onChange={onUpdateSessionSettings}
    />
  ) : null;
  const toolsPanel = activeSession ? (
    <ChatToolSettingsPanel
      settings={activeSessionSettings}
      onChange={onUpdateSessionSettings}
    />
  ) : null;
  const dataPanel = activeSession ? (
    <ChatDataDashboardPanel
      activeFileName={activeConversationDataFile}
      onOpenDataFile={onOpenConversationDataFile
        ? (fileName) => onOpenConversationDataFile(activeSession.session_id, fileName)
        : undefined}
    />
  ) : null;
  const currentPanelContent = activeSettingsPanel === "data"
    ? dataPanel
    : activeSettingsPanel === "tools"
      ? toolsPanel
      : activeSettingsPanel === "globalMemory"
        ? globalMemoryPanel
        : activeSettingsPanel === "memory"
          ? memoryPanel
          : basicPanel;

  useLayoutEffect(() => {
    if (activeSettingsPanel === previousPanelRef.current) {
      return;
    }

    const direction = SETTINGS_PANEL_ORDER.indexOf(activeSettingsPanel) >
      SETTINGS_PANEL_ORDER.indexOf(previousPanelRef.current)
      ? "forward"
      : "back";
    setTransition({
      direction,
    });
    previousPanelRef.current = activeSettingsPanel;

    const timer = window.setTimeout(() => setTransition(null), 320);
    return () => window.clearTimeout(timer);
  }, [activeSettingsPanel]);

  return (
    <div className="ai-panel__tab-view">
      {!activeSession ? (
        <p className="ai-panel__tab-empty">{t("aiPanel.settingsTabs.empty")}</p>
      ) : (
        <div className="ai-panel__settings-view-stage">
          {saveErrorMessage ? (
            <div className="ai-panel__settings-save-error" aria-live="polite">
              {saveErrorMessage}
            </div>
          ) : null}
          <div
            className={
              transition
                ? transition.direction === "forward"
                  ? "ai-panel__settings-view ai-panel__settings-view--static ai-panel__settings-view--enter-from-right"
                  : "ai-panel__settings-view ai-panel__settings-view--static ai-panel__settings-view--enter-from-left"
                : "ai-panel__settings-view ai-panel__settings-view--static"
            }
          >
            {currentPanelContent}
          </div>
        </div>
      )}
    </div>
  );
}

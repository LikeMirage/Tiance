import { useId, useRef, useState } from "react";

import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { useI18n } from "../../../shared/i18n";
import {
  ContextMenu,
  ContextMenuItem,
  type ContextMenuPosition,
} from "../../../shared/ui/context-menu";
import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import { SettingsIntegerInput, SettingsNumberInput, SettingsToggle } from "./ChatSettingControls";
import { ChatRoleSelector } from "./ChatRoleSelector";

type Props = {
  activeReasoningMode: DsLlmReasoningMode;
  activeSession: ConversationSession;
  activeSessionSettings: ConversationSessionSettings;
  projectId: string;
  onRoleSessionUpdated: (session: ConversationSession) => void;
  onSaveSessionTitle: () => void;
  onSaveSystemPrompt: () => void;
  onSessionTitleDraftChange: (value: string) => void;
  onSystemPromptDraftChange: (value: string) => void;
  onUpdateReasoningMode: (mode: DsLlmReasoningMode | null) => void;
  onUpdateSessionSettings: (patch: Partial<ConversationSessionSettings>) => void;
  reasoningOptions: Array<OptionSelectItem<DsLlmReasoningMode>>;
  sessionTitleDraft: string;
  shouldShowReasoningControl: boolean;
  systemPromptDraft: string;
};

export function ChatBasicSettingsPanel({
  activeReasoningMode,
  activeSession,
  activeSessionSettings,
  projectId,
  onRoleSessionUpdated,
  onSaveSessionTitle,
  onSaveSystemPrompt,
  onSessionTitleDraftChange,
  onSystemPromptDraftChange,
  onUpdateReasoningMode,
  onUpdateSessionSettings,
  reasoningOptions,
  sessionTitleDraft,
  shouldShowReasoningControl,
  systemPromptDraft,
}: Props) {
  const { t } = useI18n();
  const promptInputId = useId();
  const promptInputRef = useRef<HTMLTextAreaElement>(null);
  const presetButtonRef = useRef<HTMLButtonElement>(null);
  const [presetMenuPosition, setPresetMenuPosition] = useState<ContextMenuPosition | null>(null);

  return (
    <div className="ai-panel__settings">
      <ChatRoleSelector
        projectId={projectId}
        session={activeSession}
        onSessionUpdated={onRoleSessionUpdated}
      />

      <label className="ai-panel__setting-row">
        <span className="ai-panel__setting-label">{t("aiPanel.basicSettings.sessionTitle")}</span>
        <input
          className="ai-panel__text-input"
          value={sessionTitleDraft}
          onBlur={onSaveSessionTitle}
          onChange={(event) => onSessionTitleDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
        />
      </label>

      <div className="ai-panel__field">
        <label className="ai-panel__field-label" htmlFor={promptInputId}>
          {t("aiPanel.basicSettings.systemPrompt")}
        </label>
        <div className="ai-panel__prompt-editor">
          <textarea
            ref={promptInputRef}
            id={promptInputId}
            className="ai-panel__prompt-input ai-panel__prompt-editor-input"
            value={systemPromptDraft}
            onBlur={onSaveSystemPrompt}
            onChange={(event) => onSystemPromptDraftChange(event.target.value)}
          />
          <div className="ai-panel__prompt-editor-footer">
            <button
              ref={presetButtonRef}
              type="button"
              className="ai-panel__prompt-editor-action"
              aria-expanded={presetMenuPosition !== null}
              aria-haspopup="menu"
              onClick={() => {
                if (presetMenuPosition) {
                  setPresetMenuPosition(null);
                  return;
                }
                const rect = presetButtonRef.current?.getBoundingClientRect();
                if (rect) {
                  setPresetMenuPosition({ x: rect.left, y: rect.bottom + 4 });
                }
              }}
            >
              {t("aiPanel.basicSettings.selectSystemPromptPreset")}
            </button>
            <button
              type="button"
              className="ai-panel__prompt-editor-action ai-panel__prompt-editor-action--clear"
              aria-label={t("aiPanel.basicSettings.clearSystemPrompt")}
              disabled={systemPromptDraft.length === 0}
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => {
                onSystemPromptDraftChange("");
                promptInputRef.current?.focus();
              }}
            >
              {t("common.actions.clear")}
            </button>
          </div>
        </div>
      </div>
      {presetMenuPosition ? (
        <ContextMenu
          minWidth={168}
          position={presetMenuPosition}
          onClose={() => setPresetMenuPosition(null)}
        >
          <ContextMenuItem disabled onSelect={() => undefined}>
            {t("aiPanel.basicSettings.noSystemPromptPresets")}
          </ContextMenuItem>
        </ContextMenu>
      ) : null}

      <div className="ai-panel__setting-row">
        <span className="ai-panel__setting-label">{t("aiPanel.basicSettings.reasoningDepth")}</span>
        {shouldShowReasoningControl ? (
          <OptionSelect
            ariaLabel={t("aiPanel.basicSettings.reasoningDepth")}
            className="ai-panel__settings-select"
            floating
            options={reasoningOptions}
            value={activeReasoningMode}
            onChange={onUpdateReasoningMode}
          />
        ) : (
          <span className="ai-panel__setting-value">{t("aiPanel.basicSettings.unsupportedByModel")}</span>
        )}
      </div>

      <SettingsNumberInput
        defaultValue={1}
        label={t("aiPanel.basicSettings.temperature")}
        min={0}
        placeholder={t("aiPanel.basicSettings.defaultValue")}
        step={0.1}
        value={activeSessionSettings.temperature}
        onCommit={(value) => onUpdateSessionSettings({ temperature: value })}
      />
      <SettingsNumberInput
        defaultValue={1}
        label="Top P"
        min={0}
        placeholder={t("aiPanel.basicSettings.defaultValue")}
        step={0.05}
        value={activeSessionSettings.top_p}
        onCommit={(value) => onUpdateSessionSettings({ top_p: value })}
      />
      <SettingsIntegerInput
        label={t("aiPanel.basicSettings.maxOutputTokens")}
        min={1}
        value={activeSessionSettings.max_output_tokens}
        onCommit={(value) => onUpdateSessionSettings({ max_output_tokens: value })}
      />

      <SettingsToggle
        checked={activeSessionSettings.return_thinking_content}
        label={t("aiPanel.basicSettings.returnThinkingContent")}
        onChange={(checked) => onUpdateSessionSettings({
          return_thinking_content: checked,
        })}
      />
      <SettingsToggle
        checked={activeSessionSettings.return_cancelled_messages}
        label={t("aiPanel.basicSettings.returnCancelledMessages")}
        onChange={(checked) => onUpdateSessionSettings({
          return_cancelled_messages: checked,
        })}
      />
      <SettingsToggle
        checked={activeSessionSettings.return_user_before_cancelled}
        label={t("aiPanel.basicSettings.returnUserBeforeCancelled")}
        onChange={(checked) => onUpdateSessionSettings({
          return_user_before_cancelled: checked,
        })}
      />
      <SettingsToggle
        checked={activeSessionSettings.streaming_enabled}
        label={t("aiPanel.basicSettings.streamingOutput")}
        onChange={(checked) => onUpdateSessionSettings({
          streaming_enabled: checked,
        })}
      />
      <SettingsToggle
        checked={activeSessionSettings.auto_collapse_assistant_process}
        label={t("aiPanel.basicSettings.autoCollapseProcess")}
        onChange={(checked) => onUpdateSessionSettings({
          auto_collapse_assistant_process: checked,
        })}
      />
      <SettingsToggle
        checked={activeSessionSettings.inject_message_timestamps}
        label={t("aiPanel.basicSettings.injectMessageTimestamps")}
        onChange={(checked) => onUpdateSessionSettings({
          inject_message_timestamps: checked,
        })}
      />

    </div>
  );
}

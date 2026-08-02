import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import type { ConversationDataFileName } from "./ChatDataDashboardPanel";
import { SettingsIntegerInput, SettingsToggle } from "./ChatSettingControls";

export function ChatMemorySettingsPanel({
  onChange,
  onOpenDataFile,
  settings,
}: {
  onChange: (patch: Partial<ConversationSessionSettings>) => void;
  onOpenDataFile?: (fileName: ConversationDataFileName) => void;
  settings: ConversationSessionSettings;
}) {
  const { t } = useI18n();

  return (
    <div className="ai-panel__settings">
      <SettingsToggle
        checked={settings.memory_compression_enabled}
        label={t("aiPanel.memorySettings.enabled")}
        onChange={(checked) => onChange({ memory_compression_enabled: checked })}
      />

      <div className="ai-panel__setting-group">
        <span className="ai-panel__setting-group-title">{t("aiPanel.memorySettings.contextCompaction")}</span>
        <SettingsIntegerInput
          description={t("aiPanel.memorySettings.rawContextTokenReserveDescription")}
          disabled={!settings.memory_compression_enabled}
          label={t("aiPanel.memorySettings.rawContextTokenReserve")}
          min={0}
          suffix={t("aiPanel.memorySettings.units.token")}
          value={settings.memory_raw_context_token_reserve}
          onCommit={(value) => onChange(normalizeMemorySettingsPatch({
            memory_raw_context_token_reserve: value,
          }, settings))}
        />
        <SettingsIntegerInput
          description={t("aiPanel.memorySettings.contextTokenThresholdDescription")}
          disabled={!settings.memory_compression_enabled}
          label={t("aiPanel.memorySettings.contextTokenThreshold")}
          min={1}
          suffix={t("aiPanel.memorySettings.units.token")}
          value={settings.memory_context_token_trigger_threshold}
          onCommit={(value) => onChange(normalizeMemorySettingsPatch({
            memory_context_token_trigger_threshold: value,
          }, settings))}
        />
      </div>

      <div className="ai-panel__setting-group ai-panel__memory-action-row">
        <button
          className="ai-panel__memory-action"
          type="button"
          disabled={!onOpenDataFile}
          onClick={() => onOpenDataFile?.("compressions.jsonl")}
        >
          {t("aiPanel.memorySettings.compressionManager")}
        </button>
        <button
          className="ai-panel__memory-action"
          type="button"
          disabled={!onOpenDataFile}
          onClick={() => onOpenDataFile?.("injection_preview.json")}
        >
          {t("aiPanel.memorySettings.injectionPreview")}
        </button>
      </div>
    </div>
  );
}

function normalizeMemorySettingsPatch(
  patch: Partial<ConversationSessionSettings>,
  current: ConversationSessionSettings,
): Partial<ConversationSessionSettings> {
  return {
    ...patch,
    memory_context_token_trigger_threshold: positiveInteger(
      patch.memory_context_token_trigger_threshold
        ?? current.memory_context_token_trigger_threshold,
    ),
    memory_raw_context_token_reserve: nonNegativeInteger(
      patch.memory_raw_context_token_reserve
        ?? current.memory_raw_context_token_reserve,
    ),
  };
}

function positiveInteger(value: number): number {
  return Math.max(Math.round(value), 1);
}

function nonNegativeInteger(value: number): number {
  return Math.max(Math.round(value), 0);
}

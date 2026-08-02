import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import { ChatMemoryManagementDashboard } from "./ChatMemoryManagementDashboard";
import { SettingsToggle } from "./ChatSettingControls";

export function ChatGlobalMemoryPanel({
  onChange,
  projectId,
  settings,
}: {
  onChange: (patch: Partial<ConversationSessionSettings>) => void;
  projectId: string | null;
  settings: ConversationSessionSettings;
}) {
  const { t } = useI18n();

  return (
    <div className="ai-panel__settings">
      <div className="ai-panel__setting-group">
        <span className="ai-panel__setting-group-title">
          {t("aiPanel.globalMemorySettings.memoryReceiving")}
        </span>
        <SettingsToggle
          checked={settings.global_memory_enabled}
          label={t("aiPanel.globalMemorySettings.receiveGlobalMemory")}
          onChange={(checked) => onChange({ global_memory_enabled: checked })}
        />
        <SettingsToggle
          checked={settings.project_memory_enabled}
          label={t("aiPanel.globalMemorySettings.receiveProjectMemory")}
          onChange={(checked) => onChange({ project_memory_enabled: checked })}
        />
      </div>

      <div className="ai-panel__setting-group">
        <span className="ai-panel__setting-group-title">
          {t("aiPanel.globalMemorySettings.memoryExtraction")}
        </span>
        <SettingsToggle
          checked={settings.global_memory_extraction_enabled}
          label={t("aiPanel.globalMemorySettings.extractGlobalMemory")}
          onChange={(checked) => onChange({
            global_memory_extraction_enabled: checked,
          })}
        />
        <SettingsToggle
          checked={settings.project_memory_extraction_enabled}
          label={t("aiPanel.globalMemorySettings.extractProjectMemory")}
          onChange={(checked) => onChange({
            project_memory_extraction_enabled: checked,
          })}
        />
      </div>

      <ChatMemoryManagementDashboard projectId={projectId} />
    </div>
  );
}

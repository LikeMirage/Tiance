import { ArrowClockwise } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import { subscribeToolCatalogChanges } from "../../../entities/tool/model/toolCatalogEvents";
import { useI18n } from "../../../shared/i18n";
import {
  getToolSummaries,
  type ToolSummary,
} from "../../../services/tools/getToolSummaries";
import { SettingsIntegerInput, SettingsToggle } from "./ChatSettingControls";

type Props = {
  onChange: (patch: Partial<ConversationSessionSettings>) => void;
  settings: ConversationSessionSettings;
};

export function ChatToolSettingsPanel({ onChange, settings }: Props) {
  const { t } = useI18n();
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let disposed = false;
    setIsLoading(true);
    setErrorMessage(null);
    void getToolSummaries()
      .then((response) => {
        if (disposed) return;
        setTools(response.items);
      })
      .catch(() => {
        if (disposed) return;
        setErrorMessage(t("aiPanel.toolSettings.loadFailed"));
      })
      .finally(() => {
        if (!disposed) {
          setIsLoading(false);
        }
      });
    return () => {
      disposed = true;
    };
  }, [refreshKey, t]);

  useEffect(() =>
    subscribeToolCatalogChanges(() => {
      setRefreshKey((value) => value + 1);
    }),
  []);

  const toolNames = useMemo(() => tools.map((tool) => tool.name), [tools]);
  const enabledNames = useMemo(() => {
    if (settings.enabled_tool_names === null) {
      return new Set(toolNames);
    }
    const visibleNames = new Set(toolNames);
    return new Set(settings.enabled_tool_names.filter((name) => visibleNames.has(name)));
  }, [settings.enabled_tool_names, toolNames]);

  const toggleTool = (toolName: string, checked: boolean) => {
    const next = new Set(settings.enabled_tool_names === null ? toolNames : settings.enabled_tool_names);
    if (checked) {
      next.add(toolName);
    } else {
      next.delete(toolName);
    }
    const visibleToolNames = new Set(toolNames);
    const hiddenSelectedNames = Array.from(next).filter((name) => !visibleToolNames.has(name));
    onChange({
      enabled_tool_names: [
        ...toolNames.filter((name) => next.has(name)),
        ...hiddenSelectedNames,
      ],
    });
  };

  return (
    <div className="ai-panel__settings">
      <div className="ai-panel__setting-group">
        <div className="ai-panel__tool-settings-heading">
          <span className="ai-panel__setting-group-title">{t("aiPanel.toolSettings.title")}</span>
          <button
            aria-label={t("aiPanel.toolSettings.refresh")}
            className="ai-panel__tool-settings-refresh"
            disabled={isLoading}
            title={t("aiPanel.toolSettings.refresh")}
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
          </button>
        </div>
      </div>
      <SettingsToggle
        checked={settings.tools_enabled}
        label={t("aiPanel.toolSettings.toolsEnabled")}
        onChange={(checked) => onChange({ tools_enabled: checked })}
      />
      <SettingsIntegerInput
        disabled={!settings.tools_enabled}
        label={t("aiPanel.toolSettings.maxToolCalls")}
        min={1}
        value={settings.max_tool_calls}
        onCommit={(value) => onChange({ max_tool_calls: value })}
      />

      {isLoading ? (
        <p className="ai-panel__tool-settings-empty">{t("aiPanel.toolSettings.loading")}</p>
      ) : errorMessage ? (
        <p className="ai-panel__tool-settings-error">{errorMessage}</p>
      ) : tools.length === 0 ? (
        <p className="ai-panel__tool-settings-empty">{t("aiPanel.toolSettings.empty")}</p>
      ) : (
        <div className="ai-panel__tool-settings-list">
          {tools.map((tool) => (
            <ToolSettingRow
              key={tool.name}
              checked={enabledNames.has(tool.name)}
              disabled={!settings.tools_enabled}
              tool={tool}
              noDescriptionLabel={t("aiPanel.toolSettings.noDescription")}
              onChange={(checked) => toggleTool(tool.name, checked)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolSettingRow({
  checked,
  disabled,
  noDescriptionLabel,
  onChange,
  tool,
}: {
  checked: boolean;
  disabled: boolean;
  noDescriptionLabel: string;
  onChange: (checked: boolean) => void;
  tool: ToolSummary;
}) {
  const { t } = useI18n();

  return (
    <div className="ai-panel__tool-setting-row">
      <span className="ai-panel__tool-setting-main">
        <span className="ai-panel__tool-setting-head">
          <span className="ai-panel__tool-setting-title">{tool.display_name || tool.name}</span>
          <span className="ai-panel__tool-setting-name">{tool.name}</span>
        </span>
        <span className="ai-panel__tool-setting-description">
          {tool.description || noDescriptionLabel}
        </span>
        <span className="ai-panel__tool-setting-meta">{tool.category}</span>
      </span>
      <button
        aria-label={checked ? t("aiPanel.toolSettings.disableTool") : t("aiPanel.toolSettings.enableTool")}
        aria-pressed={checked}
        className={
          checked
            ? "ai-panel__tool-toggle ai-panel__tool-toggle--on"
            : "ai-panel__tool-toggle"
        }
        disabled={disabled}
        type="button"
        onClick={() => onChange(!checked)}
      >
        <i aria-hidden="true" />
      </button>
    </div>
  );
}

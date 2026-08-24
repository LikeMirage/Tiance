import { useMemo, useState } from "react";

import type { ToolSummary } from "../../../services/tools/getToolSummaries";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { RoleConfigurationEditor } from "../model/useRoleConfigurationEditor";
import { RoleField, RoleNumberInput, RoleSection, RoleToggle } from "./RoleConfigurationFields";

export function RoleConfigurationToolsPanel({
  editor,
  tools,
  toolsError,
}: {
  editor: RoleConfigurationEditor;
  tools: ToolSummary[];
  toolsError: string | null;
}) {
  const [query, setQuery] = useState("");
  const configuration = editor.configuration?.tools;
  const normalizedQuery = query.trim().toLowerCase();
  const filteredTools = useMemo(() => {
    if (!normalizedQuery) return tools;
    return tools.filter((tool) =>
      `${tool.display_name} ${tool.name} ${tool.description} ${tool.category}`
        .toLowerCase()
        .includes(normalizedQuery)
    );
  }, [normalizedQuery, tools]);
  if (!configuration) return null;

  const availableNames = tools.map((tool) => tool.name);
  const enabledNames = new Set(
    configuration.enabled_tool_names === null
      ? availableNames
      : configuration.enabled_tool_names,
  );
  const unavailableNames = (configuration.enabled_tool_names ?? []).filter(
    (name) => !availableNames.includes(name),
  );
  const updateEnabledNames = (next: Set<string>) => {
    editor.updateSection("tools", {
      ...configuration,
      enabled_tool_names: [
        ...availableNames.filter((name) => next.has(name)),
        ...unavailableNames.filter((name) => next.has(name)),
      ],
    });
  };

  return (
    <div className="role-dashboard__panel-grid">
      <RoleSection title="工具权限" description="控制角色是否可以调用工具以及单轮调用上限。">
        <div className="role-dashboard__permission-grid">
          <RoleToggle
            checked={configuration.tools_enabled}
            label="工具总开关"
            onChange={(value) => editor.updateSection("tools", {
              ...configuration,
              tools_enabled: value,
            })}
          />
          <RoleField label="最大工具调用次数">
            <RoleNumberInput
              min={1}
              value={configuration.max_tool_calls}
              onCommit={(value) => editor.updateSection("tools", {
                ...configuration,
                max_tool_calls: value ?? 1,
              })}
            />
          </RoleField>
          <RoleField label="工具授权方式">
            <OptionSelect
              ariaLabel="工具授权方式"
              className="role-dashboard__select"
              disabled={!configuration.tools_enabled}
              floating
              options={[
                { label: "按工具权限配置", value: "follow_tool_policy" },
                { label: "自动允许询问项", value: "auto_allow_ask" },
              ]}
              showSelectedOption
              value={configuration.tool_approval_mode}
              onChange={(value) => editor.updateSection("tools", {
                ...configuration,
                tool_approval_mode: value,
              })}
            />
          </RoleField>
        </div>
      </RoleSection>

      <RoleSection
        className="role-dashboard__section--wide"
        title="启用工具"
        description="为角色选择可以使用的具体工具，修改会写入 tools.json。"
      >
        <div className="role-dashboard__tool-toolbar">
          <input
            aria-label="搜索工具"
            className="role-dashboard__input"
            placeholder="搜索工具名称或说明"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <span>{filteredTools.length} 个工具</span>
          <button
            type="button"
            onClick={() => updateEnabledNames(new Set([
              ...availableNames,
              ...unavailableNames,
            ]))}
          >
            全选
          </button>
          <button type="button" onClick={() => updateEnabledNames(new Set())}>
            清空
          </button>
        </div>
        {toolsError ? (
          <p className="role-dashboard__notice role-dashboard__notice--error">
            {toolsError}
          </p>
        ) : tools.length === 0 ? (
          <p className="role-dashboard__notice">暂无可选工具。</p>
        ) : filteredTools.length === 0 ? (
          <p className="role-dashboard__notice role-dashboard__notice--inside">
            没有匹配的工具。
          </p>
        ) : (
          <div className="role-dashboard__tool-list">
            {filteredTools.map((tool) => (
              <button
                key={tool.name}
                aria-pressed={enabledNames.has(tool.name)}
                className={
                  enabledNames.has(tool.name)
                    ? "role-dashboard__tool role-dashboard__tool--enabled"
                    : "role-dashboard__tool"
                }
                disabled={!configuration.tools_enabled}
                type="button"
                onClick={() => {
                  const next = new Set(enabledNames);
                  if (next.has(tool.name)) next.delete(tool.name);
                  else next.add(tool.name);
                  updateEnabledNames(next);
                }}
              >
                <span>
                  <strong>{tool.display_name || tool.name}</strong>
                  <small>{tool.name}</small>
                </span>
                <p>{tool.description || "暂无说明。"}</p>
                <i aria-hidden="true" />
              </button>
            ))}
          </div>
        )}
        {unavailableNames.length > 0 ? (
          <div className="role-dashboard__unavailable-tools">
            <strong>已配置但当前不可用</strong>
            <p>{unavailableNames.join("、")}</p>
          </div>
        ) : null}
      </RoleSection>
    </div>
  );
}

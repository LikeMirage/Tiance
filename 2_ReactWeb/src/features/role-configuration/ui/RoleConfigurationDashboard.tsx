import { useState } from "react";

import type { RoleConfigurationEditor } from "../model/useRoleConfigurationEditor";
import { useRoleConfigurationCatalogs } from "../model/useRoleConfigurationCatalogs";
import { RoleConfigurationBasicPanel } from "./RoleConfigurationBasicPanel";
import {
  RoleMemoryPanel,
  RolePromptPanel,
  RoleResponseContextPanel,
} from "./RoleConfigurationBehaviorPanels";
import { RoleConfigurationToolsPanel } from "./RoleConfigurationToolsPanel";
import "./role-configuration-dashboard.css";

type DashboardPanel = "basic" | "prompt" | "behavior" | "memory" | "tools";

const PANELS: Array<{ id: DashboardPanel; label: string }> = [
  { id: "basic", label: "基础设置" },
  { id: "prompt", label: "系统提示词" },
  { id: "behavior", label: "回复与上下文" },
  { id: "memory", label: "记忆" },
  { id: "tools", label: "工具" },
];

export function RoleConfigurationDashboard({
  editor,
  projectName,
}: {
  editor: RoleConfigurationEditor;
  projectName: string;
}) {
  const [activePanel, setActivePanel] = useState<DashboardPanel>("basic");
  const catalogs = useRoleConfigurationCatalogs();

  if (editor.state === "loading" || editor.state === "idle") {
    return <div className="role-dashboard__state">正在读取角色配置……</div>;
  }

  if (editor.state === "error" || !editor.configuration) {
    return (
      <div className="role-dashboard__state role-dashboard__state--error">
        <strong>角色配置读取失败</strong>
        <p>{editor.loadError ?? "无法读取角色配置。"}</p>
        <button type="button" onClick={editor.reload}>重试</button>
      </div>
    );
  }

  return (
    <article className="role-dashboard">
      <header className="role-dashboard__header">
        <h1>{projectName}</h1>
      </header>
      {editor.saveError ? (
        <p className="role-dashboard__notice role-dashboard__notice--error">
          保存失败：{editor.saveError}
        </p>
      ) : null}
      <nav className="role-dashboard__tabs" aria-label="角色配置分区">
        {PANELS.map((panel) => (
          <button
            key={panel.id}
            aria-current={activePanel === panel.id ? "page" : undefined}
            className={activePanel === panel.id ? "role-dashboard__tab role-dashboard__tab--active" : "role-dashboard__tab"}
            type="button"
            onClick={() => setActivePanel(panel.id)}
          >
            {panel.label}
          </button>
        ))}
      </nav>
      <div className="role-dashboard__body">
        <div className="role-dashboard__content">
          {activePanel === "basic" ? (
            <RoleConfigurationBasicPanel
              editor={editor}
              models={catalogs.models}
              modelsError={catalogs.modelsError}
              modelsLoading={catalogs.modelsLoading}
            />
          ) : null}
          {activePanel === "prompt" ? <RolePromptPanel editor={editor} /> : null}
          {activePanel === "behavior" ? <RoleResponseContextPanel editor={editor} /> : null}
          {activePanel === "memory" ? <RoleMemoryPanel editor={editor} /> : null}
          {activePanel === "tools" ? (
            <RoleConfigurationToolsPanel
              editor={editor}
              tools={catalogs.tools}
              toolsError={catalogs.toolsError}
            />
          ) : null}
        </div>
      </div>
    </article>
  );
}

import { useEffect, useId, useMemo, useRef, useState } from "react";

import {
  getToolParameterPermissionOption,
  TOOL_PERMISSION_POLICY_DEFINITIONS,
  type ToolPermissionDecision,
  type ToolPermissionPolicy,
  type ToolPermissionPolicyDefinition,
} from "../../../entities/tool/model/toolPermissions";
import {
  formatToolPermissionDashboardContent,
  parseToolPermissionDashboardContent,
} from "../model/toolPermissionDashboardModel";
import "./tool-permission-dashboard.css";

type ToolPermissionDashboardProps = {
  content: string;
  isDirty: boolean;
  onChange: (content: string) => void;
  onSave: (content: string) => Promise<boolean>;
  saveError: string | null;
  saveState: "idle" | "saving" | "saved" | "error";
};

const DECISIONS: Array<{ label: string; value: ToolPermissionDecision }> = [
  { value: "deny", label: "禁止" },
  { value: "ask", label: "询问" },
  { value: "allow", label: "允许" },
];

export function ToolPermissionDashboard({
  content,
  isDirty,
  onChange,
  onSave,
  saveError,
  saveState,
}: ToolPermissionDashboardProps) {
  const parsed = parseToolPermissionDashboardContent(content);
  const pendingSaveRef = useRef(false);

  useEffect(() => {
    if (!parsed.ok || !isDirty || saveState === "saving" || !pendingSaveRef.current) {
      return;
    }
    const snapshot = content;
    const timer = window.setTimeout(() => {
      pendingSaveRef.current = false;
      void onSave(snapshot).catch(() => undefined);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [content, isDirty, onSave, parsed.ok, saveState]);

  const categories = useMemo(() => groupPermissionDefinitions(), []);

  if (!parsed.ok) {
    return (
      <article className="tool-permission-dashboard tool-permission-dashboard--error">
        <h1>权限配置无法读取</h1>
        <p>{parsed.error}</p>
        {saveError ? <p>{saveError}</p> : null}
      </article>
    );
  }

  const { permissionParameters, permissions, registrationName } = parsed.data;
  const updatePermissions = (nextPermissions: ToolPermissionPolicy) => {
    pendingSaveRef.current = true;
    onChange(formatToolPermissionDashboardContent(content, nextPermissions));
  };

  return (
    <article className="tool-permission-dashboard">
      <header className="tool-permission-dashboard__header">
        <div>
          <h1>{registrationName || "未命名工具"} · 权限配置</h1>
          <p>配置文件仅记录权限处理策略，当前不会拦截或改变工具调用。</p>
        </div>
        <SaveState state={saveState} error={saveError} />
      </header>

      <section className="tool-permission-dashboard__fallback">
        <div>
          <h2>缺失配置的处理方式</h2>
          <p>新增权限点或缺少范围配置时使用，并明确保存到 permissions.json。</p>
        </div>
        <DecisionSelector
          ariaLabel="缺失配置的处理方式"
          value={permissions.fallback}
          onChange={(decision) => updatePermissions({
            ...permissions,
            fallback: decision,
          })}
        />
      </section>

      {categories.map((category) => (
        <section className="tool-permission-dashboard__category" key={category.id}>
          <h2>{category.label}</h2>
          <div className="tool-permission-dashboard__cards">
            {category.definitions.map((definition) => (
              <PermissionPolicyCard
                definition={definition}
                key={definition.permissionType}
                parameters={permissionParameters.get(definition.permissionType) ?? []}
                policy={permissions.policies[definition.permissionType]}
                onChange={(scope, decision) => updatePermissions({
                  ...permissions,
                  policies: {
                    ...permissions.policies,
                    [definition.permissionType]: {
                      ...permissions.policies[definition.permissionType],
                      [scope]: decision,
                    },
                  },
                })}
              />
            ))}
            {category.id === "general" ? (
              <NoCheckPermissionCard parameters={permissionParameters.get("none") ?? []} />
            ) : null}
          </div>
        </section>
      ))}
    </article>
  );
}

function PermissionPolicyCard({
  definition,
  parameters,
  policy,
  onChange,
}: {
  definition: ToolPermissionPolicyDefinition;
  parameters: string[];
  policy: Record<string, ToolPermissionDecision>;
  onChange: (scope: string, decision: ToolPermissionDecision) => void;
}) {
  return (
    <article className="tool-permission-dashboard__card">
      <PermissionCardHeader
        description={definition.description}
        parameters={parameters}
        title={definition.label}
      />
      <div className="tool-permission-dashboard__table-wrap">
        <table className="tool-permission-dashboard__table">
          <thead>
            <tr>
              <th>适用范围</th>
              {DECISIONS.map((decision) => <th key={decision.value}>{decision.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {definition.scopes.map((scope) => (
              <tr key={scope.id}>
                <th>{scope.label}</th>
                {DECISIONS.map((decision) => (
                  <td key={decision.value}>
                    <label title={`${definition.label} · ${scope.label} · ${decision.label}`}>
                      <input
                        checked={policy[scope.id] === decision.value}
                        name={`${definition.permissionType}:${scope.id}`}
                        type="radio"
                        value={decision.value}
                        onChange={() => onChange(scope.id, decision.value)}
                      />
                      <span aria-hidden="true" />
                    </label>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function NoCheckPermissionCard({ parameters }: { parameters: string[] }) {
  const option = getToolParameterPermissionOption("none");
  return (
    <article className="tool-permission-dashboard__card tool-permission-dashboard__card--no-check">
      <PermissionCardHeader
        description={option.description}
        parameters={parameters}
        title={option.label}
      />
      <p className="tool-permission-dashboard__no-check-note">这类参数不进入权限策略判断，因此没有配置表。</p>
    </article>
  );
}

function PermissionCardHeader({
  description,
  parameters,
  title,
}: {
  description: string;
  parameters: string[];
  title: string;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const panelId = useId();

  return (
    <>
      <header>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        {parameters.length > 0 ? (
          <button
            aria-controls={panelId}
            aria-expanded={isExpanded}
            className="tool-permission-dashboard__parameter-toggle"
            type="button"
            onClick={() => setIsExpanded((current) => !current)}
          >
            参数 {parameters.length}
            <span
              aria-hidden="true"
              className={isExpanded ? "is-expanded" : ""}
            >
              ›
            </span>
          </button>
        ) : (
          <span className="tool-permission-dashboard__unused">当前工具未使用</span>
        )}
      </header>
      {isExpanded ? (
        <div
          className="tool-permission-dashboard__parameter-panel"
          id={panelId}
        >
          <span>使用此权限的参数</span>
          <div className="tool-permission-dashboard__parameter-list">
            {parameters.map((parameter) => <code key={parameter}>{parameter}</code>)}
          </div>
        </div>
      ) : null}
    </>
  );
}

function DecisionSelector({
  ariaLabel,
  value,
  onChange,
}: {
  ariaLabel: string;
  value: ToolPermissionDecision;
  onChange: (value: ToolPermissionDecision) => void;
}) {
  return (
    <div className="tool-permission-dashboard__decision-selector" aria-label={ariaLabel} role="group">
      {DECISIONS.map((decision) => (
        <button
          className={value === decision.value ? "is-active" : ""}
          key={decision.value}
          type="button"
          onClick={() => onChange(decision.value)}
        >
          {decision.label}
        </button>
      ))}
    </div>
  );
}

function SaveState({
  error,
  state,
}: {
  error: string | null;
  state: ToolPermissionDashboardProps["saveState"];
}) {
  if (state === "saving") return <span className="tool-permission-dashboard__save-state">保存中…</span>;
  if (state === "error") {
    return <span className="tool-permission-dashboard__save-state is-error">{error || "保存失败"}</span>;
  }
  if (state === "saved") return <span className="tool-permission-dashboard__save-state">已保存</span>;
  return null;
}

function groupPermissionDefinitions() {
  const groups = new Map<string, {
    definitions: ToolPermissionPolicyDefinition[];
    id: string;
    label: string;
  }>();
  for (const definition of TOOL_PERMISSION_POLICY_DEFINITIONS) {
    const current = groups.get(definition.categoryId) ?? {
      id: definition.categoryId,
      label: definition.categoryLabel,
      definitions: [],
    };
    current.definitions.push(definition);
    groups.set(definition.categoryId, current);
  }
  return Array.from(groups.values());
}

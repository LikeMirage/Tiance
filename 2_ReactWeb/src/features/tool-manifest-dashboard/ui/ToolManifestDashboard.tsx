import { useState } from "react";
import type { CSSProperties } from "react";

import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import {
  asRequiredSet,
  asString,
  asStringArray,
  parseToolManifest,
} from "../model/toolManifest";
import type {
  JsonObject,
  ToolManifestDashboardView,
} from "../model/toolManifestEditorTypes";
import { useToolManifestAutoSave } from "../model/useToolManifestAutoSave";
import {
  DashboardSection,
  Field,
  KeywordButtons,
  KeywordDialog,
} from "./ToolManifestFields";
import {
  getExamples,
  ToolManifestExamplesView,
} from "./ToolManifestExamplesView";
import { ToolManifestParametersSection } from "./ToolManifestParametersSection";
import "./tool-manifest-dashboard.css";

type ToolManifestDashboardProps = {
  content: string;
  entryCandidates?: string[];
  isDirty: boolean;
  onChange: (content: string) => void;
  onSave: (content: string) => Promise<boolean>;
  saveError: string | null;
  saveState: "idle" | "saving" | "saved" | "error";
  view?: ToolManifestDashboardView;
};

export function ToolManifestDashboard({
  content,
  entryCandidates = [],
  isDirty,
  onChange,
  onSave,
  saveError,
  saveState,
  view = "basics",
}: ToolManifestDashboardProps) {
  const parsed = parseToolManifest(content);
  const manifest = parsed.ok ? parsed.manifest : {};
  const keywords = getKeywords(manifest);
  const parameters = Object.entries(manifest.input_schema?.properties ?? {});
  const required = asRequiredSet(manifest.input_schema?.required);
  const inputCallRules = asString(manifest.input_schema?.description);
  const accentColor = "var(--color-accent)";
  const registrationName = getRegistrationName(manifest);
  const description = getDescription(manifest);
  const examples = getExamples(manifest.examples);
  const isDynamicLoadingEnabled = getDynamicLoadingEnabled(manifest);
  const isParallelExecutionEnabled = getParallelExecutionEnabled(manifest);
  const isToolEnabled = getToolEnabled(manifest);
  const runtimeEntry = asString(manifest.runtime?.entry);
  const runtimeEntryOptions = buildRuntimeEntryOptions(entryCandidates, runtimeEntry);
  const [isKeywordDialogOpen, setIsKeywordDialogOpen] = useState(false);
  const [expandedParameterNames, setExpandedParameterNames] = useState<Set<string>>(() => new Set());
  const markPendingAutoSave = useToolManifestAutoSave({
    canSave: parsed.ok,
    content,
    isDirty,
    onSave,
    saveState,
  });

  const updateManifest = (updater: (draft: JsonObject) => void) => {
    const current = parseEditableJsonObject(content);
    if (!current) return;
    updater(current);
    const nextContent = formatJson(current);
    if (nextContent === content) return;
    markPendingAutoSave();
    onChange(nextContent);
  };

  const handleRawJsonChange = (nextContent: string) => {
    if (nextContent === content) return;
    markPendingAutoSave();
    onChange(nextContent);
  };

  const setParameterExpanded = (name: string, isExpanded: boolean) => {
    setExpandedParameterNames((current) => {
      const next = new Set(current);
      if (isExpanded) {
        next.add(name);
      } else {
        next.delete(name);
      }
      return next;
    });
  };

  if (!parsed.ok) {
    return (
      <div className="tool-dashboard tool-dashboard--error">
        <section className="tool-dashboard__section tool-dashboard__section--wide">
          <h2>tool.json 格式错误</h2>
          {saveError ? <p>{saveError}</p> : null}
          <p>{parsed.error}</p>
        </section>
        <DashboardSection title="原始 JSON">
          <textarea
            className="tool-dashboard__raw-editor"
            spellCheck={false}
            value={content}
            onChange={(event) => handleRawJsonChange(event.target.value)}
          />
        </DashboardSection>
      </div>
    );
  }

  return (
    <article className="tool-dashboard" style={{ "--tool-dashboard-accent": accentColor } as CSSProperties}>
      <header className="tool-dashboard__header">
        <div>
          <h1>{registrationName || "未命名工具"}</h1>
        </div>
        <div className="tool-dashboard__header-actions">
          <button
            className={[
              "tool-dashboard__dynamic-toggle",
              isDynamicLoadingEnabled ? "tool-dashboard__dynamic-toggle--on" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            type="button"
            role="switch"
            aria-checked={isDynamicLoadingEnabled}
            onClick={() => updateManifest((draft) => {
              setDynamicLoadingEnabled(draft, !isDynamicLoadingEnabled);
            })}
          >
            <span>动态加载</span>
            <i aria-hidden="true" />
          </button>
          <button
            className={[
              "tool-dashboard__dynamic-toggle",
              isParallelExecutionEnabled ? "tool-dashboard__dynamic-toggle--on" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            type="button"
            role="switch"
            aria-checked={isParallelExecutionEnabled}
            onClick={() => updateManifest((draft) => {
              setParallelExecutionEnabled(draft, !isParallelExecutionEnabled);
            })}
          >
            <span>并发执行</span>
            <i aria-hidden="true" />
          </button>
          {view === "basics" ? (
            <button
              className={[
                "tool-dashboard__dynamic-toggle",
                isToolEnabled ? "tool-dashboard__dynamic-toggle--on" : "",
              ]
              .filter(Boolean)
              .join(" ")}
              type="button"
              role="switch"
              aria-checked={isToolEnabled}
              onClick={() => updateManifest((draft) => {
                setToolEnabled(draft, !isToolEnabled);
              })}
            >
              <span>启用</span>
              <i aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </header>
      {saveError ? <p className="tool-dashboard__save-error">保存失败：{saveError}</p> : null}

      {view === "basics" ? (
        <>
          <section className="tool-dashboard__form-grid">
            <Field label="注册名称">
              <input
                className="tool-dashboard__input"
                value={registrationName}
                onChange={(event) => updateManifest((draft) => { draft.registration_name = event.target.value; })}
              />
            </Field>
            <Field label="调用名称">
              <input
                className="tool-dashboard__input"
                value={asString(manifest.name)}
                onChange={(event) => updateManifest((draft) => {
                  draft.name = normalizeIdentifierInput(event.target.value);
                })}
              />
            </Field>
            <Field className="tool-dashboard__field--wide" label="摘要">
              <textarea
                className="tool-dashboard__textarea"
                rows={2}
                value={description}
                onChange={(event) => updateManifest((draft) => {
                  draft.description = event.target.value;
                })}
              />
            </Field>
            <Field className="tool-dashboard__field--wide" label="关键词">
              <KeywordButtons
                keywords={keywords}
                onAdd={() => setIsKeywordDialogOpen(true)}
                onRemove={(keyword) => updateManifest((draft) => {
                  draft.keywords = keywords.filter((item: string) => item !== keyword);
                })}
              />
            </Field>
          </section>

          {isKeywordDialogOpen ? (
            <KeywordDialog
              existingKeywords={keywords}
              onCancel={() => setIsKeywordDialogOpen(false)}
              onConfirm={(keyword) => {
                updateManifest((draft) => {
                  draft.keywords = [...keywords, keyword];
                });
                setIsKeywordDialogOpen(false);
              }}
            />
          ) : null}

          <ToolManifestParametersSection
            expandedParameterNames={expandedParameterNames}
            inputCallRules={inputCallRules}
            parameters={parameters}
            required={required}
            updateManifest={updateManifest}
            onParameterExpandedChange={setParameterExpanded}
          />

          <DashboardSection title="运行入口">
            <div className="tool-dashboard__compact-form">
              <Field label="类型">
                <input
                  className="tool-dashboard__input"
                  readOnly
                  value={asString(manifest.runtime?.type)}
                />
              </Field>
              <Field label="入口">
                <OptionSelect
                  ariaLabel="入口"
                  className="tool-dashboard__select"
                  disabled={runtimeEntryOptions.length === 0}
                  floating
                  options={runtimeEntryOptions}
                  placeholder={runtimeEntryOptions.length > 0 ? "选择入口文件" : "暂无可选入口文件"}
                  showSelectedOption
                  value={runtimeEntry}
                  onChange={(value) => updateManifest((draft) => {
                    const runtime = ensureObject(draft, "runtime");
                    runtime.entry = value;
                  })}
                />
              </Field>
              <Field label="超时秒数">
                <input
                  className="tool-dashboard__input"
                  min={1}
                  type="number"
                  value={Number(manifest.runtime?.timeout_seconds ?? 60)}
                  onChange={(event) => updateManifest((draft) => {
                    const runtime = ensureObject(draft, "runtime");
                    runtime.timeout_seconds = Number(event.target.value || 60);
                  })}
                />
              </Field>
            </div>
          </DashboardSection>
        </>
      ) : (
        <ToolManifestExamplesView
          examples={examples}
          updateManifest={updateManifest}
        />
      )}

    </article>
  );
}

function parseEditableJsonObject(content: string): JsonObject | null {
  try {
    const payload = JSON.parse(content) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return null;
    }
    return { ...(payload as JsonObject) };
  } catch {
    return null;
  }
}

function formatJson(payload: JsonObject) {
  return `${JSON.stringify(payload, null, 2)}\n`;
}

function toJsonObject(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : {};
}

function getRegistrationName(manifest: { registration_name?: unknown }) {
  return asString(manifest.registration_name);
}

function getDescription(manifest: { description?: unknown }) {
  return asString(manifest.description);
}

function getDynamicLoadingEnabled(manifest: { loading?: unknown }) {
  const loading = manifest.loading;
  if (!loading || typeof loading !== "object" || Array.isArray(loading)) {
    return true;
  }
  const payload = loading as JsonObject;
  return payload.dynamic !== false;
}

function setDynamicLoadingEnabled(
  draft: JsonObject,
  enabled: boolean,
) {
  const loading = ensureObject(draft, "loading");
  loading.dynamic = enabled;
  delete loading.sections;
}

function getParallelExecutionEnabled(manifest: { execution?: unknown }) {
  const execution = manifest.execution;
  if (!execution || typeof execution !== "object" || Array.isArray(execution)) {
    return false;
  }
  return (execution as JsonObject).parallel === true;
}

function setParallelExecutionEnabled(draft: JsonObject, enabled: boolean) {
  const execution = ensureObject(draft, "execution");
  execution.parallel = enabled;
}

function getToolEnabled(manifest: { state?: unknown }) {
  const state = manifest.state;
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    return true;
  }
  return (state as JsonObject).enabled !== false;
}

function setToolEnabled(draft: JsonObject, enabled: boolean) {
  const state = ensureObject(draft, "state");
  state.enabled = enabled;
}

function getKeywords(manifest: { keywords?: unknown }) {
  return asStringArray(manifest.keywords);
}

function ensureObject(target: JsonObject, key: string): JsonObject {
  const current = target[key];
  if (current && typeof current === "object" && !Array.isArray(current)) {
    return current as JsonObject;
  }
  const next: JsonObject = {};
  target[key] = next;
  return next;
}

function normalizeIdentifierInput(value: string) {
  return value.replace(/[^A-Za-z0-9_]/g, "");
}

function buildRuntimeEntryOptions(
  candidates: string[],
  currentEntry: string,
): Array<OptionSelectItem<string>> {
  const items: Array<OptionSelectItem<string>> = [];
  const usedValues = new Set<string>();

  const pushValue = (value: string) => {
    const normalized = value.trim();
    if (!normalized || usedValues.has(normalized)) return;
    usedValues.add(normalized);
    items.push({ label: normalized, value: normalized });
  };

  pushValue(currentEntry);
  for (const candidate of candidates) {
    pushValue(candidate);
  }

  return items;
}

import { useState } from "react";
import { CaretDown, CaretRight, Plus, Trash } from "@phosphor-icons/react";

import { asString, type ToolManifestExample } from "../model/toolManifest";
import type { JsonObject } from "../model/toolManifestEditorTypes";
import { ConfirmDialog, Field } from "./ToolManifestFields";

type EditableToolExample = {
  content: string;
  enabled: boolean;
  injectContent: boolean;
  title: string;
};

type ToolManifestExamplesViewProps = {
  examples: EditableToolExample[];
  updateManifest: (updater: (draft: JsonObject) => void) => void;
};

export function getExamples(value: unknown): EditableToolExample[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(normalizeToolExample)
    .filter((example): example is EditableToolExample => Boolean(example));
}

export function ToolManifestExamplesView({
  examples,
  updateManifest,
}: ToolManifestExamplesViewProps) {
  const [expandedExampleIndexes, setExpandedExampleIndexes] = useState<Set<number>>(() => new Set());
  const [deleteExampleIndex, setDeleteExampleIndex] = useState<number | null>(null);

  const setExampleExpanded = (index: number, isExpanded: boolean) => {
    setExpandedExampleIndexes((current) => {
      const next = new Set(current);
      if (isExpanded) {
        next.add(index);
      } else {
        next.delete(index);
      }
      return next;
    });
  };

  const handleAddExample = () => {
    const nextIndex = examples.length;
    updateManifest((draft) => {
      draft.examples = serializeToolExamples([
        ...getExamples(draft.examples),
        buildEmptyExample(),
      ]);
    });
    setExpandedExampleIndexes((current) => {
      const next = new Set(current);
      next.add(nextIndex);
      return next;
    });
  };

  return (
    <>
      <div className="tool-dashboard__examples-page">
        <div className="tool-dashboard__examples-toolbar">
          <button className="tool-dashboard__secondary-button" type="button" onClick={handleAddExample}>
            <Plus size={14} weight="bold" aria-hidden="true" />
            <span>新增场景</span>
          </button>
        </div>
        {examples.length > 0 ? (
          <div className="tool-dashboard__param-list">
            {examples.map((example, index) => (
              <EditableExampleItem
                example={example}
                index={index}
                isExpanded={expandedExampleIndexes.has(index)}
                key={index}
                onDelete={() => setDeleteExampleIndex(index)}
                onExpandedChange={(isExpanded) => setExampleExpanded(index, isExpanded)}
                onExampleChange={(updater) => updateManifest((draft) => updateToolExample(draft, index, updater))}
              />
            ))}
          </div>
        ) : (
          <p>暂无应用场景。</p>
        )}
      </div>

      {deleteExampleIndex !== null ? (
        <ConfirmDialog
          confirmLabel="删除"
          message="删除后会从 examples.json 中移除这个应用场景。"
          title="删除应用场景"
          onCancel={() => setDeleteExampleIndex(null)}
          onConfirm={() => {
            updateManifest((draft) => removeToolExample(draft, deleteExampleIndex));
            setDeleteExampleIndex(null);
          }}
        />
      ) : null}
    </>
  );
}

function EditableExampleItem({
  example,
  index,
  isExpanded,
  onDelete,
  onExampleChange,
  onExpandedChange,
}: {
  example: EditableToolExample;
  index: number;
  isExpanded: boolean;
  onDelete?: () => void;
  onExampleChange: (updater: (example: EditableToolExample) => void) => void;
  onExpandedChange: (isExpanded: boolean) => void;
}) {
  const title = example.title.trim() || `应用场景 ${index + 1}`;
  const contentPreview = getContentPreview(example.content);

  return (
    <div className={["tool-dashboard__param-card", isExpanded ? "tool-dashboard__param-card--expanded" : ""].filter(Boolean).join(" ")}>
      <div className="tool-dashboard__example-header">
        <button
          className="tool-dashboard__param-summary tool-dashboard__example-summary"
          type="button"
          aria-expanded={isExpanded}
          onClick={() => onExpandedChange(!isExpanded)}
        >
          <span className="tool-dashboard__param-caret" aria-hidden="true">
            {isExpanded ? <CaretDown size={14} weight="bold" /> : <CaretRight size={14} weight="bold" />}
          </span>
          <span className="tool-dashboard__param-summary-main">
            <strong>{title}</strong>
            <span>{contentPreview || "暂无内容。"}</span>
          </span>
          <span className="tool-dashboard__param-badges">
            <span>场景 {index + 1}</span>
          </span>
        </button>
        <div className="tool-dashboard__example-actions">
          <button
            className={[
              "tool-dashboard__dynamic-toggle",
              example.enabled ? "tool-dashboard__dynamic-toggle--on" : "",
            ].filter(Boolean).join(" ")}
            type="button"
            role="switch"
            aria-checked={example.enabled}
            onClick={() => onExampleChange((draft) => {
              draft.enabled = !draft.enabled;
            })}
          >
            <span>启用案例</span>
            <i aria-hidden="true" />
          </button>
          <button
            className={[
              "tool-dashboard__dynamic-toggle",
              example.injectContent ? "tool-dashboard__dynamic-toggle--on" : "",
            ].filter(Boolean).join(" ")}
            disabled={!example.enabled}
            type="button"
            role="switch"
            aria-checked={example.injectContent}
            onClick={() => onExampleChange((draft) => {
              draft.injectContent = !draft.injectContent;
            })}
          >
            <span>正文注入</span>
            <i aria-hidden="true" />
          </button>
          {onDelete ? (
            <button
              aria-label={`删除 ${title}`}
              className="tool-dashboard__example-delete-button"
              type="button"
              onClick={onDelete}
            >
              <Trash size={15} weight="bold" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>

      {isExpanded ? (
        <div className="tool-dashboard__param-panel">
          <div className="tool-dashboard__param-form">
            <Field label="标题">
              <input
                className="tool-dashboard__input"
                value={example.title}
                onChange={(event) => onExampleChange((draft) => {
                  draft.title = event.target.value;
                })}
              />
            </Field>
            <Field className="tool-dashboard__field--wide" label="场景内容">
              <textarea
                aria-label={`${title} 应用场景内容`}
                className="tool-dashboard__textarea tool-dashboard__scenario-textarea"
                spellCheck={false}
                value={example.content}
                onChange={(event) => onExampleChange((draft) => {
                  draft.content = event.target.value;
                })}
              />
            </Field>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function normalizeToolExample(value: unknown): EditableToolExample | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const payload = value as ToolManifestExample;
  return {
    title: asString(payload.title),
    content: asString(payload.content),
    enabled: typeof payload.enabled === "boolean" ? payload.enabled : true,
    injectContent: typeof payload.inject_content === "boolean" ? payload.inject_content : false,
  };
}

function buildEmptyExample(): EditableToolExample {
  return {
    title: "新应用场景",
    content: "",
    enabled: true,
    injectContent: false,
  };
}

function serializeToolExamples(examples: EditableToolExample[]) {
  return examples.map((example) => ({
    title: example.title,
    content: example.content,
    enabled: example.enabled,
    inject_content: example.injectContent,
  }));
}

function updateToolExample(
  draft: JsonObject,
  index: number,
  updater: (example: EditableToolExample) => void,
) {
  const examples = getExamples(draft.examples);
  const target = examples[index];
  if (!target) return;
  const next = { ...target };
  updater(next);
  examples[index] = next;
  draft.examples = serializeToolExamples(examples);
}

function removeToolExample(draft: JsonObject, index: number) {
  const examples = getExamples(draft.examples);
  examples.splice(index, 1);
  draft.examples = serializeToolExamples(examples);
}

function getContentPreview(content: string) {
  return content.trim().split(/\r?\n/).find((line) => line.trim())?.trim() ?? "";
}

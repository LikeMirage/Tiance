import { CaretDown, CaretRight } from "@phosphor-icons/react";

import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import {
  asString,
  type JsonSchemaProperty,
} from "../model/toolManifest";
import type { JsonObject } from "../model/toolManifestEditorTypes";
import {
  buildDefaultValueOptions,
  ensureObject,
  formatDefaultValue,
  formatOptionalNumber,
  getArrayItemType,
  getParameterOptions,
  parseDefaultValue,
  setArrayItemType,
  setInputParameterRequired,
  setOptionalNumberField,
  setOptionalStringField,
  setParameterOptions,
  updateInputParameterSchema,
  type ParameterOption,
} from "../model/toolManifestParameterSchema";
import {
  DashboardSection,
  Field,
  ReadonlyValue,
} from "./ToolManifestFields";

type ToolManifestParametersSectionProps = {
  expandedParameterNames: Set<string>;
  inputCallRules: string;
  onParameterExpandedChange: (name: string, isExpanded: boolean) => void;
  parameters: Array<[string, JsonSchemaProperty]>;
  required: Set<string>;
  updateManifest: (updater: (draft: JsonObject) => void) => void;
};

const FORMAT_OPTIONS: Array<OptionSelectItem<string>> = [
  { label: "无", value: "" },
  { label: "uri", value: "uri" },
  { label: "email", value: "email" },
  { label: "date", value: "date" },
  { label: "date-time", value: "date-time" },
  { label: "uuid", value: "uuid" },
  { label: "regex", value: "regex" },
];

const ARRAY_ITEM_TYPE_OPTIONS: Array<OptionSelectItem<string>> = [
  { label: "string", value: "string" },
  { label: "integer", value: "integer" },
  { label: "number", value: "number" },
  { label: "boolean", value: "boolean" },
  { label: "object", value: "object" },
];

export function ToolManifestParametersSection({
  expandedParameterNames,
  inputCallRules,
  onParameterExpandedChange,
  parameters,
  required,
  updateManifest,
}: ToolManifestParametersSectionProps) {
  return (
    <DashboardSection title="输入参数">
      <Field className="tool-dashboard__call-rules-field" label="参数规则">
        <textarea
          className="tool-dashboard__textarea"
          placeholder="例如：mode=search 时必须填写 query；建议先用 metadata 查看文件规模。"
          rows={2}
          value={inputCallRules}
          onChange={(event) => updateManifest((draft) => {
            const inputSchema = ensureObject(draft, "input_schema");
            const nextDescription = event.target.value;
            if (nextDescription) {
              inputSchema.description = nextDescription;
            } else {
              delete inputSchema.description;
            }
          })}
        />
      </Field>
      {parameters.length > 0 ? (
        <div className="tool-dashboard__param-list">
          {parameters.map(([name, schema]) => (
            <EditableParameterItem
              options={getParameterOptions(schema)}
              isExpanded={expandedParameterNames.has(name)}
              isRequired={required.has(name)}
              key={name}
              name={name}
              onExpandedChange={(isExpanded) => onParameterExpandedChange(name, isExpanded)}
              onRequiredChange={(nextRequired) => updateManifest((draft) =>
                setInputParameterRequired(draft, name, nextRequired),
              )}
              onSchemaChange={(updater) => updateManifest((draft) =>
                updateInputParameterSchema(draft, name, updater),
              )}
              schema={schema}
            />
          ))}
        </div>
      ) : (
        <p>暂无输入参数。</p>
      )}
    </DashboardSection>
  );
}

function ParameterOptionsEditor({
  onUpdate,
  options,
}: {
  onUpdate: (index: number, option: ParameterOption) => void;
  options: ParameterOption[];
}) {
  return (
    <div className="tool-dashboard__option-editor">
      <div className="tool-dashboard__option-row tool-dashboard__option-row--head">
        <span>值</span>
        <span>说明</span>
      </div>
      {options.length > 0 ? (
        options.map((option, index) => (
          <div className="tool-dashboard__option-row" key={getParameterOptionKey(option, index)}>
            <ReadonlyValue value={option.value || "未命名可选值"} />
            <div className="tool-dashboard__option-note">
              <input
                className="tool-dashboard__input"
                value={option.description}
                onChange={(event) => onUpdate(index, {
                  ...option,
                  description: event.target.value,
                })}
              />
            </div>
          </div>
        ))
      ) : (
        <p className="tool-dashboard__option-empty">暂无可选值。</p>
      )}
    </div>
  );
}

function getParameterOptionKey(option: ParameterOption, index: number) {
  return option.value ? `value:${option.value}` : `empty:${option.description}:${index}`;
}

function ParameterAdvancedFields({
  onSchemaChange,
  parameterType,
  schema,
}: {
  onSchemaChange: (updater: (schema: JsonObject) => void) => void;
  parameterType: string;
  schema: JsonSchemaProperty;
}) {
  if (parameterType === "string") {
    return (
      <div className="tool-dashboard__param-advanced tool-dashboard__field--wide">
        <span>字符串配置</span>
        <div className="tool-dashboard__param-advanced-grid">
          <Field label="最小长度">
            <input
              className="tool-dashboard__input"
              min={0}
              type="number"
              value={formatOptionalNumber(schema.minLength)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "minLength",
                event.target.value,
                { integer: true, minimum: 0 },
              ))}
            />
          </Field>
          <Field label="最大长度">
            <input
              className="tool-dashboard__input"
              min={0}
              type="number"
              value={formatOptionalNumber(schema.maxLength)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "maxLength",
                event.target.value,
                { integer: true, minimum: 0 },
              ))}
            />
          </Field>
          <Field label="格式">
            <OptionSelect
              ariaLabel="格式"
              className="tool-dashboard__select"
              floating
              options={FORMAT_OPTIONS}
              value={asString(schema.format)}
              onChange={(value) => onSchemaChange((draft) => setOptionalStringField(
                draft,
                "format",
                value,
              ))}
            />
          </Field>
        </div>
      </div>
    );
  }

  if (parameterType === "integer" || parameterType === "number") {
    const isInteger = parameterType === "integer";
    const minimumStep = isInteger ? 1 : 0.000001;
    return (
      <div className="tool-dashboard__param-advanced tool-dashboard__field--wide">
        <span>数字配置</span>
        <div className="tool-dashboard__param-advanced-grid">
          <Field label="最小值">
            <input
              className="tool-dashboard__input"
              type="number"
              value={formatOptionalNumber(schema.minimum)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "minimum",
                event.target.value,
                { integer: isInteger },
              ))}
            />
          </Field>
          <Field label="最大值">
            <input
              className="tool-dashboard__input"
              type="number"
              value={formatOptionalNumber(schema.maximum)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "maximum",
                event.target.value,
                { integer: isInteger },
              ))}
            />
          </Field>
          <Field label="步进">
            <input
              className="tool-dashboard__input"
              min={minimumStep}
              type="number"
              value={formatOptionalNumber(schema.multipleOf)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "multipleOf",
                event.target.value,
                { integer: isInteger, minimum: minimumStep },
              ))}
            />
          </Field>
        </div>
      </div>
    );
  }

  if (parameterType === "array") {
    return (
      <div className="tool-dashboard__param-advanced tool-dashboard__field--wide">
        <span>数组配置</span>
        <div className="tool-dashboard__param-advanced-grid">
          <Field label="元素类型">
            <OptionSelect
              ariaLabel="元素类型"
              className="tool-dashboard__select"
              floating
              options={ARRAY_ITEM_TYPE_OPTIONS}
              value={getArrayItemType(schema)}
              onChange={(value) => onSchemaChange((draft) => setArrayItemType(
                draft,
                value,
              ))}
            />
          </Field>
          <Field label="最少数量">
            <input
              className="tool-dashboard__input"
              min={0}
              type="number"
              value={formatOptionalNumber(schema.minItems)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "minItems",
                event.target.value,
                { integer: true, minimum: 0 },
              ))}
            />
          </Field>
          <Field label="最多数量">
            <input
              className="tool-dashboard__input"
              min={0}
              type="number"
              value={formatOptionalNumber(schema.maxItems)}
              onChange={(event) => onSchemaChange((draft) => setOptionalNumberField(
                draft,
                "maxItems",
                event.target.value,
                { integer: true, minimum: 0 },
              ))}
            />
          </Field>
          <Field label="重复值">
            <label className="tool-dashboard__param-required-toggle">
              <input
                checked={schema.uniqueItems === true}
                type="checkbox"
                onChange={(event) => onSchemaChange((draft) => {
                  if (event.target.checked) {
                    draft.uniqueItems = true;
                  } else {
                    delete draft.uniqueItems;
                  }
                })}
              />
              <span>不允许重复</span>
            </label>
          </Field>
        </div>
      </div>
    );
  }

  if (parameterType === "object") {
    return (
      <div className="tool-dashboard__param-advanced tool-dashboard__field--wide">
        <span>对象配置</span>
        <div className="tool-dashboard__param-advanced-grid">
          <Field label="额外字段">
            <label className="tool-dashboard__param-required-toggle">
              <input
                checked={schema.additionalProperties !== false}
                type="checkbox"
                onChange={(event) => onSchemaChange((draft) => {
                  if (event.target.checked) {
                    delete draft.additionalProperties;
                  } else {
                    draft.additionalProperties = false;
                  }
                })}
              />
              <span>允许额外字段</span>
            </label>
          </Field>
        </div>
      </div>
    );
  }

  return null;
}

function EditableParameterItem({
  isExpanded,
  isRequired,
  name,
  onExpandedChange,
  onRequiredChange,
  onSchemaChange,
  options,
  schema,
}: {
  isExpanded: boolean;
  isRequired: boolean;
  name: string;
  onExpandedChange: (isExpanded: boolean) => void;
  onRequiredChange: (isRequired: boolean) => void;
  onSchemaChange: (updater: (schema: JsonObject) => void) => void;
  options: ParameterOption[];
  schema: JsonSchemaProperty;
}) {
  const parameterType = asString(schema.type, "string");
  const description = asString(schema.description, asString(schema.title));
  const enumCount = options.length;
  const defaultValue = formatDefaultValue(schema.default);

  return (
    <div className={["tool-dashboard__param-card", isExpanded ? "tool-dashboard__param-card--expanded" : ""].filter(Boolean).join(" ")}>
      <button
        className="tool-dashboard__param-summary"
        type="button"
        aria-expanded={isExpanded}
        onClick={() => onExpandedChange(!isExpanded)}
      >
        <span className="tool-dashboard__param-caret" aria-hidden="true">
          {isExpanded ? <CaretDown size={14} weight="bold" /> : <CaretRight size={14} weight="bold" />}
        </span>
        <span className="tool-dashboard__param-summary-main">
          <strong>{name}</strong>
          <span>{description || "暂无说明。"}</span>
        </span>
        <span className="tool-dashboard__param-badges">
          <span>{parameterType}</span>
          {isRequired ? <strong>必填</strong> : <span>可选</span>}
          {enumCount > 0 ? <span>{enumCount} 个可选值</span> : null}
          {defaultValue ? <span>默认 {defaultValue}</span> : null}
        </span>
      </button>

      {isExpanded ? (
        <div className="tool-dashboard__param-panel">
          <div className="tool-dashboard__param-form">
            <Field label="参数名">
              <ReadonlyValue value={name} />
            </Field>
            <Field label="类型">
              <ReadonlyValue value={parameterType} />
            </Field>
            <Field label="是否必填">
              <label className="tool-dashboard__param-required-toggle">
                <input
                  checked={isRequired}
                  type="checkbox"
                  onChange={(event) => onRequiredChange(event.target.checked)}
                />
                <span>必填参数</span>
              </label>
            </Field>
            <Field label="默认值">
              {options.length > 0 ? (
                <OptionSelect
                  ariaLabel="默认值"
                  className="tool-dashboard__select"
                  floating
                  options={buildDefaultValueOptions(options, defaultValue)}
                  value={defaultValue}
                  onChange={(value) => onSchemaChange((draft) => {
                    const nextDefault = parseDefaultValue(value, asString(draft.type, parameterType));
                    if (nextDefault === undefined) {
                      delete draft.default;
                    } else {
                      draft.default = nextDefault;
                    }
                  })}
                />
              ) : (
                <input
                  className="tool-dashboard__input"
                  value={defaultValue}
                  onChange={(event) => onSchemaChange((draft) => {
                    const nextDefault = parseDefaultValue(event.target.value, asString(draft.type, parameterType));
                    if (nextDefault === undefined) {
                      delete draft.default;
                    } else {
                      draft.default = nextDefault;
                    }
                  })}
                />
              )}
            </Field>
            <Field className="tool-dashboard__field--wide" label="说明">
              <textarea
                className="tool-dashboard__textarea"
                rows={3}
                value={description}
                onChange={(event) => onSchemaChange((draft) => {
                  draft.description = event.target.value;
                })}
              />
            </Field>
            <ParameterAdvancedFields
              onSchemaChange={onSchemaChange}
              parameterType={parameterType}
              schema={schema}
            />
            <Field className="tool-dashboard__field--wide" label="可选值">
              <ParameterOptionsEditor
                options={options}
                onUpdate={(index, option) => onSchemaChange((draft) => setParameterOptions(
                  draft,
                  options.map((currentOption, itemIndex) => (
                    itemIndex === index ? option : currentOption
                  )),
                ))}
              />
            </Field>
          </div>
        </div>
      ) : null}
    </div>
  );
}

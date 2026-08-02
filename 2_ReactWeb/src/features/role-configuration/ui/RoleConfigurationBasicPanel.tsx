import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import type { LlmModelCatalogEntry } from "../../../entities/llm-provider/model/modelCatalog";
import {
  buildLlmModelPickerKey,
  getLlmModelPickerOptionKey,
  toUnavailableLlmModelPickerOption,
  type LlmModelPickerOption,
} from "../../llm-model-picker/model/llmModelPickerOption";
import { LlmModelPicker } from "../../llm-model-picker/ui/LlmModelPicker";
import type { RoleConfigurationEditor } from "../model/useRoleConfigurationEditor";
import { RoleField, RoleNumberInput, RoleSection } from "./RoleConfigurationFields";

const REASONING_OPTIONS: Array<OptionSelectItem<string>> = [
  { label: "默认", value: "default" },
  { label: "自动", value: "auto" },
  { label: "关闭", value: "off" },
  { label: "低", value: "low" },
  { label: "中", value: "medium" },
  { label: "高", value: "high" },
  { label: "最大", value: "max" },
];

export function RoleConfigurationBasicPanel({
  editor,
  models,
  modelsError,
  modelsLoading,
}: {
  editor: RoleConfigurationEditor;
  models: LlmModelCatalogEntry[];
  modelsError: string | null;
  modelsLoading: boolean;
}) {
  const configuration = editor.configuration;
  if (!configuration) return null;
  const { generation, model, profile } = configuration;
  const currentModelKey = buildLlmModelPickerKey(model.provider_id, model.model_id);
  const modelOptions = buildModelOptions(models, currentModelKey);
  const reasoningMode = model.reasoning_mode ?? "default";
  const reasoningOptions = REASONING_OPTIONS.some((option) => option.value === reasoningMode)
    ? REASONING_OPTIONS
    : [{ label: reasoningMode, value: reasoningMode }, ...REASONING_OPTIONS];

  return (
    <div className="role-dashboard__panel-grid role-dashboard__panel-grid--basic">
      <RoleSection
        className="role-dashboard__section--wide"
        title="角色资料"
        description="描述角色用途。"
      >
        <div className="role-dashboard__form-grid">
          <RoleField label="角色说明" wide>
            <textarea
              className="role-dashboard__textarea"
              rows={3}
              value={profile.description}
              onChange={(event) => editor.updateSection("profile", {
                ...profile,
                description: event.target.value,
              })}
            />
          </RoleField>
        </div>
      </RoleSection>

      <RoleSection title="模型" description="选择角色配置中记录的模型与推理模式。">
        <div className="role-dashboard__form-grid">
          <RoleField label="模型">
            <LlmModelPicker
              ariaLabel="角色模型"
              disabled={modelsLoading && modelOptions.length === 0}
              error={modelsError}
              loading={modelsLoading}
              options={modelOptions}
              placeholder={modelsLoading ? "模型加载中" : "选择模型"}
              value={currentModelKey}
              onChange={(_, option) => {
                if (!option) return;
                editor.updateSection("model", {
                  ...model,
                  provider_id: option.providerId,
                  model_id: option.modelId,
                });
              }}
            />
          </RoleField>
          <RoleField label="推理模式">
            <OptionSelect
              ariaLabel="角色推理模式"
              className="role-dashboard__select"
              floating
              options={reasoningOptions}
              showSelectedOption
              value={reasoningMode}
              onChange={(value) => editor.updateSection("model", {
                ...model,
                reasoning_mode: value,
              })}
            />
          </RoleField>
        </div>
      </RoleSection>

      <RoleSection title="生成参数" description="留空的采样参数由模型或供应商使用默认值。">
        <div className="role-dashboard__form-grid">
          <RoleField label="温度">
            <RoleNumberInput
              allowNull
              max={2}
              min={0}
              step={0.1}
              value={generation.temperature}
              onCommit={(value) => editor.updateSection("generation", {
                ...generation,
                temperature: value,
              })}
            />
          </RoleField>
          <RoleField label="Top P">
            <RoleNumberInput
              allowNull
              max={1}
              min={0}
              step={0.05}
              value={generation.top_p}
              onCommit={(value) => editor.updateSection("generation", {
                ...generation,
                top_p: value,
              })}
            />
          </RoleField>
          <RoleField label="最大输出长度">
            <RoleNumberInput
              min={1}
              value={generation.max_output_tokens}
              onCommit={(value) => editor.updateSection("generation", {
                ...generation,
                max_output_tokens: value ?? 1,
              })}
            />
          </RoleField>
        </div>
      </RoleSection>
    </div>
  );
}

function buildModelOptions(
  models: LlmModelCatalogEntry[],
  currentModelKey: string,
): LlmModelPickerOption[] {
  const options: LlmModelPickerOption[] = models.map((item) => ({
    capabilityTags: item.capability_tags,
    familyGroup: item.family_group,
    modelId: item.model_id,
    modelLabel: item.model_label || item.model_id,
    providerId: item.provider_id,
    providerLabel: item.provider_label || item.provider_id,
    source: item.source,
  }));
  if (
    currentModelKey !== ":" &&
    !options.some((option) => getLlmModelPickerOptionKey(option) === currentModelKey)
  ) {
    const unavailableOption = toUnavailableLlmModelPickerOption(currentModelKey);
    if (unavailableOption) options.unshift(unavailableOption);
  }
  return options;
}

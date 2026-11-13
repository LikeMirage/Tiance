import { LlmModelPicker } from "../../llm-model-picker/ui/LlmModelPicker";
import { toLlmModelPickerOption } from "../../llm-model-picker/model/llmModelPickerOption";
import { getModelKey } from "../model/useChatModelOptions";
import type { ChatComposerModelPickerState } from "./ChatComposerTypes";

export function ChatModelPicker({
  modelPicker, isOpen, onOpenChange, panelContainer,
}: {
  modelPicker: ChatComposerModelPickerState;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  panelContainer: HTMLElement | null;
}) {
  const activeModel = modelPicker.activeModel;
  const pickerOptions = modelPicker.models.map(toLlmModelPickerOption);
  const placeholder =
    modelPicker.activeSession?.model_id ??
    (modelPicker.isLoading ? "模型加载中" : "选择模型");
  const value = activeModel ? getModelKey(activeModel) : "";

  return (
    <LlmModelPicker
      ariaLabel="选择会话模型"
      disabled={modelPicker.isDisabled}
      error={modelPicker.loadError}
      loading={modelPicker.isLoading}
      open={isOpen}
      panelContainer={panelContainer}
      options={pickerOptions}
      placement="above"
      placeholder={placeholder}
      value={value}
      variant="inline"
      onChange={(_, option) => {
        if (!option) {
          return;
        }
        modelPicker.onSelect({
          capabilityTags: option.capabilityTags ?? [],
          familyGroup: option.familyGroup ?? "",
          modelId: option.modelId,
          modelLabel: option.modelLabel,
          providerId: option.providerId,
          providerLabel: option.providerLabel,
          source: option.source ?? "",
        });
      }}
      onOpen={() => {
        void modelPicker.onReload();
      }}
      onOpenChange={onOpenChange}
    />
  );
}

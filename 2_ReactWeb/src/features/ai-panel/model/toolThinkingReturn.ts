import type { ChatModelOption } from "./chatModelOption";

export type ToolThinkingReturnModelInfo = {
  modelId?: string | null;
  modelLabel?: string | null;
  providerId?: string | null;
  providerLabel?: string | null;
};

export function shouldAutoEnableToolThinkingReturn(
  model: ToolThinkingReturnModelInfo,
): boolean {
  return [
    model.providerId,
    model.providerLabel,
    model.modelId,
    model.modelLabel,
  ].some((value) => value?.toLowerCase().includes("deepseek"));
}

export function resolveToolThinkingReturnModelInfo({
  modelId,
  models,
  providerId,
  selectedModel,
}: {
  modelId: string | null;
  models?: ChatModelOption[];
  providerId: string | null;
  selectedModel?: ChatModelOption | null;
}): ToolThinkingReturnModelInfo {
  const matchedModel = models?.find((model) =>
    model.providerId === providerId && model.modelId === modelId,
  ) ?? (
    selectedModel?.providerId === providerId && selectedModel.modelId === modelId
      ? selectedModel
      : null
  );

  return {
    modelId,
    modelLabel: matchedModel?.modelLabel ?? null,
    providerId,
    providerLabel: matchedModel?.providerLabel ?? null,
  };
}

import { withReasoningOffOption } from "../../../entities/llm-runtime/model/reasoningModes";
import { getModelCatalog } from "../../../services/llm/getModelCatalog";
import { getRuntimeCapabilities } from "../../../services/llm/getRuntimeCapabilities";
import { toChatModelOption } from "../../ai-panel/model/chatModelOption";
import {
  filterLlmModelProviderGroups,
  groupLlmModelsByProvider,
} from "../../llm-model-picker/model/llmModelCatalogQuery";

export async function queryConversationModels(input: {
  modelId?: string | null;
  providerId?: string | null;
  query?: string | null;
}) {
  if (input.modelId && !input.providerId) {
    throw new Error("精确查询模型时必须同时提供 provider_id。");
  }
  if (input.modelId && input.query?.trim()) {
    throw new Error("精确查询模型时不能同时传 query。");
  }
  const catalog = await getModelCatalog({ kind: "chat" });
  const allModels = catalog.items.map(toChatModelOption);
  const allGroups = groupLlmModelsByProvider(allModels);
  const providerGroups = input.providerId
    ? allGroups.filter((group) => group.providerId === input.providerId)
    : allGroups;
  if (input.providerId && providerGroups.length === 0) {
    throw new Error("指定供应商不在聊天面板可用供应商列表中。");
  }
  const filteredGroups = filterLlmModelProviderGroups(providerGroups, input.query ?? "");
  const filteredModels = filteredGroups.flatMap((group) => group.models);
  const exactModel = input.modelId
    ? providerGroups.flatMap((group) => group.models).find((model) => model.modelId === input.modelId)
    : null;
  if (input.modelId && !exactModel) {
    throw new Error("指定模型不在该供应商的聊天模型列表中。");
  }
  const capabilities = exactModel
    ? await getRuntimeCapabilities(exactModel.providerId, exactModel.modelId)
    : null;

  return {
    count: exactModel ? 1 : filteredModels.length,
    providers: filteredGroups.map((group) => ({
      provider_id: group.providerId,
      provider_label: group.providerLabel,
      model_count: group.models.length,
      total_model_count: allGroups.find((item) => item.providerId === group.providerId)?.models.length ?? 0,
    })),
    models: (exactModel ? [exactModel] : filteredModels).map(serializeModel),
    ...(capabilities ? {
      runtime_capabilities: {
        provider_profile_id: capabilities.providerProfileId,
        input_modalities: capabilities.inputModalities,
        output_formats: capabilities.outputFormats,
        reasoning: {
          supported: capabilities.reasoning.supported,
          modes: capabilities.reasoning.supported
            ? withReasoningOffOption(capabilities.reasoning.modes)
            : [],
        },
        sampling: {
          supported: capabilities.sampling.supported,
          parameters: capabilities.sampling.parameters.map((parameter) => {
            switch (parameter) {
              case "topP": return "top_p";
              case "presencePenalty": return "presence_penalty";
              case "frequencyPenalty": return "frequency_penalty";
              default: return parameter;
            }
          }),
          disabled_when_reasoning: capabilities.sampling.disabledWhenReasoning,
          disabled_reason_when_reasoning:
            capabilities.sampling.disabledReasonWhenReasoning ?? null,
        },
        max_output_tokens: capabilities.maxOutputTokens,
        tool_calling: capabilities.toolCalling,
      },
    } : {}),
  };
}

function serializeModel(model: ReturnType<typeof toChatModelOption>) {
  return {
    provider_id: model.providerId,
    provider_label: model.providerLabel,
    model_id: model.modelId,
    model_label: model.modelLabel,
    family_group: model.familyGroup,
    capability_tags: model.capabilityTags,
    source: model.source,
  };
}

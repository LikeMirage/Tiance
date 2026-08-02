import type { Dispatch, SetStateAction } from "react";

import type { LlmModelCatalogEntry } from "../../../entities/llm-provider/model/modelCatalog";
import type {
  FunctionalModelOption,
  FunctionalModelProfileKey,
  FunctionalModelProfileSettingsMap,
  FunctionalModelSettings,
} from "./functionalModelSettings";
import { normalizeFunctionalModelSettings } from "./functionalModelSettings";

export function getFunctionalModelKey(model: FunctionalModelOption) {
  return `${model.providerId}:${model.modelId}`;
}

export function getModelCatalogKind(profileKey: FunctionalModelProfileKey) {
  void profileKey;
  return "functional_text" as const;
}

export function clearUnavailableProfileModel(
  profileKey: FunctionalModelProfileKey,
  eligibleTextModels: readonly FunctionalModelOption[],
  setAllSettings: Dispatch<SetStateAction<FunctionalModelSettings>>,
) {
  setAllSettings((current) => {
    const currentProfile = current[profileKey];
    if (!currentProfile.modelKey) {
      return current;
    }

    const selectedModelStillAvailable = eligibleTextModels.some((model) =>
      getFunctionalModelKey(model) === currentProfile.modelKey,
    );
    if (selectedModelStillAvailable) {
      return current;
    }

    return {
      ...current,
      [profileKey]: {
        ...currentProfile,
        modelKey: "",
      },
    };
  });
}

export function normalizeProfileSettings<K extends FunctionalModelProfileKey>(
  profileKey: K,
  input: unknown,
  storedVersion?: number | null,
): FunctionalModelProfileSettingsMap[K] {
  const settingsPayload: Record<string, unknown> = {
    [profileKey]: input,
  };
  if (typeof storedVersion === "number") {
    settingsPayload.version = storedVersion;
  }
  return normalizeFunctionalModelSettings(settingsPayload)[profileKey] as FunctionalModelProfileSettingsMap[K];
}

export function getStringSetting(
  settings: FunctionalModelProfileSettingsMap[FunctionalModelProfileKey],
  key: string,
) {
  const value = settings[key as keyof typeof settings];
  return typeof value === "string" ? value : null;
}

export function toFunctionalModelOption(model: LlmModelCatalogEntry): FunctionalModelOption {
  return {
    capabilityTags: model.capability_tags,
    modelId: model.model_id,
    modelLabel: model.model_label || model.model_id,
    providerId: model.provider_id,
    providerLabel: model.provider_label || model.provider_id,
  };
}

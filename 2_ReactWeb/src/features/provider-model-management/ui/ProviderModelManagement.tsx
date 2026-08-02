import type { UseProviderModelDiscoveryResult } from "../../../features/provider-model-discovery/model/useProviderModelDiscovery";
import type {
  ModelManagementMode,
  UseModelManagementPanelResult,
} from "../model/useProviderModelManagement";
import { AddedModelsView } from "./AddedModelsView";
import { CloudModelsView } from "./CloudModelsView";
import { CustomModelEditor } from "./CustomModelEditor";
import type { ModelCheckState } from "./providerModelManagementUiTypes";

export type { ModelCheckState } from "./providerModelManagementUiTypes";

type ProviderModelManagementProps = {
  hasAnyProviderApiKey: boolean;
  mode: ModelManagementMode;
  modelCheckStates: Record<string, ModelCheckState>;
  modelManagementPanel: UseModelManagementPanelResult;
  onTestModel: (modelId: string, label: string) => Promise<void>;
  providerId: string;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  testingModelIds: string[];
};

export function ProviderModelManagement({
  hasAnyProviderApiKey,
  mode,
  modelCheckStates,
  modelManagementPanel,
  onTestModel,
  providerId,
  providerModelDiscovery,
  testingModelIds,
}: ProviderModelManagementProps) {
  if (mode === "added") {
    return (
      <AddedModelsView
        hasAnyProviderApiKey={hasAnyProviderApiKey}
        modelCheckStates={modelCheckStates}
        modelManagementPanel={modelManagementPanel}
        onTestModel={onTestModel}
        testingModelIds={testingModelIds}
      />
    );
  }

  if (mode === "cloud") {
    return (
      <CloudModelsView
        hasAnyProviderApiKey={hasAnyProviderApiKey}
        modelCheckStates={modelCheckStates}
        modelManagementPanel={modelManagementPanel}
        onTestModel={onTestModel}
        providerModelDiscovery={providerModelDiscovery}
        testingModelIds={testingModelIds}
      />
    );
  }

  return (
    <CustomModelEditor
      modelManagementPanel={modelManagementPanel}
      providerId={providerId}
    />
  );
}

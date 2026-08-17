import { useState } from "react";

import type {
  ProviderCatalogEntry,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { UseProviderConfigStateResult } from "../../provider-config/model/useProviderConfigState";
import type { UseProviderModelDiscoveryResult } from "../../provider-model-discovery/model/useProviderModelDiscovery";
import {
  ProviderApiBaseUrlSection,
  ProviderOtherSettingsSection,
} from "../../provider-config/ui/ProviderConfigSections";
import {
  formatModelSetUsage,
} from "../../provider-model-management/model/providerUsageFormat";
import { ProviderModelManagement } from "../../provider-model-management/ui/ProviderModelManagement";
import { getProviderUsageMetricLabels } from "../../provider-model-management/ui/providerModelI18n";
import type { ModelManagementMode } from "../../provider-model-management/model/useProviderModelManagement";
import { InlineEditableText } from "../../../shared/ui/inline-editable-text/InlineEditableText";
import { useI18n } from "../../../shared/i18n";
import { useProviderCanvasController } from "../model/useProviderCanvasController";
import "./provider-canvas.css";

export type ProviderCanvasPanelProps = {
  isActive?: boolean;
  isRenamingProvider: boolean;
  isUpdatingProviderProtocol: boolean;
  onRenameProvider: (providerId: string, displayName: string) => Promise<void>;
  onUpdateProviderProtocol: (
    providerId: string,
    protocolFamily: ProviderProtocolFamily,
  ) => Promise<void>;
  providerConfigState: UseProviderConfigStateResult;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  selectedProvider: ProviderCatalogEntry;
};

type ProviderSettingsView = "api" | "models" | "other";

export function ProviderCanvasPanel({
  isActive = true,
  isRenamingProvider,
  isUpdatingProviderProtocol,
  onRenameProvider,
  onUpdateProviderProtocol,
  providerConfigState,
  providerModelDiscovery,
  selectedProvider,
}: ProviderCanvasPanelProps) {
  const { t } = useI18n();
  const [activeSettingsView, setActiveSettingsView] =
    useState<ProviderSettingsView>("api");
  const controller = useProviderCanvasController({
    isActive,
    onUpdateProviderProtocol,
    providerConfigState,
    providerModelDiscovery,
    selectedProvider,
  });
  const selectedProviderDraft = controller.selectedProviderDraft;

  if (!selectedProviderDraft) {
    return null;
  }

  const isSavingSelectedProvider =
    providerConfigState.savingProviderId === selectedProvider.provider_id;
  const enableToggleActionLabel = selectedProviderDraft.enabled
    ? t("providerCanvas.disable")
    : t("providerCanvas.enable");
  const enableToggleClassName = [
    "provider-canvas__canvas-enable",
    selectedProviderDraft.enabled ? "provider-canvas__canvas-enable--active" : "",
    isSavingSelectedProvider ? "provider-canvas__canvas-enable--saving" : "",
  ].filter(Boolean).join(" ");
  const usageMetricLabels = getProviderUsageMetricLabels(t);
  return (
    <div className="provider-canvas">
      <div className="provider-canvas__canvas-head">
        <div className="provider-canvas__canvas-head-copy">
          <InlineEditableText
            ariaLabel={t("providerCanvas.renameProvider", {
              provider: selectedProvider.display_name,
            })}
            as="h2"
            className="provider-canvas__canvas-title"
            disabled={isRenamingProvider}
            editable
            emptyErrorMessage={t("providerCanvas.errors.providerNameRequired")}
            value={selectedProvider.display_name}
            onCommit={(displayName) =>
              onRenameProvider(selectedProvider.provider_id, displayName)
            }
          />
          <span className="provider-canvas__provider-usage-summary">
            {formatModelSetUsage(
              controller.modelManagementPanel.providerUsageSummary,
              usageMetricLabels,
            )}
          </span>
        </div>
        <div className="provider-canvas__canvas-head-actions">
          <button
            className={enableToggleClassName}
            type="button"
            aria-busy={isSavingSelectedProvider}
            aria-pressed={selectedProviderDraft.enabled}
            aria-label={`${enableToggleActionLabel} ${selectedProvider.display_name}`}
            disabled={
              isSavingSelectedProvider
              || (!selectedProviderDraft.enabled
                && selectedProviderDraft.apiBaseUrl.trim().length === 0)
            }
            onClick={providerConfigState.toggleSelectedEnabled}
          >
            {t("providerCanvas.enable")}
          </button>
        </div>
      </div>
      <div className="provider-canvas__scroll-content">
        {controller.providerProtocolError || providerConfigState.error ? (
          <div className="provider-canvas__provider-protocol-error" role="status">
            {controller.providerProtocolError ?? providerConfigState.error}
          </div>
        ) : null}

        <div className="provider-canvas__canvas-config">
          <nav
            className="provider-canvas__settings-tabs"
            role="tablist"
            aria-label={t("providerCanvas.settingsTabs.aria")}
          >
            {(["api", "models", "other"] as const).map((view) => (
              <button
                key={view}
                className={
                  activeSettingsView === view
                    ? "provider-canvas__settings-tab provider-canvas__settings-tab--active"
                    : "provider-canvas__settings-tab"
                }
                type="button"
                role="tab"
                aria-selected={activeSettingsView === view}
                onClick={() => setActiveSettingsView(view)}
              >
                {t(`providerCanvas.settingsTabs.${view}`)}
              </button>
            ))}
          </nav>

          {activeSettingsView === "api" ? (
            <ProviderApiBaseUrlSection
              apiKeyInputRefs={controller.apiKeyInputRefs}
              isUpdatingProviderProtocol={isUpdatingProviderProtocol}
              protocolFamily={selectedProvider.protocol_family}
              providerConfigState={providerConfigState}
              providerDisplayName={selectedProvider.display_name}
              selectedProviderDraft={selectedProviderDraft}
              onUpdateProviderProtocol={(value) => {
                void controller.updateSelectedProviderProtocol(value);
              }}
            />
          ) : null}

          {activeSettingsView === "other" ? (
            <ProviderOtherSettingsSection
              providerConfigState={providerConfigState}
              providerDisplayName={selectedProvider.display_name}
              selectedProviderDraft={selectedProviderDraft}
            />
          ) : null}

          {activeSettingsView === "models" ? (
            <div className="provider-canvas__canvas-group">
              <header className="provider-canvas__api-address-section-head">
                <div
                  className="provider-canvas__api-address-tabs"
                  role="tablist"
                  aria-label={t("providerCanvas.modelManagement.modeAria")}
                >
                  {controller.modelModeTabs.map((tab) => (
                    <button
                      key={tab.id}
                      className={
                        controller.modelManagementPanel.activeMode === tab.id
                          ? "provider-canvas__api-address-tab provider-canvas__api-address-tab--active"
                          : "provider-canvas__api-address-tab"
                      }
                      type="button"
                      role="tab"
                      aria-selected={controller.modelManagementPanel.activeMode === tab.id}
                      onClick={tab.onClick}
                    >
                      {getModelModeLabel(tab.id, t)}
                    </button>
                  ))}
                </div>
              </header>

              <div className="provider-canvas__model-mode-stage">
                <div
                  className={
                    controller.modelModeTransitionState
                      ? controller.modelModeTransitionState.direction === "forward"
                        ? "provider-canvas__model-mode-view provider-canvas__model-mode-view--static provider-canvas__model-mode-view--enter-from-right"
                        : "provider-canvas__model-mode-view provider-canvas__model-mode-view--static provider-canvas__model-mode-view--enter-from-left"
                      : "provider-canvas__model-mode-view provider-canvas__model-mode-view--static"
                  }
                >
                  <ProviderModelManagement
                    hasAnyProviderApiKey={controller.hasAnyProviderApiKey}
                    mode={controller.modelManagementPanel.activeMode}
                    modelCheckStates={controller.modelCheckStates}
                    modelManagementPanel={controller.modelManagementPanel}
                    onTestModel={controller.testModelConnection}
                    providerId={selectedProvider.provider_id}
                    providerModelDiscovery={providerModelDiscovery}
                    testingModelIds={controller.testingModelIds}
                  />
                </div>
                {controller.shouldRenderModelModeLeavingLayer && controller.modelModeTransitionState ? (
                  <div
                    className={
                      controller.modelModeTransitionState.direction === "forward"
                        ? "provider-canvas__model-mode-view provider-canvas__model-mode-view--layer provider-canvas__model-mode-view--exit-to-left"
                        : "provider-canvas__model-mode-view provider-canvas__model-mode-view--layer provider-canvas__model-mode-view--exit-to-right"
                    }
                    aria-hidden="true"
                  >
                    <ProviderModelManagement
                      hasAnyProviderApiKey={controller.hasAnyProviderApiKey}
                      mode={controller.modelModeTransitionState.leavingMode}
                      modelCheckStates={controller.modelCheckStates}
                      modelManagementPanel={controller.modelManagementPanel}
                      onTestModel={controller.testModelConnection}
                      providerId={selectedProvider.provider_id}
                      providerModelDiscovery={providerModelDiscovery}
                      testingModelIds={controller.testingModelIds}
                    />
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function getModelModeLabel(
  mode: ModelManagementMode,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (mode === "custom") return t("providerCanvas.modelManagement.tabs.custom");
  if (mode === "cloud") return t("providerCanvas.modelManagement.tabs.cloud");
  return t("providerCanvas.modelManagement.tabs.added");
}

import { useEffect, useMemo, useState } from "react";
import { Plus, Pulse } from "@phosphor-icons/react";

import type { DiscoveredModelEntry } from "../../../entities/llm-provider/model/discoveredModel";
import type { UseProviderModelDiscoveryResult } from "../../../features/provider-model-discovery/model/useProviderModelDiscovery";
import { useI18n } from "../../../shared/i18n";
import { normalizeCustomModelCapabilityTags } from "../model/customModelCapabilities";
import { getCustomModelCapabilityLabel } from "./providerModelI18n";
import "./discovered-model-catalog.css";

type DiscoveredModelCatalogProps = {
  addedModelIds: string[];
  addingModelIds: string[];
  deletingModelIds: string[];
  isTestingDisabled: boolean;
  modelCheckStates: Record<string, { message: string; tone: "error" | "success" }>;
  onTestModel: (modelId: string, label: string) => Promise<void>;
  onAddModel: (model: DiscoveredModelEntry) => Promise<void>;
  onRemoveModel: (modelId: string) => Promise<void>;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  testingModelIds: string[];
};

const GROUP_PREVIEW_ITEM_LIMIT = 1;

export function DiscoveredModelCatalog({
  addedModelIds,
  addingModelIds,
  deletingModelIds,
  isTestingDisabled,
  modelCheckStates,
  onTestModel,
  onAddModel,
  onRemoveModel,
  providerModelDiscovery,
  testingModelIds,
}: DiscoveredModelCatalogProps) {
  const { t } = useI18n();
  const [searchKeyword, setSearchKeyword] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setSearchKeyword("");
    setExpandedGroups({});
  }, [providerModelDiscovery.items]);

  const groupedItems = useMemo(
    () => groupDiscoveredModels(providerModelDiscovery.items),
    [providerModelDiscovery.items],
  );
  const filteredGroups = useMemo(
    () => filterDiscoveredModelGroups(groupedItems, searchKeyword, t),
    [groupedItems, searchKeyword, t],
  );

  useEffect(() => {
    setExpandedGroups((current) => {
      const nextEntries = groupedItems.map(([groupName]) => [
        groupName,
        current[groupName] ?? false,
      ] as const);
      return Object.fromEntries(nextEntries);
    });
  }, [groupedItems]);

  if (!providerModelDiscovery.visible) {
    return null;
  }

  const hasItems = providerModelDiscovery.items.length > 0;
  const isLoading = providerModelDiscovery.state === "loading";
  const refreshButton = (
    <button
      className={
        isLoading
          ? "workspace-discovered-models__refresh workspace-discovered-models__refresh--standalone workspace-discovered-models__refresh--loading"
          : "workspace-discovered-models__refresh workspace-discovered-models__refresh--standalone"
      }
      type="button"
      aria-label={t("providerCanvas.modelManagement.cloud.syncAria")}
      disabled={isLoading}
      onClick={() => {
        void providerModelDiscovery.refreshSelectedModels();
      }}
    >
      <SyncIcon />
    </button>
  );

  if (isLoading && !hasItems) {
    return (
      <div className="provider-canvas__model-empty">
        {t("providerCanvas.modelManagement.cloud.loading")}
      </div>
    );
  }

  if (providerModelDiscovery.state === "needs_api_key" && !hasItems) {
    return (
      <div className="workspace-discovered-models__notice workspace-discovered-models__notice--warning">
        {t("providerCanvas.modelManagement.cloud.needsApiKey")}
      </div>
    );
  }

  if (providerModelDiscovery.state === "error" && !hasItems) {
    return (
      <div className="provider-canvas__model-empty provider-canvas__model-empty--error workspace-discovered-models__empty-state">
        <span>{providerModelDiscovery.error ?? t("providerCanvas.modelManagement.cloud.loadFailed")}</span>
        {refreshButton}
      </div>
    );
  }

  if (!hasItems) {
    return (
      <div className="provider-canvas__model-empty workspace-discovered-models__empty-state">
        <span>{t("providerCanvas.modelManagement.cloud.empty")}</span>
        {refreshButton}
      </div>
    );
  }

  const staleCacheWarning =
    providerModelDiscovery.state === "error" || providerModelDiscovery.state === "needs_api_key"
      ? (providerModelDiscovery.error ?? t("providerCanvas.modelManagement.cloud.staleCache"))
      : null;

  return (
    <div className="workspace-discovered-models">
      <div className="workspace-discovered-models__toolbar">
        <label className="workspace-discovered-models__search">
          <span className="workspace-discovered-models__search-label">
            {t("providerCanvas.modelManagement.cloud.searchLabel")}
          </span>
          <input
            className="workspace-discovered-models__search-input"
            type="search"
            autoComplete="off"
            value={searchKeyword}
            placeholder={t("providerCanvas.modelManagement.cloud.searchPlaceholder")}
            onChange={(event) => setSearchKeyword(event.target.value)}
          />
        </label>
        <button
          className={
            isLoading
              ? "workspace-discovered-models__refresh workspace-discovered-models__refresh--loading"
              : "workspace-discovered-models__refresh"
          }
          type="button"
          aria-label={t("providerCanvas.modelManagement.cloud.syncAria")}
          disabled={isLoading}
          onClick={() => {
            void providerModelDiscovery.refreshSelectedModels();
          }}
        >
          <SyncIcon />
        </button>
      </div>

      {staleCacheWarning ? (
        <div className="workspace-discovered-models__notice workspace-discovered-models__notice--inline">
          {staleCacheWarning}
        </div>
      ) : null}

      {filteredGroups.length === 0 ? (
        <div className="provider-canvas__model-empty">
          {t("providerCanvas.modelManagement.cloud.emptyFiltered")}
        </div>
      ) : (
        <div className="workspace-discovered-models__groups">
          {filteredGroups.map(([groupName, models]) => {
            const isExpanded = expandedGroups[groupName] ?? false;
            const needsPreview = models.length > GROUP_PREVIEW_ITEM_LIMIT;

            return (
              <section
                key={groupName}
                className="workspace-discovered-models__group"
                aria-label={t("providerCanvas.modelManagement.cloud.groupAria", {
                  group: groupName,
                })}
              >
                <button
                  className={
                    isExpanded
                      ? "workspace-discovered-models__group-head workspace-discovered-models__group-head--expanded"
                      : "workspace-discovered-models__group-head"
                  }
                  type="button"
                  aria-expanded={isExpanded}
                  onClick={() =>
                    setExpandedGroups((current) => ({
                      ...current,
                      [groupName]: !isExpanded,
                    }))
                  }
                >
                  <span className="workspace-discovered-models__group-head-copy">
                    <h4 className="workspace-discovered-models__group-title">{groupName}</h4>
                    <span className="workspace-discovered-models__group-count">
                      {models.length}
                    </span>
                  </span>
                  <span
                    className={
                      isExpanded
                        ? "workspace-discovered-models__group-caret workspace-discovered-models__group-caret--expanded"
                        : "workspace-discovered-models__group-caret"
                    }
                    aria-hidden="true"
                  />
                </button>

                <div
                  className={
                    isExpanded
                      ? "workspace-discovered-models__group-content workspace-discovered-models__group-content--expanded"
                      : "workspace-discovered-models__group-content"
                  }
                >
                  <div className="workspace-discovered-models__group-body" role="list">
                    {models.map((model) => (
                      <DiscoveredModelRow
                        key={`${model.provider_id}:${model.model_id}`}
                        addedModelIds={addedModelIds}
                        addingModelIds={addingModelIds}
                        deletingModelIds={deletingModelIds}
                        isTestingDisabled={isTestingDisabled}
                        modelCheckState={modelCheckStates[model.model_id.trim()] ?? null}
                        model={model}
                        onTestModel={onTestModel}
                        onAddModel={onAddModel}
                        onRemoveModel={onRemoveModel}
                        testingModelIds={testingModelIds}
                      />
                    ))}
                  </div>

                  {needsPreview && !isExpanded ? (
                    <button
                      className="workspace-discovered-models__group-overlay"
                      type="button"
                      aria-label={t("providerCanvas.modelManagement.cloud.expandGroupAria", {
                        group: groupName,
                      })}
                      onClick={() =>
                        setExpandedGroups((current) => ({
                          ...current,
                          [groupName]: true,
                        }))
                      }
                    >
                      <span
                        className="workspace-discovered-models__group-overlay-caret"
                        aria-hidden="true"
                      />
                    </button>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

type DiscoveredModelRowProps = {
  addedModelIds: string[];
  addingModelIds: string[];
  deletingModelIds: string[];
  isTestingDisabled: boolean;
  modelCheckState: { message: string; tone: "error" | "success" } | null;
  model: DiscoveredModelEntry;
  onTestModel: (modelId: string, label: string) => Promise<void>;
  onAddModel: (model: DiscoveredModelEntry) => Promise<void>;
  onRemoveModel: (modelId: string) => Promise<void>;
  testingModelIds: string[];
};

function DiscoveredModelRow({
  addedModelIds,
  addingModelIds,
  deletingModelIds,
  isTestingDisabled,
  modelCheckState,
  model,
  onTestModel,
  onAddModel,
  onRemoveModel,
  testingModelIds,
}: DiscoveredModelRowProps) {
  const { t } = useI18n();
  const resolvedCapabilityTags = resolveDiscoveredModelCapabilityTags(model);
  const normalizedModelId = model.model_id.trim();
  const isAdded = addedModelIds.includes(normalizedModelId);
  const isAdding = addingModelIds.includes(normalizedModelId);
  const isDeleting = deletingModelIds.includes(normalizedModelId);
  const resolvedName = resolveDiscoveredModelName(model);
  const shouldShowModelId =
    normalizedModelId.length > 0 &&
    resolvedName.trim().toLowerCase() !== normalizedModelId.toLowerCase();
  const isBusy = isAdding || isDeleting;
  const isTesting = testingModelIds.includes(normalizedModelId);

  return (
    <article className="workspace-discovered-models__item" role="listitem">
      <div className="workspace-discovered-models__item-copy">
        <span className="workspace-discovered-models__item-name">{resolvedName}</span>
        {shouldShowModelId ? (
          <span className="workspace-discovered-models__item-meta">{model.model_id}</span>
        ) : null}
      </div>
      <div className="workspace-discovered-models__item-side">
        {resolvedCapabilityTags.length > 0 ? (
          <div
            className="workspace-discovered-models__item-tags"
            aria-label={t("providerCanvas.modelManagement.capabilities.aria")}
          >
            {resolvedCapabilityTags.map((capability) => (
              <span key={capability} className="workspace-discovered-models__item-tag">
                {getCustomModelCapabilityLabel(capability, t)}
              </span>
            ))}
          </div>
        ) : null}
        {isTesting ? (
          <span
            className="workspace-discovered-models__item-check-state workspace-discovered-models__item-check-state--pending"
            role="status"
          >
            {t("providerCanvas.modelManagement.test.testing")}
          </span>
        ) : modelCheckState ? (
          <button
            className={
              modelCheckState.tone === "success"
                ? "workspace-discovered-models__item-check-state workspace-discovered-models__item-check-state--success"
                : "workspace-discovered-models__item-check-state workspace-discovered-models__item-check-state--error"
            }
            type="button"
            aria-label={t("providerCanvas.modelManagement.test.retestAria", {
              model: resolvedName,
            })}
            title={modelCheckState.message}
            disabled={isBusy || isTestingDisabled}
            onClick={() => {
              void onTestModel(normalizedModelId, resolvedName);
            }}
          >
            {modelCheckState.tone === "success"
              ? t("providerCanvas.modelManagement.test.success")
              : t("providerCanvas.modelManagement.test.failed")}
          </button>
        ) : (
          <button
            className="workspace-discovered-models__item-check"
            type="button"
            aria-label={t("providerCanvas.modelManagement.test.testAria", {
              model: resolvedName,
            })}
            title={t("providerCanvas.modelManagement.test.title")}
            disabled={isBusy || isTestingDisabled}
            onClick={() => {
              void onTestModel(normalizedModelId, resolvedName);
            }}
          >
            <Pulse aria-hidden="true" size={14} weight="regular" />
          </button>
        )}
        <button
          className={
            isAdded
              ? isBusy
                ? "workspace-discovered-models__item-add workspace-discovered-models__item-add--added workspace-discovered-models__item-add--busy"
                : "workspace-discovered-models__item-add workspace-discovered-models__item-add--added"
              : isBusy
                ? "workspace-discovered-models__item-add workspace-discovered-models__item-add--busy"
                : "workspace-discovered-models__item-add"
          }
          type="button"
          aria-label={
            isDeleting
              ? t("common.actions.deleting")
              : isAdded
                ? t("providerCanvas.modelManagement.cloud.deleteModelAria", {
                  model: resolvedName,
                })
                : isAdding
                  ? t("providerCanvas.modelManagement.cloud.adding")
                  : t("providerCanvas.modelManagement.cloud.addModelAria", {
                    model: resolvedName,
                  })
          }
          title={
            isDeleting
              ? t("common.actions.deleting")
              : isAdded
                ? t("providerCanvas.modelManagement.cloud.removeFromAdded")
                : isAdding
                  ? t("providerCanvas.modelManagement.cloud.adding")
                  : t("providerCanvas.modelManagement.cloud.addToAdded")
          }
          disabled={isBusy || isTesting}
          onClick={() => {
            if (isAdded) {
              void onRemoveModel(normalizedModelId);
              return;
            }

            void onAddModel(model);
          }}
        >
          <Plus aria-hidden="true" size={14} weight="bold" />
        </button>
      </div>
    </article>
  );
}

function SyncIcon() {
  return (
    <svg
      className="workspace-discovered-models__refresh-icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M20 11a8 8 0 0 0-14.2-4.8" />
      <path d="M5 3v4h4" />
      <path d="M4 13a8 8 0 0 0 14.2 4.8" />
      <path d="M19 21v-4h-4" />
    </svg>
  );
}

function groupDiscoveredModels(items: DiscoveredModelEntry[]) {
  const groups = new Map<string, DiscoveredModelEntry[]>();

  items
    .slice()
    .sort((left, right) =>
      resolveDiscoveredModelName(left).localeCompare(resolveDiscoveredModelName(right), "zh-CN"),
    )
    .forEach((item) => {
      const groupName = item.family_group || item.provider_id;
      const currentGroup = groups.get(groupName);
      if (currentGroup) {
        currentGroup.push(item);
        return;
      }

      groups.set(groupName, [item]);
    });

  return Array.from(groups.entries()).sort(([leftGroup], [rightGroup]) =>
    leftGroup.localeCompare(rightGroup, "zh-CN"),
  );
}

function filterDiscoveredModelGroups(
  groupedItems: Array<[string, DiscoveredModelEntry[]]>,
  searchKeyword: string,
  t: ReturnType<typeof useI18n>["t"],
) {
  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  if (normalizedKeyword.length === 0) {
    return groupedItems;
  }

  return groupedItems.flatMap(([groupName, models]) => {
    if (groupName.toLowerCase().includes(normalizedKeyword)) {
      return [[groupName, models] as [string, DiscoveredModelEntry[]]];
    }

    const matchedModels = models.filter((model) =>
      buildDiscoveredModelSearchText(model, t).includes(normalizedKeyword),
    );

    if (matchedModels.length === 0) {
      return [];
    }

    return [[groupName, matchedModels] as [string, DiscoveredModelEntry[]]];
  });
}

function buildDiscoveredModelSearchText(
  model: DiscoveredModelEntry,
  t: ReturnType<typeof useI18n>["t"],
) {
  const capabilityTags = resolveDiscoveredModelCapabilityTags(model);
  return [
    model.display_name,
    model.model_id,
    model.family_group,
    model.provider_id,
    ...capabilityTags,
    ...capabilityTags.map((capability) => getCustomModelCapabilityLabel(capability, t)),
  ]
    .join(" ")
    .toLowerCase();
}

function resolveDiscoveredModelCapabilityTags(model: DiscoveredModelEntry) {
  return normalizeCustomModelCapabilityTags(model.capability_tags);
}

function resolveDiscoveredModelName(model: DiscoveredModelEntry) {
  return model.display_name || model.model_id;
}

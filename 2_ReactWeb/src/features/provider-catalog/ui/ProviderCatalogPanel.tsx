import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import { useOverlayScrollbar } from "../../../shared/model/overlay-scrollbar/useOverlayScrollbar";
import { useProviderCreateForm } from "../model/useProviderCreateForm";
import { useProviderCatalogReorder } from "../model/useProviderCatalogReorder";
import type { UseProviderCatalogResult } from "../model/useProviderCatalog";
import type { ProjectCategory } from "../../../entities/project/model/project";
import { ProviderCatalogCreateForm } from "./ProviderCatalogCreateForm";
import { ProviderCatalogList } from "./ProviderCatalogList";
import "./provider-catalog-panel.css";

type ProviderCatalogPanelProps = {
  categoryId?: string | null;
  onOpenProvider?: (providerId: string) => void;
  onMoveProviderToCategory?: (providerId: string, categoryId: string) => void;
  providerCatalog: UseProviderCatalogResult;
  visibleProviderIds?: ReadonlySet<string>;
  targetCategories?: ProjectCategory[];
};

export function ProviderCatalogPanel({
  categoryId,
  onOpenProvider,
  onMoveProviderToCategory,
  providerCatalog,
  visibleProviderIds,
  targetCategories,
}: ProviderCatalogPanelProps) {
  const { t } = useI18n();
  const [searchKeyword, setSearchKeyword] = useState("");
  const normalizedKeyword = searchKeyword.trim().toLowerCase();
  const filteredProviders = useMemo(
    () =>
      providerCatalog.items.filter((provider) => {
            if (visibleProviderIds && !visibleProviderIds.has(provider.provider_id)) {
              return false;
            }
            if (normalizedKeyword.length === 0) return true;
            const searchableText =
              `${provider.display_name} ${provider.provider_id}`.toLowerCase();
            return searchableText.includes(normalizedKeyword);
          }),
    [normalizedKeyword, providerCatalog.items, visibleProviderIds],
  );

  const providerCreateForm = useProviderCreateForm({
    categoryId,
    onCreated: () => setSearchKeyword(""),
    providerCatalog,
  });
  const providerScrollbar = useOverlayScrollbar(
    [
      providerCatalog.state,
      filteredProviders.length,
      providerCreateForm.isVisible ? "create-open" : "create-closed",
    ].join(":"),
  );
  const providerReorder = useProviderCatalogReorder(
    providerCatalog,
    filteredProviders.map((provider) => provider.provider_id),
  );

  return (
    <aside
      className="provider-catalog-panel"
      aria-label={t("providerCatalog.panel")}
    >
      <header className="provider-catalog-panel__header">
        <h2 className="provider-catalog-panel__title">{t("providerCatalog.title")}</h2>
        <button
          className="provider-catalog-panel__add"
          type="button"
          aria-label={t("providerCatalog.addProvider")}
          aria-expanded={providerCreateForm.isVisible}
          onClick={() => {
            providerScrollbar.scrollRef.current?.scrollTo({ top: 0 });
            providerCreateForm.toggle();
          }}
        >
          +
        </button>
      </header>

      <ProviderCatalogCreateForm
        apiBaseUrlInputRef={providerCreateForm.apiBaseUrlInputRef}
        draft={providerCreateForm.draft}
        error={providerCreateForm.error}
        isApiBaseUrlInvalid={providerCreateForm.isApiBaseUrlInvalid}
        isInteractive={providerCreateForm.isInteractive}
        isSubmitting={providerCatalog.isCreatingProvider}
        isVisible={providerCreateForm.isVisible}
        onCancel={providerCreateForm.close}
        onSubmit={() => void providerCreateForm.submit()}
        onUpdateField={providerCreateForm.updateField}
      />

      <label className="provider-catalog-panel__search">
        <span className="provider-catalog-panel__search-label">{t("providerCatalog.search")}</span>
        <input
          className="provider-catalog-panel__search-input"
          type="search"
          autoComplete="off"
          value={searchKeyword}
          placeholder={t("providerCatalog.search")}
          onChange={(event) => setSearchKeyword(event.target.value)}
        />
      </label>

      {providerCatalog.state === "ready" && providerCatalog.error ? (
        <div className="provider-catalog-panel__action-error" role="status">
          {providerCatalog.error}
        </div>
      ) : null}

      <ProviderCatalogList
        dragHoverTarget={providerReorder.dragHoverTarget}
        draggingProviderId={providerReorder.draggingProviderId}
        filteredProviders={filteredProviders}
        onListDragOver={providerReorder.handleListDragOver}
        onListDrop={providerReorder.handleListDrop}
        onProviderDragEnd={providerReorder.handleProviderDragEnd}
        onProviderDragOver={providerReorder.handleProviderDragOver}
        onProviderDragStart={providerReorder.handleProviderDragStart}
        onOpenProvider={onOpenProvider}
        onMoveProviderToCategory={onMoveProviderToCategory}
        providerCatalog={providerCatalog}
        providerScrollbar={providerScrollbar}
        registerProviderItem={providerReorder.registerProviderItem}
        targetCategories={targetCategories}
      />
    </aside>
  );
}

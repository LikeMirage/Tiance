import { useMemo, useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { OnlineMarketSourceSelector } from "../../online-market-source/ui/OnlineMarketSourceSelector";
import {
  THEME_MARKET_BOARD_CLASSES,
} from "../../../shared/online-market/OnlineMarketBoardControls";
import { OnlineMarketBoardShell } from "../../../shared/online-market/OnlineMarketBoardShell";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { DEFAULT_PROVIDER_MARKET_SOURCE } from "../../../services/llm/providerMarketApi";
import {
  filterProviderMarketItems,
  listProviderMarketValues,
  type ProviderMarketProvider,
} from "../model/providerMarket";
import { useProviderMarket, type ProviderInstallState } from "../model/useProviderMarket";
import { ProviderInstallCategoryModal } from "./ProviderInstallCategoryModal";
import { ProviderMarketFilterPanel } from "./ProviderMarketFilterPanel";
import "../../theme-market/ui/theme-market-board.css";
import "../../role-market/ui/role-market-board.css";
import "./provider-market-board.css";

export function ProviderMarketBoard({
  categories,
  isActive,
  selectedCategoryId,
}: {
  categories: readonly ProjectCategory[];
  isActive: boolean;
  selectedCategoryId: string | null;
}) {
  const { language, t } = useI18n();
  const market = useProviderMarket(isActive);
  const [query, setQuery] = useState("");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [pendingProvider, setPendingProvider] = useState<ProviderMarketProvider | null>(null);
  const [pendingUpdate, setPendingUpdate] = useState<ProviderMarketProvider | null>(null);
  const providers = useMemo(
    () => filterProviderMarketItems(market.index?.providers ?? [], market.filters, query),
    [market.filters, market.index?.providers, query],
  );
  const authors = useMemo(
    () => listProviderMarketValues(market.index?.providers ?? [], "author"),
    [market.index?.providers],
  );
  const protocols = useMemo(
    () => listProviderMarketValues(market.index?.providers ?? [], "protocol"),
    [market.index?.providers],
  );
  const activeFilterCount = market.filters.authors.length
    + market.filters.protocols.length
    + market.filters.statuses.length;
  const hasFilters = Boolean(query.trim()) || activeFilterCount > 0;
  const providerCategories = categories.filter((category) => category.category_kind === "provider");

  return (
    <section className="theme-market-board role-market-board provider-market-board" aria-label={t("providerMarket.ariaLabel")}>
      <OnlineMarketBoardShell
        syncCollection="provider"
        auxiliary={isFilterOpen ? (
          <ProviderMarketFilterPanel
            authors={authors}
            filters={market.filters}
            onChange={market.setFilters}
            protocols={protocols}
          />
        ) : null}
        auxiliaryClassName="theme-market-board__auxiliary"
        classes={THEME_MARKET_BOARD_CLASSES}
        content={{
          emptyText: t(hasFilters ? "providerMarket.noResults" : "providerMarket.empty"),
          hasError: Boolean(market.error),
          hasIndex: Boolean(market.index),
          hasItems: providers.length > 0,
          isLoading: market.isLoading,
          loadingText: t("providerMarket.loading"),
          notConnectedText: t("providerMarket.notConnected"),
        }}
        error={{
          error: market.error,
          isLoading: market.isLoading,
          onRetry: () => void market.refresh(),
          retryText: t("common.actions.retry"),
        }}
        source={{
          connectText: t("providerMarket.connect"),
          connectingText: t("providerMarket.connecting"),
          draftSource: market.draftSource,
          inputId: "provider-market-source",
          isLoading: market.isLoading,
          onConnect: () => void market.connect(),
          onDraftSourceChange: market.setDraftSource,
          placeholder: t("providerMarket.sourcePlaceholder"),
          refreshText: t("common.actions.refresh"),
          selector: (
            <OnlineMarketSourceSelector
              defaultSource={DEFAULT_PROVIDER_MARKET_SOURCE}
              disabled={market.isLoading}
              onSelectDefault={() => void market.reset()}
              onSelectSource={(source) => void market.connectTo(source)}
              source={market.draftSource}
            />
          ),
          source: market.source,
        }}
        toolbar={{
          activeFilterCount,
          filterOpen: isFilterOpen,
          filterText: t("providerMarket.filter"),
          isLoading: market.isLoading,
          onFilterToggle: () => setIsFilterOpen((current) => !current),
          onQueryChange: setQuery,
          onRefresh: () => void market.refresh(),
          query,
          refreshText: t("common.actions.refresh"),
          searchPlaceholder: t("providerMarket.searchPlaceholder"),
          status: market.index ? (
            <>
              <strong>{market.index.name}</strong>
              <span>{t("providerMarket.providerCount", { count: market.index.providers.length })}</span>
              <span>{t("providerMarket.updatedAt", { value: formatDate(market.index.updatedAt, language) })}</span>
              {market.index.cached ? <span>{t("providerMarket.cached")}</span> : null}
            </>
          ) : (
            <span>{market.isLoading ? t("providerMarket.loading") : t("providerMarket.notConnected")}</span>
          ),
        }}
      >
        {providers.map((provider) => (
          <ProviderMarketCard
            installState={market.installStates[provider.id]}
            key={`${market.source}:${provider.id}:${provider.version}`}
            language={language}
            onInstall={() => {
              if (provider.installationStatus === "update-available") setPendingUpdate(provider);
              else setPendingProvider(provider);
            }}
            provider={provider}
          />
        ))}
      </OnlineMarketBoardShell>

      {pendingProvider ? (
        <ProviderInstallCategoryModal
          categories={providerCategories}
          onCancel={() => setPendingProvider(null)}
          onConfirm={(categoryId) => {
            const providerId = pendingProvider.id;
            setPendingProvider(null);
            void market.install(providerId, categoryId, false);
          }}
          provider={pendingProvider}
          selectedCategoryId={selectedCategoryId}
        />
      ) : null}
      {pendingUpdate ? (
        <ConfirmModal
          confirmLabel={t("providerMarket.install.updateConfirm")}
          message={t("providerMarket.install.updateMessage", {
            current: pendingUpdate.localVersion ?? "-",
            name: pendingUpdate.name,
            next: pendingUpdate.version,
          })}
          onCancel={() => setPendingUpdate(null)}
          onConfirm={() => {
            const providerId = pendingUpdate.id;
            setPendingUpdate(null);
            void market.install(providerId, null, true);
          }}
          title={t("providerMarket.install.updateTitle")}
        />
      ) : null}
    </section>
  );
}

function ProviderMarketCard({
  installState,
  language,
  onInstall,
  provider,
}: {
  installState?: ProviderInstallState;
  language: string;
  onInstall: () => void;
  provider: ProviderMarketProvider;
}) {
  const { t } = useI18n();
  const isInstalling = installState?.phase === "installing";
  const isInstalled = provider.installationStatus === "installed";
  const disabled = isInstalling || isInstalled;
  const errorMessage = installState?.phase === "error"
    ? installState.error ?? t("providerMarket.install.failed")
    : null;

  return (
    <article className="role-market-card provider-market-card">
      <header className="role-market-card__header">
        <div className="role-market-card__identity">
          <strong title={provider.name}>{provider.name}</strong>
          <span>{provider.id} · {provider.protocol}</span>
        </div>
        <span className={`role-market-card__status role-market-card__status--${provider.installationStatus}`}>
          {statusLabel(provider.installationStatus, t)}
        </span>
      </header>
      <p className="role-market-card__summary">{provider.summary}</p>
      <footer className="role-market-card__footer">
        <div className="role-market-card__details">
          <span className="role-market-card__metadata">
            {provider.author} · v{provider.version} · {t("providerMarket.modelCount", { count: provider.modelCount })} · {formatBytes(provider.size, language)}
          </span>
          {errorMessage ? <span className="role-market-card__error" title={errorMessage}>{errorMessage}</span> : null}
        </div>
        <button className="role-market-card__action" type="button" disabled={disabled} onClick={onInstall}>
          {isInstalling
            ? t("providerMarket.install.installingShort")
            : isInstalled
              ? t("providerMarket.install.installed")
              : provider.installationStatus === "update-available"
                  ? t("providerMarket.install.update")
                  : errorMessage
                    ? t("common.actions.retry")
                    : t("providerMarket.install.download")}
        </button>
      </footer>
    </article>
  );
}

function statusLabel(status: ProviderMarketProvider["installationStatus"], t: ReturnType<typeof useI18n>["t"]) {
  if (status === "installed") return t("providerMarket.statuses.installed");
  if (status === "update-available") return t("providerMarket.statuses.update-available");
  return t("providerMarket.statuses.not-installed");
}

function formatDate(value: string, language: string) {
  return new Intl.DateTimeFormat(language, { day: "2-digit", month: "2-digit", year: "numeric" })
    .format(new Date(value));
}

function formatBytes(value: number, language: string) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(size)} ${units[unitIndex]}`;
}

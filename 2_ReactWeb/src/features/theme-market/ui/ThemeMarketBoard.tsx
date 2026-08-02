import { useMemo, useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { OnlineMarketSourceSelector } from "../../online-market-source/ui/OnlineMarketSourceSelector";
import {
  THEME_MARKET_BOARD_CLASSES,
} from "../../../shared/online-market/OnlineMarketBoardControls";
import { OnlineMarketBoardShell } from "../../../shared/online-market/OnlineMarketBoardShell";
import {
  DEFAULT_THEME_MARKET_SOURCE,
  getThemeMarketPreviewUrl,
} from "../../../services/theme-market/themeMarketApi";
import type { ThemeMarketTheme } from "../model/themeMarket";
import { useThemeMarket, type ThemeInstallState } from "../model/useThemeMarket";
import { ThemeInstallCategoryModal } from "./ThemeInstallCategoryModal";
import { ThemeMarketFilterPanel } from "./ThemeMarketFilterPanel";
import { ThemeUpdateConfirmModal } from "./ThemeUpdateConfirmModal";
import "./theme-market-board.css";

type ThemeMarketBoardProps = {
  categories: readonly ProjectCategory[];
  isActive: boolean;
  selectedCategoryId: string | null;
};

export function ThemeMarketBoard({
  categories,
  isActive,
  selectedCategoryId,
}: ThemeMarketBoardProps) {
  const { language, t } = useI18n();
  const market = useThemeMarket(isActive);
  const [query, setQuery] = useState("");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [pendingTheme, setPendingTheme] = useState<ThemeMarketTheme | null>(null);
  const [pendingUpdateTheme, setPendingUpdateTheme] = useState<ThemeMarketTheme | null>(null);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const themes = useMemo(() => {
    return (market.index?.themes ?? []).filter((theme) => {
      if (market.filters.modes.length && !market.filters.modes.includes(theme.mode)) return false;
      if (market.filters.authors.length && !market.filters.authors.includes(theme.author)) return false;
      if (
        market.filters.baseColors.length
        && !theme.baseColors.some((color) => market.filters.baseColors.includes(color))
      ) return false;
      if (
        market.filters.statuses.length
        && !market.filters.statuses.includes(theme.installationStatus)
      ) return false;
      if (!normalizedQuery) return true;
      return [theme.name, theme.id, theme.author, theme.summary]
        .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
    });
  }, [market.filters, market.index?.themes, normalizedQuery]);
  const authors = useMemo(
    () => [...new Set((market.index?.themes ?? []).map((theme) => theme.author))].sort(),
    [market.index?.themes],
  );
  const baseColors = useMemo(
    () => [...new Set((market.index?.themes ?? []).flatMap((theme) => theme.baseColors))].sort(),
    [market.index?.themes],
  );
  const activeFilterCount = Object.values(market.filters)
    .reduce((total, values) => total + values.length, 0);
  const hasFilters = Boolean(normalizedQuery) || activeFilterCount > 0;
  return (
    <section className="theme-market-board" aria-label={t("themeMarket.ariaLabel")}>
      <OnlineMarketBoardShell
        syncCollection="theme"
        auxiliary={isFilterOpen ? (
          <ThemeMarketFilterPanel
            authors={authors}
            baseColors={baseColors}
            filters={market.filters}
            onChange={market.setFilters}
          />
        ) : null}
        auxiliaryClassName="theme-market-board__auxiliary"
        classes={THEME_MARKET_BOARD_CLASSES}
        content={{
          emptyText: t(hasFilters ? "themeMarket.noResults" : "themeMarket.empty"),
          hasError: Boolean(market.error),
          hasIndex: Boolean(market.index),
          hasItems: themes.length > 0,
          isLoading: market.isLoading,
          loadingText: t("themeMarket.loading"),
          notConnectedText: t("themeMarket.notConnected"),
        }}
        error={{
          error: market.error,
          isLoading: market.isLoading,
          onRetry: () => void market.refresh(),
          retryText: t("common.actions.retry"),
        }}
        source={{
          connectText: t("themeMarket.connect"),
          connectingText: t("themeMarket.connecting"),
          draftSource: market.draftSource,
          inputId: "theme-market-source",
          isLoading: market.isLoading,
          onConnect: () => void market.connect(),
          onDraftSourceChange: market.setDraftSource,
          placeholder: t("themeMarket.sourcePlaceholder"),
          refreshText: t("common.actions.refresh"),
          selector: (
            <OnlineMarketSourceSelector
              defaultSource={DEFAULT_THEME_MARKET_SOURCE}
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
          filterText: t("themeMarket.filter"),
          isLoading: market.isLoading,
          onFilterToggle: () => setIsFilterOpen((current) => !current),
          onQueryChange: setQuery,
          onRefresh: () => void market.refresh(),
          query,
          refreshText: t("common.actions.refresh"),
          searchPlaceholder: t("themeMarket.searchPlaceholder"),
          status: market.index ? (
            <>
              <strong>{market.index.name}</strong>
              <span>{t("themeMarket.themeCount", { count: market.index.themes.length })}</span>
              <span>{t("themeMarket.updatedAt", {
                value: formatDate(market.index.updatedAt, language),
              })}</span>
              {market.index.cached ? <span>{t("themeMarket.cached")}</span> : null}
            </>
          ) : (
            <span>{market.isLoading ? t("themeMarket.loading") : t("themeMarket.notConnected")}</span>
          ),
        }}
      >
        {themes.map((theme) => (
          <ThemeMarketCard
            installState={market.installStates[theme.id]}
            key={`${market.source}:${theme.id}:${theme.version}`}
            language={language}
            onInstall={() => {
              if (theme.installationStatus === "update-available") {
                setPendingUpdateTheme(theme);
                return;
              }
              setPendingTheme(theme);
            }}
            source={market.source}
            theme={theme}
          />
        ))}
      </OnlineMarketBoardShell>

      {pendingTheme ? (
        <ThemeInstallCategoryModal
          categories={categories.filter((category) => category.category_kind === "theme")}
          onCancel={() => setPendingTheme(null)}
          onConfirm={(categoryId) => {
            const themeId = pendingTheme.id;
            setPendingTheme(null);
            void market.install(themeId, categoryId, false);
          }}
          selectedCategoryId={selectedCategoryId}
          theme={pendingTheme}
        />
      ) : null}
      {pendingUpdateTheme ? (
        <ThemeUpdateConfirmModal
          onCancel={() => setPendingUpdateTheme(null)}
          onConfirm={() => {
            const themeId = pendingUpdateTheme.id;
            setPendingUpdateTheme(null);
            void market.install(themeId, null, true);
          }}
          theme={pendingUpdateTheme}
        />
      ) : null}
    </section>
  );
}

function ThemeMarketCard({
  installState,
  language,
  onInstall,
  source,
  theme,
}: {
  installState?: ThemeInstallState;
  language: string;
  onInstall: () => void;
  source: string;
  theme: ThemeMarketTheme;
}) {
  const { t } = useI18n();
  const [previewFailed, setPreviewFailed] = useState(false);
  const isInstalling = installState?.phase === "installing";
  const isInstalled = installState?.phase === "success"
    || theme.installationStatus === "installed";
  const canInstall = !isInstalled && !isInstalling;
  const errorMessage = installState?.phase === "error"
    ? installState.error ?? t("themeMarket.install.failed")
    : null;

  return (
    <article className="theme-market-card">
      <div className="theme-market-card__preview">
        {previewFailed ? (
          <span>{t("themeMarket.previewUnavailable")}</span>
        ) : (
          <img
            alt={t("themeMarket.previewAlt", { name: theme.name })}
            loading="lazy"
            src={getThemeMarketPreviewUrl(theme.previewPath, `${source}:${theme.version}`)}
            onError={() => setPreviewFailed(true)}
          />
        )}
      </div>
      <div className="theme-market-card__body">
        <header>
          <strong title={theme.name}>{theme.name}</strong>
          <span className={`theme-market-card__mode theme-market-card__mode--${theme.mode}`}>
            {t(`themeMarket.filters.${theme.mode}`)}
          </span>
        </header>
        <p>{theme.summary}</p>
        <div className={`theme-market-card__details${errorMessage ? " theme-market-card__details--error" : ""}`}>
          <div className="theme-market-card__details-copy">
            <span title={`${theme.author} · v${theme.version} · ${formatBytes(theme.size, language)}`}>
              {theme.author} · v{theme.version} · {formatBytes(theme.size, language)}
            </span>
            {errorMessage ? <span title={errorMessage}>{errorMessage}</span> : null}
          </div>
          <button
            type="button"
            disabled={!canInstall}
            onClick={onInstall}
          >
            {isInstalling
              ? t("themeMarket.install.installingShort")
              : isInstalled
                ? t("themeMarket.install.installed")
                : theme.installationStatus === "not-installed"
                  ? t("themeMarket.install.download")
                  : theme.installationStatus === "update-available"
                    ? t("themeMarket.install.update")
                    : t("themeMarket.install.installed")}
          </button>
        </div>
      </div>
    </article>
  );
}

function formatDate(value: string, language: string) {
  return new Intl.DateTimeFormat(language, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
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

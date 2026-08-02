import { useMemo, useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { OnlineMarketSourceSelector } from "../../online-market-source/ui/OnlineMarketSourceSelector";
import {
  THEME_MARKET_BOARD_CLASSES,
} from "../../../shared/online-market/OnlineMarketBoardControls";
import { OnlineMarketBoardShell } from "../../../shared/online-market/OnlineMarketBoardShell";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { DEFAULT_TOOL_MARKET_SOURCE } from "../../../services/tools/toolMarketApi";
import {
  filterToolMarketItems,
  listToolMarketPlatforms,
  listToolMarketValues,
  type ToolMarketTool,
} from "../model/toolMarket";
import { useToolMarket } from "../model/useToolMarket";
import { ToolInstallModal } from "./ToolInstallModal";
import { ToolMarketCard } from "./ToolMarketCard";
import { ToolMarketFilterPanel } from "./ToolMarketFilterPanel";
import "../../theme-market/ui/theme-market-board.css";
import "../../role-market/ui/role-market-board.css";
import "./tool-market-board.css";

export function ToolMarketBoard({
  categories, isActive, onInstalled, selectedCategoryId,
}: {
  categories: readonly ProjectCategory[];
  isActive: boolean;
  onInstalled?: () => void;
  selectedCategoryId: string | null;
}) {
  const { language, t } = useI18n();
  const market = useToolMarket(isActive, onInstalled);
  const [query, setQuery] = useState("");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [pendingTool, setPendingTool] = useState<ToolMarketTool | null>(null);
  const [pendingUpdate, setPendingUpdate] = useState<ToolMarketTool | null>(null);
  const tools = useMemo(
    () => filterToolMarketItems(market.index?.tools ?? [], market.filters, query),
    [market.filters, market.index?.tools, query],
  );
  const authors = useMemo(
    () => listToolMarketValues(market.index?.tools ?? [], "author"),
    [market.index?.tools],
  );
  const runtimes = useMemo(
    () => listToolMarketValues(market.index?.tools ?? [], "runtime"),
    [market.index?.tools],
  );
  const platforms = useMemo(
    () => listToolMarketPlatforms(market.index?.tools ?? []),
    [market.index?.tools],
  );
  const activeFilterCount = market.filters.authors.length
    + market.filters.runtimes.length
    + market.filters.platforms.length
    + market.filters.statuses.length;
  const hasFilters = Boolean(query.trim()) || activeFilterCount > 0;

  return (
    <section className="theme-market-board role-market-board tool-market-board" aria-label={t("toolMarket.ariaLabel")}>
      <OnlineMarketBoardShell
        syncCollection="tool"
        auxiliary={isFilterOpen ? (
          <ToolMarketFilterPanel
            authors={authors}
            filters={market.filters}
            onChange={market.setFilters}
            platforms={platforms}
            runtimes={runtimes}
          />
        ) : null}
        auxiliaryClassName="theme-market-board__auxiliary"
        classes={THEME_MARKET_BOARD_CLASSES}
        content={{
          emptyText: t(hasFilters ? "toolMarket.noResults" : "toolMarket.empty"),
          hasError: Boolean(market.error),
          hasIndex: Boolean(market.index),
          hasItems: tools.length > 0,
          isLoading: market.isLoading,
          loadingText: t("toolMarket.loading"),
          notConnectedText: t("toolMarket.notConnected"),
        }}
        error={{
          error: market.error,
          isLoading: market.isLoading,
          onRetry: () => void market.refresh(),
          retryText: t("common.actions.retry"),
        }}
        source={{
          connectText: t("toolMarket.connect"),
          connectingText: t("toolMarket.connecting"),
          draftSource: market.draftSource,
          inputId: "tool-market-source",
          isLoading: market.isLoading,
          onConnect: () => void market.connect(),
          onDraftSourceChange: market.setDraftSource,
          placeholder: t("toolMarket.sourcePlaceholder"),
          refreshText: t("common.actions.refresh"),
          selector: (
            <OnlineMarketSourceSelector
              defaultSource={DEFAULT_TOOL_MARKET_SOURCE}
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
          filterText: t("toolMarket.filter"),
          isLoading: market.isLoading,
          onFilterToggle: () => setIsFilterOpen((current) => !current),
          onQueryChange: setQuery,
          onRefresh: () => void market.refresh(),
          query,
          refreshText: t("common.actions.refresh"),
          searchPlaceholder: t("toolMarket.searchPlaceholder"),
          status: market.index ? (
            <>
              <strong>{market.index.name}</strong>
              <span>{t("toolMarket.toolCount", { count: market.index.tools.length })}</span>
              <span>{t("toolMarket.updatedAt", { value: formatDate(market.index.updatedAt, language) })}</span>
              {market.index.cached ? <span>{t("toolMarket.cached")}</span> : null}
            </>
          ) : <span>{market.isLoading ? t("toolMarket.loading") : t("toolMarket.notConnected")}</span>,
        }}
      >
        {tools.map((tool) => (
          <ToolMarketCard
            installState={market.installStates[tool.id]}
            key={`${market.source}:${tool.id}:${tool.version}`}
            language={language}
            onInstall={() => {
              if (tool.installationStatus === "update-available") setPendingUpdate(tool);
              else setPendingTool(tool);
            }}
            tool={tool}
          />
        ))}
      </OnlineMarketBoardShell>

      {pendingTool ? (
        <ToolInstallModal
          categories={categories}
          onCancel={() => setPendingTool(null)}
          onConfirm={(categoryId, callName) => {
            const toolId = pendingTool.id;
            setPendingTool(null);
            void market.install(toolId, categoryId, callName);
          }}
          selectedCategoryId={selectedCategoryId}
          tool={pendingTool}
        />
      ) : null}
      {pendingUpdate ? (
        <ConfirmModal
          confirmLabel={t("toolMarket.install.updateConfirm")}
          message={t("toolMarket.install.updateMessage", {
            current: pendingUpdate.localVersion ?? "-",
            name: pendingUpdate.displayName,
            next: pendingUpdate.version,
          })}
          onCancel={() => setPendingUpdate(null)}
          onConfirm={() => {
            const toolId = pendingUpdate.id;
            setPendingUpdate(null);
            void market.install(toolId, null, null);
          }}
          title={t("toolMarket.install.updateTitle")}
        />
      ) : null}
    </section>
  );
}

function formatDate(value: string, language: string) {
  return new Intl.DateTimeFormat(language, { day: "2-digit", month: "2-digit", year: "numeric" })
    .format(new Date(value));
}

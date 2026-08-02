import { useMemo, useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { OnlineMarketSourceSelector } from "../../online-market-source/ui/OnlineMarketSourceSelector";
import {
  THEME_MARKET_BOARD_CLASSES,
} from "../../../shared/online-market/OnlineMarketBoardControls";
import { OnlineMarketBoardShell } from "../../../shared/online-market/OnlineMarketBoardShell";
import { DEFAULT_ROLE_MARKET_SOURCE } from "../../../services/role-market/roleMarketApi";
import { filterRoleMarketRoles, listRoleMarketAuthors } from "../model/roleMarketFilters";
import type { RoleMarketRole } from "../model/roleMarket";
import { filterRoleCategories, isRoleMarketActionDisabled } from "../model/roleMarketOperations";
import { useRoleMarket, type RoleInstallState } from "../model/useRoleMarket";
import { RoleInstallCategoryModal } from "./RoleInstallCategoryModal";
import { RoleMarketFilterPanel } from "./RoleMarketFilterPanel";
import { RoleUpdateConfirmModal } from "./RoleUpdateConfirmModal";
import "../../theme-market/ui/theme-market-board.css";
import "./role-market-board.css";

type RoleMarketBoardProps = {
  categories: readonly ProjectCategory[];
  isActive: boolean;
  selectedCategoryId: string | null;
};

export function RoleMarketBoard({
  categories,
  isActive,
  selectedCategoryId,
}: RoleMarketBoardProps) {
  const { language, t } = useI18n();
  const market = useRoleMarket(isActive);
  const [query, setQuery] = useState("");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [pendingRole, setPendingRole] = useState<RoleMarketRole | null>(null);
  const [pendingUpdateRole, setPendingUpdateRole] = useState<RoleMarketRole | null>(null);
  const roles = useMemo(
    () => filterRoleMarketRoles(market.index?.roles ?? [], market.filters, query),
    [market.filters, market.index?.roles, query],
  );
  const authors = useMemo(
    () => listRoleMarketAuthors(market.index?.roles ?? []),
    [market.index?.roles],
  );
  const activeFilterCount = market.filters.authors.length + market.filters.statuses.length;
  const hasFilters = Boolean(query.trim()) || activeFilterCount > 0;
  return (
    <section
      className="theme-market-board role-market-board"
      aria-label={t("roleMarket.ariaLabel")}
    >
      <OnlineMarketBoardShell
        auxiliary={isFilterOpen ? (
          <RoleMarketFilterPanel
            authors={authors}
            filters={market.filters}
            onChange={market.setFilters}
          />
        ) : null}
        auxiliaryClassName="theme-market-board__auxiliary"
        classes={THEME_MARKET_BOARD_CLASSES}
        content={{
          emptyText: t(hasFilters ? "roleMarket.noResults" : "roleMarket.empty"),
          hasError: Boolean(market.error),
          hasIndex: Boolean(market.index),
          hasItems: roles.length > 0,
          isLoading: market.isLoading,
          loadingText: t("roleMarket.loading"),
          notConnectedText: t("roleMarket.notConnected"),
        }}
        error={{
          error: market.error,
          isLoading: market.isLoading,
          onRetry: () => void market.refresh(),
          retryText: t("common.actions.retry"),
        }}
        source={{
          connectText: t("roleMarket.connect"),
          connectingText: t("roleMarket.connecting"),
          draftSource: market.draftSource,
          inputId: "role-market-source",
          isLoading: market.isLoading,
          onConnect: () => void market.connect(),
          onDraftSourceChange: market.setDraftSource,
          placeholder: t("roleMarket.sourcePlaceholder"),
          refreshText: t("common.actions.refresh"),
          selector: (
            <OnlineMarketSourceSelector
              defaultSource={DEFAULT_ROLE_MARKET_SOURCE}
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
          filterText: t("roleMarket.filter"),
          isLoading: market.isLoading,
          onFilterToggle: () => setIsFilterOpen((current) => !current),
          onQueryChange: setQuery,
          onRefresh: () => void market.refresh(),
          query,
          refreshText: t("common.actions.refresh"),
          searchPlaceholder: t("roleMarket.searchPlaceholder"),
          status: market.index ? (
            <>
              <strong>{market.index.name}</strong>
              <span>{t("roleMarket.roleCount", { count: market.index.roles.length })}</span>
              <span>{t("roleMarket.updatedAt", {
                value: formatDate(market.index.updatedAt, language),
              })}</span>
              {market.index.cached ? <span>{t("roleMarket.cached")}</span> : null}
            </>
          ) : (
            <span>{market.isLoading ? t("roleMarket.loading") : t("roleMarket.notConnected")}</span>
          ),
        }}
      >
        {roles.map((role) => (
          <RoleMarketCard
            installState={market.installStates[role.id]}
            key={`${market.source}:${role.id}:${role.version}`}
            language={language}
            onInstall={() => {
              if (role.installationStatus === "update-available") {
                setPendingUpdateRole(role);
              } else {
                setPendingRole(role);
              }
            }}
            role={role}
          />
        ))}
      </OnlineMarketBoardShell>

      {pendingRole ? (
        <RoleInstallCategoryModal
          categories={filterRoleCategories(categories)}
          onCancel={() => setPendingRole(null)}
          onConfirm={(categoryId) => {
            const roleId = pendingRole.id;
            setPendingRole(null);
            void market.install(roleId, categoryId, false);
          }}
          role={pendingRole}
          selectedCategoryId={selectedCategoryId}
        />
      ) : null}
      {pendingUpdateRole ? (
        <RoleUpdateConfirmModal
          onCancel={() => setPendingUpdateRole(null)}
          onConfirm={() => {
            const roleId = pendingUpdateRole.id;
            setPendingUpdateRole(null);
            void market.install(roleId, null, true);
          }}
          role={pendingUpdateRole}
        />
      ) : null}
    </section>
  );
}

function RoleMarketCard({
  installState,
  language,
  onInstall,
  role,
}: {
  installState?: RoleInstallState;
  language: string;
  onInstall: () => void;
  role: RoleMarketRole;
}) {
  const { t } = useI18n();
  const isInstalling = installState?.phase === "installing";
  const isInstalled = role.installationStatus === "installed";
  const isActionDisabled = isRoleMarketActionDisabled(
    role.installationStatus,
    installState?.phase,
  );
  const errorMessage = installState?.phase === "error"
    ? installState.error ?? t("roleMarket.install.failed")
    : null;

  return (
    <article className="role-market-card">
      <header className="role-market-card__header">
        <div className="role-market-card__identity">
          <strong title={role.name}>{role.name}</strong>
          <span>{role.id}</span>
        </div>
        <span className={`role-market-card__status role-market-card__status--${role.installationStatus}`}>
          {t(`roleMarket.statuses.${role.installationStatus}`)}
        </span>
      </header>
      <p className="role-market-card__summary">{role.summary}</p>
      <footer className="role-market-card__footer">
        <div className="role-market-card__details">
          <span className="role-market-card__metadata">
            {role.author} · v{role.version} · {formatBytes(role.size, language)} · {role.license}
          </span>
          {errorMessage ? <span className="role-market-card__error" title={errorMessage}>{errorMessage}</span> : null}
        </div>
        <button
          className="role-market-card__action"
          type="button"
          disabled={isActionDisabled}
          onClick={onInstall}
        >
          {isInstalling
            ? t("roleMarket.install.installingShort")
            : isInstalled
              ? t("roleMarket.install.installed")
              : role.installationStatus === "update-available"
                ? t("roleMarket.install.update")
                : errorMessage
                  ? t("common.actions.retry")
                  : t("roleMarket.install.download")}
        </button>
      </footer>
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

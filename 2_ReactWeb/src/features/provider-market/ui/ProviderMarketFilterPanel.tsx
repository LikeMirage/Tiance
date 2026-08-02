import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import type {
  ProviderMarketFilters,
  ProviderMarketInstallationStatus,
} from "../model/providerMarket";

type FilterGroup = "authors" | "protocols" | "statuses";

const FILTER_GROUPS: readonly FilterGroup[] = ["authors", "protocols", "statuses"];
const STATUSES: readonly ProviderMarketInstallationStatus[] = [
  "not-installed", "installed", "update-available", "local-conflict",
];
const GROUP_LABELS: Record<FilterGroup, TranslationKey> = {
  authors: "providerMarket.filterGroups.authors",
  protocols: "providerMarket.filterGroups.protocols",
  statuses: "providerMarket.filterGroups.statuses",
};
const STATUS_LABELS: Record<ProviderMarketInstallationStatus, TranslationKey> = {
  "not-installed": "providerMarket.statuses.not-installed",
  installed: "providerMarket.statuses.installed",
  "update-available": "providerMarket.statuses.update-available",
  "local-conflict": "providerMarket.statuses.local-conflict",
};

export function ProviderMarketFilterPanel({
  authors,
  filters,
  onChange,
  protocols,
}: {
  authors: readonly string[];
  filters: ProviderMarketFilters;
  onChange: (filters: ProviderMarketFilters) => void;
  protocols: readonly string[];
}) {
  const { t } = useI18n();
  const [activeGroup, setActiveGroup] = useState<FilterGroup>("authors");
  const options = useMemo<readonly string[]>(() => {
    if (activeGroup === "authors") return authors;
    if (activeGroup === "protocols") return protocols;
    return STATUSES;
  }, [activeGroup, authors, protocols]);
  const selected: readonly string[] = filters[activeGroup];

  const updateSelected = (values: string[]) => {
    if (activeGroup === "statuses") {
      onChange({ ...filters, statuses: values as ProviderMarketInstallationStatus[] });
      return;
    }
    onChange({ ...filters, [activeGroup]: values });
  };

  return (
    <div className="theme-market-filter-panel">
      <nav className="theme-market-filter-panel__groups" aria-label={t("providerMarket.filterPanelAria")}>
        {FILTER_GROUPS.map((group) => (
          <button
            className={activeGroup === group ? "is-active" : undefined}
            key={group}
            type="button"
            onClick={() => setActiveGroup(group)}
          >
            <span>{t(GROUP_LABELS[group])}</span>
            {filters[group].length ? <small>{filters[group].length}</small> : null}
          </button>
        ))}
      </nav>
      <section className="theme-market-filter-panel__options">
        <strong>{t(GROUP_LABELS[activeGroup])}</strong>
        <div>
          <button
            className={selected.length === 0 ? "is-active" : undefined}
            type="button"
            onClick={() => updateSelected([])}
          >
            {t("providerMarket.filters.all")}
          </button>
          {options.map((option) => (
            <button
              className={selected.includes(option) ? "is-active" : undefined}
              key={option}
              type="button"
              onClick={() => updateSelected(toggleOption(selected, option))}
            >
              {activeGroup === "statuses"
                ? t(STATUS_LABELS[option as ProviderMarketInstallationStatus])
                : option}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function toggleOption(values: readonly string[], option: string) {
  return values.includes(option)
    ? values.filter((value) => value !== option)
    : [...values, option];
}

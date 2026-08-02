import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import type {
  ToolMarketFilters,
  ToolMarketInstallationStatus,
} from "../model/toolMarket";

type FilterGroup = "authors" | "runtimes" | "platforms" | "statuses";

const FILTER_GROUPS: readonly FilterGroup[] = ["authors", "runtimes", "platforms", "statuses"];
const STATUSES: readonly ToolMarketInstallationStatus[] = [
  "not-installed", "installed", "update-available", "call-name-conflict",
];
const GROUP_LABELS: Record<FilterGroup, TranslationKey> = {
  authors: "toolMarket.filterGroups.authors",
  runtimes: "toolMarket.filterGroups.runtimes",
  platforms: "toolMarket.filterGroups.platforms",
  statuses: "toolMarket.filterGroups.statuses",
};
const STATUS_LABELS: Record<ToolMarketInstallationStatus, TranslationKey> = {
  "not-installed": "toolMarket.statuses.not-installed",
  installed: "toolMarket.statuses.installed",
  "update-available": "toolMarket.statuses.update-available",
  "call-name-conflict": "toolMarket.statuses.call-name-conflict",
};

export function ToolMarketFilterPanel({
  authors, filters, onChange, platforms, runtimes,
}: {
  authors: readonly string[];
  filters: ToolMarketFilters;
  onChange: (filters: ToolMarketFilters) => void;
  platforms: readonly string[];
  runtimes: readonly string[];
}) {
  const { t } = useI18n();
  const [activeGroup, setActiveGroup] = useState<FilterGroup>("authors");
  const options = useMemo<readonly string[]>(() => {
    if (activeGroup === "authors") return authors;
    if (activeGroup === "runtimes") return runtimes;
    if (activeGroup === "platforms") return platforms;
    return STATUSES;
  }, [activeGroup, authors, platforms, runtimes]);
  const selected: readonly string[] = filters[activeGroup];

  const updateSelected = (values: string[]) => {
    if (activeGroup === "statuses") {
      onChange({ ...filters, statuses: values as ToolMarketInstallationStatus[] });
      return;
    }
    onChange({ ...filters, [activeGroup]: values });
  };

  return (
    <div className="theme-market-filter-panel">
      <nav className="theme-market-filter-panel__groups" aria-label={t("toolMarket.filterPanelAria")}>
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
            {t("toolMarket.filters.all")}
          </button>
          {options.map((option) => (
            <button
              className={selected.includes(option) ? "is-active" : undefined}
              key={option}
              type="button"
              onClick={() => updateSelected(toggleOption(selected, option))}
            >
              {activeGroup === "statuses"
                ? t(STATUS_LABELS[option as ToolMarketInstallationStatus])
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

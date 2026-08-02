import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import type {
  RoleMarketFilters,
  RoleMarketInstallationStatus,
} from "../model/roleMarket";

type RoleMarketFilterPanelProps = {
  authors: readonly string[];
  filters: RoleMarketFilters;
  onChange: (filters: RoleMarketFilters) => void;
};

type FilterGroup = "authors" | "statuses";

const FILTER_GROUPS: readonly FilterGroup[] = ["authors", "statuses"];
const STATUSES: readonly RoleMarketInstallationStatus[] = [
  "not-installed",
  "installed",
  "update-available",
];
const GROUP_LABELS: Record<FilterGroup, TranslationKey> = {
  authors: "roleMarket.filterGroups.authors",
  statuses: "roleMarket.filterGroups.statuses",
};
const STATUS_LABELS: Record<RoleMarketInstallationStatus, TranslationKey> = {
  "not-installed": "roleMarket.statuses.not-installed",
  installed: "roleMarket.statuses.installed",
  "update-available": "roleMarket.statuses.update-available",
};

export function RoleMarketFilterPanel({
  authors,
  filters,
  onChange,
}: RoleMarketFilterPanelProps) {
  const { t } = useI18n();
  const [activeGroup, setActiveGroup] = useState<FilterGroup>("authors");
  const options = useMemo<readonly string[]>(
    () => activeGroup === "authors" ? authors : STATUSES,
    [activeGroup, authors],
  );
  const selected: readonly string[] = filters[activeGroup];

  const updateSelected = (values: string[]) => {
    if (activeGroup === "authors") {
      onChange({ ...filters, authors: values });
    } else {
      onChange({ ...filters, statuses: values as RoleMarketInstallationStatus[] });
    }
  };

  return (
    <div className="theme-market-filter-panel">
      <nav
        className="theme-market-filter-panel__groups"
        aria-label={t("roleMarket.filterPanelAria")}
      >
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
            {t("roleMarket.filters.all")}
          </button>
          {options.map((option) => (
            <button
              className={selected.includes(option) ? "is-active" : undefined}
              key={option}
              type="button"
              onClick={() => updateSelected(toggleOption(selected, option))}
            >
              {activeGroup === "statuses"
                ? t(STATUS_LABELS[option as RoleMarketInstallationStatus])
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

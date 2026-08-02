import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import type {
  ThemeMarketFilters,
  ThemeMarketInstallationStatus,
  ThemeMarketMode,
} from "../model/themeMarket";

type ThemeMarketFilterPanelProps = {
  authors: readonly string[];
  baseColors: readonly string[];
  filters: ThemeMarketFilters;
  onChange: (filters: ThemeMarketFilters) => void;
};

type FilterGroup = "modes" | "authors" | "baseColors" | "statuses";

const FILTER_GROUPS: readonly FilterGroup[] = ["modes", "authors", "baseColors", "statuses"];
const MODES: readonly ThemeMarketMode[] = ["dark", "light"];
const STATUSES: readonly ThemeMarketInstallationStatus[] = [
  "not-installed",
  "installed",
  "update-available",
];
const MODE_LABELS: Record<ThemeMarketMode, TranslationKey> = {
  dark: "themeMarket.filters.dark",
  light: "themeMarket.filters.light",
};
const STATUS_LABELS: Record<ThemeMarketInstallationStatus, TranslationKey> = {
  "not-installed": "themeMarket.statuses.not-installed",
  installed: "themeMarket.statuses.installed",
  "update-available": "themeMarket.statuses.update-available",
};
const BASE_COLOR_LABELS: Record<string, TranslationKey> = {
  black: "themeMarket.baseColors.black",
  white: "themeMarket.baseColors.white",
  gray: "themeMarket.baseColors.gray",
  red: "themeMarket.baseColors.red",
  orange: "themeMarket.baseColors.orange",
  gold: "themeMarket.baseColors.gold",
  green: "themeMarket.baseColors.green",
  cyan: "themeMarket.baseColors.cyan",
  blue: "themeMarket.baseColors.blue",
  purple: "themeMarket.baseColors.purple",
  pink: "themeMarket.baseColors.pink",
  brown: "themeMarket.baseColors.brown",
};
const GROUP_LABELS: Record<FilterGroup, TranslationKey> = {
  modes: "themeMarket.filterGroups.modes",
  authors: "themeMarket.filterGroups.authors",
  baseColors: "themeMarket.filterGroups.baseColors",
  statuses: "themeMarket.filterGroups.statuses",
};

export function ThemeMarketFilterPanel({
  authors,
  baseColors,
  filters,
  onChange,
}: ThemeMarketFilterPanelProps) {
  const { t } = useI18n();
  const [activeGroup, setActiveGroup] = useState<FilterGroup>("modes");
  const options = useMemo<readonly string[]>(() => {
    if (activeGroup === "modes") return MODES;
    if (activeGroup === "statuses") return STATUSES;
    return activeGroup === "authors" ? authors : baseColors;
  }, [activeGroup, authors, baseColors]);
  const selected: readonly string[] = filters[activeGroup];

  const updateSelected = (values: string[]) => {
    if (activeGroup === "modes") {
      onChange({ ...filters, modes: values as ThemeMarketMode[] });
    } else if (activeGroup === "statuses") {
      onChange({ ...filters, statuses: values as ThemeMarketInstallationStatus[] });
    } else if (activeGroup === "authors") {
      onChange({ ...filters, authors: values });
    } else {
      onChange({ ...filters, baseColors: values });
    }
  };

  const optionLabel = (option: string) => {
    if (activeGroup === "modes") return t(MODE_LABELS[option as ThemeMarketMode]);
    if (activeGroup === "statuses") {
      return t(STATUS_LABELS[option as ThemeMarketInstallationStatus]);
    }
    if (activeGroup === "baseColors" && BASE_COLOR_LABELS[option]) {
      return t(BASE_COLOR_LABELS[option]);
    }
    return option;
  };

  return (
    <div className="theme-market-filter-panel">
      <nav className="theme-market-filter-panel__groups" aria-label={t("themeMarket.filterPanelAria")}>
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
            {t("themeMarket.filters.all")}
          </button>
          {options.map((option) => (
            <button
              className={selected.includes(option) ? "is-active" : undefined}
              key={option}
              type="button"
              onClick={() => updateSelected(toggleOption(selected, option))}
            >
              {optionLabel(option)}
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

import { useMemo, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import type {
  ProjectMarketFilters,
  ProjectMarketInstallationStatus,
  ProjectMarketNamespace,
} from "../model/projectMarket";

type FilterGroup = "authors" | "tags" | "statuses";

const GROUPS: readonly FilterGroup[] = ["authors", "tags", "statuses"];
const STATUSES: readonly ProjectMarketInstallationStatus[] = ["not-installed", "installed"];
export function ProjectMarketFilterPanel({
  authors,
  filters,
  namespace,
  onChange,
  tags,
}: {
  authors: readonly string[];
  filters: ProjectMarketFilters;
  namespace: ProjectMarketNamespace;
  onChange: (filters: ProjectMarketFilters) => void;
  tags: readonly string[];
}) {
  const { t } = useI18n();
  const [activeGroup, setActiveGroup] = useState<FilterGroup>("authors");
  const options = useMemo<readonly string[]>(() => {
    if (activeGroup === "authors") return authors;
    if (activeGroup === "tags") return tags;
    return STATUSES;
  }, [activeGroup, authors, tags]);
  const selected: readonly string[] = filters[activeGroup];
  const groupLabel = (group: FilterGroup) =>
    `${namespace}.filterGroups.${group}` as TranslationKey;
  const updateSelected = (values: string[]) => {
    if (activeGroup === "statuses") {
      onChange({ ...filters, statuses: values as ProjectMarketInstallationStatus[] });
      return;
    }
    onChange({ ...filters, [activeGroup]: values });
  };

  return (
    <div className="project-market-filter-panel">
      <nav aria-label={t(`${namespace}.filterPanelAria` as TranslationKey)}>
        {GROUPS.map((group) => (
          <button
            className={group === activeGroup ? "is-active" : undefined}
            key={group}
            onClick={() => setActiveGroup(group)}
            type="button"
          >
            <span>{t(groupLabel(group))}</span>
            {filters[group].length ? <small>{filters[group].length}</small> : null}
          </button>
        ))}
      </nav>
      <section>
        <strong>{t(groupLabel(activeGroup))}</strong>
        <div>
          <button
            className={selected.length === 0 ? "is-active" : undefined}
            onClick={() => updateSelected([])}
            type="button"
          >
            {t(`${namespace}.filters.all` as TranslationKey)}
          </button>
          {options.map((option) => (
            <button
              className={selected.includes(option) ? "is-active" : undefined}
              key={option}
              onClick={() => updateSelected(toggleOption(selected, option))}
              type="button"
            >
              {activeGroup === "statuses"
                ? t(`${namespace}.statuses.${option}` as TranslationKey)
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

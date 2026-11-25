import { useEffect, useId, useRef, useState } from "react";
import { MagnifyingGlass, X } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";

type ProjectOverviewHeaderSearchProps = {
  activeCount: number;
  idleCount: number;
  errorCount: number;
};

export function ProjectOverviewHeaderSearch({
  activeCount,
  idleCount,
  errorCount,
}: ProjectOverviewHeaderSearchProps) {
  const { t } = useI18n();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (expanded) inputRef.current?.focus({ preventScroll: true });
  }, [expanded]);

  function closeSearch() {
    setExpanded(false);
    buttonRef.current?.focus({ preventScroll: true });
  }

  return (
    <div
      className="project-category-overview__header-search"
      data-expanded={expanded}
      onKeyDown={(event) => {
        if (event.key === "Escape" && expanded) {
          event.preventDefault();
          event.stopPropagation();
          closeSearch();
        }
      }}
    >
      <div
        className="project-category-overview__totals"
        aria-label={t("projectOverview.totalsAria")}
        aria-hidden={expanded}
      >
        <span className="project-category-overview__total project-category-overview__total--running">
          {t("projectOverview.activeSessions", { count: activeCount })}
        </span>
        <span className="project-category-overview__total project-category-overview__total--idle">
          {t("projectOverview.idleSessions", { count: idleCount })}
        </span>
        <span className="project-category-overview__total project-category-overview__total--error">
          {t("projectOverview.errorSessions", { count: errorCount })}
        </span>
      </div>
      <div className="project-category-overview__search-field" inert={!expanded}>
        {/* Presentation only: typing does not filter projects or issue requests. */}
        <input
          id={inputId}
          ref={inputRef}
          type="text"
          autoComplete="off"
          aria-label={t("common.actions.search")}
          placeholder={t("common.actions.search")}
          className="project-category-overview__search-input"
        />
        <button
          type="button"
          className="project-category-overview__search-close"
          aria-label={t("common.actions.close")}
          title={t("common.actions.close")}
          onClick={closeSearch}
        >
          <X size={13} weight="bold" aria-hidden="true" />
        </button>
      </div>
      <button
        ref={buttonRef}
        type="button"
        className="project-category-overview__search-toggle"
        aria-label={t("common.actions.search")}
        title={t("common.actions.search")}
        aria-expanded={expanded}
        aria-controls={inputId}
        onClick={() => {
          if (expanded) inputRef.current?.focus({ preventScroll: true });
          else setExpanded(true);
        }}
      >
        <MagnifyingGlass size={15} weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}

import {
  ArrowClockwise,
  Funnel,
  LinkSimple,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { useEffect, useId, useRef } from "react";
import type { FormEvent, ReactNode } from "react";
import "./online-market-board-controls.css";

export type OnlineMarketBoardClasses = {
  button: string;
  content: string;
  error: string;
  filter: string;
  grid: string;
  input: string;
  primaryButton: string;
  refresh: string;
  search: string;
  source: string;
  state: string;
  status: string;
  toolbar: string;
  tools: string;
};

export const THEME_MARKET_BOARD_CLASSES: OnlineMarketBoardClasses = {
  button: "theme-market-board__button",
  content: "theme-market-board__content",
  error: "theme-market-board__error",
  filter: "theme-market-board__filter-button",
  grid: "theme-market-board__grid",
  input: "theme-market-board__source-input",
  primaryButton: "theme-market-board__button--primary",
  refresh: "theme-market-board__refresh",
  search: "theme-market-board__search",
  source: "theme-market-board__source",
  state: "theme-market-board__state",
  status: "theme-market-board__status",
  toolbar: "theme-market-board__toolbar",
  tools: "theme-market-board__filters",
};

export const PROJECT_MARKET_BOARD_CLASSES: OnlineMarketBoardClasses = {
  button: "project-market-board__button",
  content: "project-market-board__content",
  error: "project-market-board__error",
  filter: "project-market-board__filter",
  grid: "project-market-board__grid",
  input: "project-market-board__input",
  primaryButton: "project-market-board__button--primary",
  refresh: "project-market-board__refresh",
  search: "project-market-board__search",
  source: "project-market-board__source",
  state: "project-market-board__empty",
  status: "project-market-board__status",
  toolbar: "project-market-board__toolbar",
  tools: "project-market-board__tools",
};

export function normalizeOnlineMarketSourceText(source: string): string {
  return source.trim().replace(/\/+$/, "").replace(/\.git$/i, "");
}

export type OnlineMarketSourceFormProps = {
  actions?: ReactNode;
  classes: OnlineMarketBoardClasses;
  connectText: string;
  connectingText: string;
  draftSource: string;
  inputId: string;
  isLoading: boolean;
  selector: ReactNode;
  onConnect: () => void;
  onDraftSourceChange: (source: string) => void;
  placeholder: string;
  refreshText: string;
  source: string;
  readOnly?: boolean;
};

export function OnlineMarketSourceForm({
  actions,
  classes,
  connectText,
  connectingText,
  draftSource,
  inputId,
  isLoading,
  selector,
  onConnect,
  onDraftSourceChange,
  placeholder,
  refreshText,
  readOnly = false,
  source,
}: OnlineMarketSourceFormProps) {
  const normalizedDraft = normalizeOnlineMarketSourceText(draftSource);
  const displaySource = normalizedDraft.replace(/^https?:\/\/(?:www\.)?/i, "");
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onConnect();
  };

  return (
    <form
      className={`${classes.source} online-market-source-form${readOnly ? " online-market-source-form--readonly" : ""}`}
      onSubmit={handleSubmit}
    >
      {selector}
      <div className={`${classes.input} online-market-source-form__input`}>
        <LinkSimple size={15} aria-hidden="true" />
        {readOnly ? (
          <span
            aria-label={placeholder}
            aria-readonly="true"
            className="online-market-source-form__address-text"
            id={inputId}
            role="textbox"
            title={normalizedDraft}
          >
            {displaySource}
          </span>
        ) : (
          <input
            autoComplete="off"
            aria-label={placeholder}
            disabled={isLoading}
            id={inputId}
            onChange={(event) => onDraftSourceChange(event.target.value)}
            placeholder={placeholder}
            spellCheck={false}
            type="url"
            value={draftSource}
          />
        )}
      </div>
      <button
        className={`${classes.button} ${classes.primaryButton} online-market-source-form__button`}
        disabled={isLoading || !normalizedDraft}
        type="submit"
      >
        {isLoading
          ? connectingText
          : normalizedDraft === normalizeOnlineMarketSourceText(source)
            ? refreshText
            : connectText}
      </button>
      {actions}
    </form>
  );
}

export type OnlineMarketToolbarProps = {
  activeFilterCount: number;
  classes: OnlineMarketBoardClasses;
  filterOpen: boolean;
  filterText: string;
  filterPanel?: ReactNode;
  isLoading: boolean;
  onFilterToggle: () => void;
  onQueryChange: (query: string) => void;
  onRefresh: () => void;
  query: string;
  refreshText: string;
  searchPlaceholder: string;
  status: ReactNode;
};

export function OnlineMarketToolbar({
  activeFilterCount,
  classes,
  filterOpen,
  filterText,
  filterPanel,
  isLoading,
  onFilterToggle,
  onQueryChange,
  onRefresh,
  query,
  refreshText,
  searchPlaceholder,
  status,
}: OnlineMarketToolbarProps) {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);
  const filterPanelId = useId();

  useEffect(() => {
    if (!filterOpen || !filterPanel) return undefined;

    const handleOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && toolbarRef.current?.contains(event.target)) return;
      onFilterToggle();
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onFilterToggle();
      filterButtonRef.current?.focus();
    };
    document.addEventListener("pointerdown", handleOutsidePointer);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handleOutsidePointer);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [filterOpen, filterPanel, onFilterToggle]);

  return (
    <div className={`${classes.toolbar} online-market-toolbar`} ref={toolbarRef}>
      <div className={classes.status} aria-live="polite">{status}</div>
      <div className={classes.tools}>
        <label className={classes.search}>
          <MagnifyingGlass size={14} aria-hidden="true" />
          <input
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={searchPlaceholder}
            type="search"
            value={query}
          />
        </label>
        <button
          aria-controls={filterOpen && filterPanel ? filterPanelId : undefined}
          aria-expanded={filterOpen}
          className={`${classes.filter}${filterOpen ? " is-active" : ""}`}
          onClick={onFilterToggle}
          ref={filterButtonRef}
          type="button"
        >
          <Funnel size={14} aria-hidden="true" />
          {filterText}
          {activeFilterCount ? <span>{activeFilterCount}</span> : null}
        </button>
        <button
          aria-label={refreshText}
          className={classes.refresh}
          disabled={isLoading}
          onClick={onRefresh}
          title={refreshText}
          type="button"
        >
          <ArrowClockwise size={16} aria-hidden="true" />
        </button>
      </div>
      {filterOpen && filterPanel ? (
        <div
          aria-label={filterText}
          className="online-market-filter-popover"
          id={filterPanelId}
          role="region"
        >
          {filterPanel}
        </div>
      ) : null}
    </div>
  );
}

export type OnlineMarketErrorProps = {
  classes: OnlineMarketBoardClasses;
  error: string | null;
  isLoading: boolean;
  onRetry: () => void;
  retryText: string;
};

export function OnlineMarketError({
  classes,
  error,
  isLoading,
  onRetry,
  retryText,
}: OnlineMarketErrorProps) {
  if (!error) return null;
  return (
    <div className={classes.error} role="alert">
      <span>{error}</span>
      <button disabled={isLoading} onClick={onRetry} type="button">{retryText}</button>
    </div>
  );
}

export type OnlineMarketContentProps = {
  children: ReactNode;
  classes: OnlineMarketBoardClasses;
  emptyText: string;
  hasError: boolean;
  hasIndex: boolean;
  hasItems: boolean;
  isLoading: boolean;
  loadingText: string;
  notConnectedText: string;
};

export function OnlineMarketContent({
  children,
  classes,
  emptyText,
  hasError,
  hasIndex,
  hasItems,
  isLoading,
  loadingText,
  notConnectedText,
}: OnlineMarketContentProps) {
  return (
    <div className={classes.content}>
      {isLoading && !hasIndex ? (
        <div className={classes.state}>{loadingText}</div>
      ) : hasIndex && hasItems ? (
        <div className={classes.grid}>{children}</div>
      ) : hasIndex ? (
        <div className={classes.state}>{emptyText}</div>
      ) : !hasError ? (
        <div className={classes.state}>{notConnectedText}</div>
      ) : null}
    </div>
  );
}

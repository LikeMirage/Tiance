import {
  CaretDown,
  Check,
  GithubLogo,
  GlobeHemisphereWest,
  LockKey,
  Plus,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getGithubConnection,
  type GithubConnectionStatus,
} from "../../../services/github/githubConnectionApi";
import { useI18n } from "../../../shared/i18n";
import { useWorkspaceNavigation } from "../../../shared/model/workspaceNavigation";
import { normalizeOnlineMarketSourceText } from "../../../shared/online-market/OnlineMarketBoardControls";
import "./online-market-source-selector.css";

type OnlineMarketSourceSelectorProps = {
  defaultSource: string;
  disabled: boolean;
  source: string;
  sourceLabel?: string;
  onSelectDefault: () => void;
  onSelectSource: (source: string) => void;
  onSelectRepository?: (repository: {
    defaultBranch: string;
    fullName: string;
  }) => void;
};

export function OnlineMarketSourceSelector({
  defaultSource,
  disabled,
  source,
  sourceLabel,
  onSelectDefault,
  onSelectRepository,
  onSelectSource,
}: OnlineMarketSourceSelectorProps) {
  const { t } = useI18n();
  const { openGithubSettings } = useWorkspaceNavigation();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const [open, setOpen] = useState(false);
  const [connection, setConnection] = useState<GithubConnectionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const normalizedSource = normalizeOnlineMarketSourceText(source);
  const normalizedDefault = normalizeOnlineMarketSourceText(defaultSource);
  const privateRepositories = useMemo(
    () => connection?.repositories.filter((repository) => repository.private) ?? [],
    [connection?.repositories],
  );
  const activeRepository = privateRepositories.find(
    (repository) => githubRepositorySource(repository.fullName) === normalizedSource,
  );
  const triggerLabel = normalizedSource === normalizedDefault
    ? t("onlineMarketSource.default")
    : sourceLabel ?? activeRepository?.fullName ?? t("onlineMarketSource.custom");

  const loadRepositories = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(false);
    try {
      setConnection(await getGithubConnection(controller.signal));
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  const toggleOpen = () => {
    if (disabled) return;
    setOpen((current) => {
      const next = !current;
      if (next) void loadRepositories();
      return next;
    });
  };

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  useEffect(() => () => requestRef.current?.abort(), []);

  return (
    <div className="online-market-source-selector" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="online-market-source-selector__trigger"
        disabled={disabled}
        onClick={toggleOpen}
        title={triggerLabel}
        type="button"
      >
        {activeRepository || sourceLabel
          ? <LockKey size={14} />
          : <GlobeHemisphereWest size={14} />}
        <span>{triggerLabel}</span>
        <CaretDown className={open ? "is-open" : ""} size={13} />
      </button>

      {open ? (
        <div className="online-market-source-selector__menu" role="menu">
          <button
            className="online-market-source-selector__item"
            onClick={() => {
              setOpen(false);
              onSelectDefault();
            }}
            role="menuitem"
            type="button"
          >
            <GlobeHemisphereWest size={15} />
            <span>
              <strong>{t("onlineMarketSource.default")}</strong>
              <small>{defaultSource}</small>
            </span>
            {normalizedSource === normalizedDefault ? <Check size={14} /> : null}
          </button>

          <div className="online-market-source-selector__group-label">
            {t("onlineMarketSource.privateRepositories")}
          </div>
          {loading ? (
            <div className="online-market-source-selector__state" role="status">
              {t("onlineMarketSource.loading")}
            </div>
          ) : error ? (
            <button
              className="online-market-source-selector__state online-market-source-selector__state--action"
              onClick={() => void loadRepositories()}
              type="button"
            >
              {t("onlineMarketSource.loadFailed")}
            </button>
          ) : !connection?.connected ? (
            <div className="online-market-source-selector__state">
              {t("onlineMarketSource.notConnected")}
            </div>
          ) : privateRepositories.length === 0 ? (
            <div className="online-market-source-selector__state">
              {t("onlineMarketSource.empty")}
            </div>
          ) : privateRepositories.map((repository) => {
            const repositorySource = githubRepositorySource(repository.fullName);
            return (
              <button
                className="online-market-source-selector__item"
                key={repository.id}
                onClick={() => {
                  setOpen(false);
                  if (onSelectRepository) {
                    onSelectRepository(repository);
                  } else {
                    onSelectSource(repositorySource);
                  }
                }}
                role="menuitem"
                type="button"
              >
                <GithubLogo size={15} />
                <span><strong>{repository.fullName}</strong></span>
                {repositorySource === normalizedSource ? <Check size={14} /> : null}
              </button>
            );
          })}

          <button
            className="online-market-source-selector__add"
            onClick={() => {
              setOpen(false);
              openGithubSettings();
            }}
            role="menuitem"
            type="button"
          >
            <Plus size={15} />
            {t("onlineMarketSource.addPrivateRepository")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function githubRepositorySource(fullName: string) {
  return normalizeOnlineMarketSourceText(`https://github.com/${fullName}`);
}

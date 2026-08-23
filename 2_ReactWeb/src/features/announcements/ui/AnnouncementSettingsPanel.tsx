import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";

import {
  checkAnnouncements,
  getAnnouncementContent,
  getAnnouncementSettings,
  getAnnouncementYear,
  markAnnouncementRead,
  resolveAnnouncementAssetUrl,
  updateAnnouncementSettings,
  type AnnouncementCheck,
  type AnnouncementContent,
  type AnnouncementItem,
  type AnnouncementYearIndex,
} from "../../../services/system/announcements";
import { useI18n } from "../../../shared/i18n";
import { HttpRequestError } from "../../../services/http/httpClient";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { SettingsViewStage } from "../../../shared/ui/settings-view-tabs/SettingsViewStage";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";
import "./announcement-settings.css";

type AnnouncementSettingsPanelProps = {
  active: boolean;
  onReady?: () => void;
};

type AnnouncementSettingsTab = "announcement" | "history" | "checking";

export function AnnouncementSettingsPanel({ active, onReady }: AnnouncementSettingsPanelProps) {
  const { t } = useI18n();
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [activeTab, setActiveTab] = useState<AnnouncementSettingsTab>("announcement");
  const [checkOnStartup, setCheckOnStartup] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<AnnouncementCheck | null>(null);
  const [yearIndex, setYearIndex] = useState<AnnouncementYearIndex | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [content, setContent] = useState<AnnouncementContent | null>(null);
  const [selectedAnnouncementId, setSelectedAnnouncementId] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [emptyCatalog, setEmptyCatalog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activatedRef = useRef(false);
  const contentRequestRef = useRef(0);
  const yearRequestRef = useRef(0);
  const selectionVersionRef = useRef(0);

  useEffect(() => onReady?.(), [onReady]);

  useEffect(() => {
    const controller = new AbortController();
    void getAnnouncementSettings(controller.signal)
      .then((result) => {
        setCheckOnStartup(result.checkOnStartup);
        setSettingsLoaded(true);
      })
      .catch((settingsError) => {
        if (!controller.signal.aborted) {
          setError(toErrorMessage(settingsError, t("announcements.loadFailed")));
        }
      });
    return () => controller.abort();
  }, [t]);

  const openAnnouncement = useCallback(async (
    item: AnnouncementItem,
    activateAnnouncementTab: boolean,
  ) => {
    const requestId = contentRequestRef.current + 1;
    contentRequestRef.current = requestId;
    if (activateAnnouncementTab) setActiveTab("announcement");
    setSelectedAnnouncementId(item.id);
    setContent(null);
    setLoadingContent(true);
    setError(null);
    try {
      const loaded = await getAnnouncementContent(item.id, item.revision);
      if (contentRequestRef.current !== requestId) return;
      setContent(loaded);
      if (!item.read) {
        try {
          await markAnnouncementRead(item.id, item.revision);
        } catch (readError) {
          if (contentRequestRef.current === requestId) {
            setError(toErrorMessage(readError, t("announcements.readFailed")));
          }
          return;
        }
        if (contentRequestRef.current !== requestId) return;
        setYearIndex((current) => current ? markItemRead(current, item.id, item.revision) : current);
        setCheck((current) => current ? {
          ...current,
          latest: current.latest.id === item.id
            ? { ...current.latest, read: true }
            : current.latest,
          latestUnread: current.latest.id === item.id ? false : current.latestUnread,
          latestYear: markItemRead(current.latestYear, item.id, item.revision),
        } : current);
      }
    } catch (contentError) {
      if (contentRequestRef.current === requestId) {
        setError(toErrorMessage(contentError, t("announcements.loadFailed")));
      }
    } finally {
      if (contentRequestRef.current === requestId) setLoadingContent(false);
    }
  }, [t]);

  const runCheck = useCallback(async (selectLatestAnnouncement: boolean) => {
    const selectionVersion = selectionVersionRef.current;
    setChecking(true);
    setEmptyCatalog(false);
    setError(null);
    try {
      const result = await checkAnnouncements();
      setCheck(result);
      const shouldLoadLatest = selectionVersionRef.current === selectionVersion && (
        selectLatestAnnouncement
        || content === null
        || (
          content.announcement.id === result.latest.id
          && content.announcement.revision !== result.latest.revision
        )
      );
      if (
        shouldLoadLatest
      ) {
        setSelectedYear(result.root.latestAnnouncementYear);
        setYearIndex(result.latestYear);
        await openAnnouncement(result.latest, false);
      } else if (
        selectedYear === null
        || selectedYear === result.root.latestAnnouncementYear
      ) {
        setSelectedYear(result.root.latestAnnouncementYear);
        setYearIndex(result.latestYear);
      }
    } catch (checkError) {
      if (
        checkError instanceof HttpRequestError
        && checkError.code === "announcement_catalog_empty"
      ) {
        setCheck(null);
        setYearIndex(null);
        setSelectedYear(null);
        setSelectedAnnouncementId(null);
        setContent(null);
        setEmptyCatalog(true);
      } else {
        setError(toAnnouncementErrorMessage(
          checkError,
          t("announcements.backendUnavailable"),
          t("announcements.checkFailed"),
        ));
      }
    } finally {
      setChecking(false);
    }
  }, [content, openAnnouncement, selectedYear, t]);

  useEffect(() => {
    if (!active || activatedRef.current) return;
    activatedRef.current = true;
    void runCheck(true);
  }, [active, runCheck]);

  const selectYear = async (year: number) => {
    if ((year === selectedYear && yearIndex !== null) || checking) return;
    const requestId = yearRequestRef.current + 1;
    yearRequestRef.current = requestId;
    selectionVersionRef.current += 1;
    setSelectedYear(year);
    setYearIndex(null);
    setError(null);
    try {
      const loaded = await getAnnouncementYear(year);
      if (yearRequestRef.current !== requestId) return;
      setYearIndex(loaded);
    } catch (yearError) {
      if (yearRequestRef.current === requestId) {
        setError(toErrorMessage(yearError, t("announcements.loadFailed")));
      }
    }
  };

  const showAnnouncement = (item: AnnouncementItem) => {
    selectionVersionRef.current += 1;
    void openAnnouncement(item, true);
  };

  const toggleStartupCheck = async () => {
    if (!settingsLoaded || savingSettings) return;
    setSavingSettings(true);
    setError(null);
    try {
      const updated = await updateAnnouncementSettings(!checkOnStartup);
      setCheckOnStartup(updated.checkOnStartup);
    } catch (settingsError) {
      setError(toErrorMessage(settingsError, t("announcements.saveFailed")));
    } finally {
      setSavingSettings(false);
    }
  };

  return (
    <div className="announcement-settings">
      <header className="announcement-settings__head">
        <h2>{t("announcements.title")}</h2>
      </header>

      <SettingsViewTabs
        activeView={activeTab}
        ariaLabel={t("announcements.tabsAria")}
        onChange={setActiveTab}
        tabs={announcementSettingsTabs.map((tab) => ({
          id: tab.id,
          label: t(tab.labelKey),
        }))}
      />

      {error ? <div className="announcement-settings__error" role="alert">{error}</div> : null}
      {check?.cached ? <div className="announcement-settings__offline">{t("announcements.cached")}</div> : null}

      <SettingsViewStage
        activeView={activeTab}
        className="announcement-settings__view-stage"
        keepLeavingView
        layout="fill"
        orderedViews={announcementSettingsViewOrder}
      >
        {activeTab === "announcement" ? (
        <section className="announcement-settings__viewer" role="tabpanel">
          {emptyCatalog ? (
            <div className="announcement-settings__empty">
              <strong>{t("announcements.emptyRepositoryTitle")}</strong>
              <span>{t("announcements.emptyRepositoryDescription")}</span>
            </div>
          ) : loadingContent || (checking && !content) ? (
            <div className="announcement-settings__placeholder">{t("announcements.loading")}</div>
          ) : content ? (
            <article className="announcement-settings__article">
              <header className="announcement-settings__article-head">
                <h3>{content.announcement.title}</h3>
                <time dateTime={content.announcement.publishedAt}>
                  {formatPublishedAt(content.announcement.publishedAt)}
                </time>
              </header>
              <div className="announcement-settings__content">
                <LazyMarkdownPreview
                  content={content.content}
                  resolveAssetUrl={(src) => resolveAnnouncementAssetUrl(content.announcement, src)}
                />
              </div>
            </article>
          ) : (
            <div className="announcement-settings__placeholder">{t("announcements.select")}</div>
          )}
        </section>
        ) : null}

        {activeTab === "history" ? (
        <section className="announcement-settings__history" role="tabpanel" aria-label={t("announcements.history")}>
          {emptyCatalog ? (
            <div className="announcement-settings__empty">
              <strong>{t("announcements.emptyRepositoryTitle")}</strong>
              <span>{t("announcements.emptyRepositoryDescription")}</span>
            </div>
          ) : (
            <>
              <nav className="announcement-settings__years" aria-label={t("announcements.years")}>
                {[...(check?.root.years ?? [])]
                  .sort((a, b) => b.year - a.year)
                  .map((item) => (
                    <button
                      key={item.year}
                      className={selectedYear === item.year ? "is-active" : ""}
                      disabled={checking}
                      type="button"
                      onClick={() => void selectYear(item.year)}
                    >
                      {item.year}
                    </button>
                  ))}
              </nav>

              {checking || (selectedYear !== null && !yearIndex) ? (
                <div className="announcement-settings__placeholder">{t("announcements.loading")}</div>
              ) : null}
              {!checking && !check && !error ? (
                <div className="announcement-settings__placeholder">{t("announcements.checkPrompt")}</div>
              ) : null}
              {yearIndex && yearIndex.announcements.length === 0 ? (
                <div className="announcement-settings__placeholder">{t("announcements.empty")}</div>
              ) : null}

              <div className="announcement-settings__list">
                {yearIndex?.announcements.map((item) => {
                  const selected = selectedAnnouncementId === item.id;
                  return (
                    <button
                      className={selected
                        ? "announcement-settings__item-button announcement-settings__item-button--selected"
                        : "announcement-settings__item-button"}
                      key={`${item.id}-${item.revision}`}
                      type="button"
                      onClick={() => showAnnouncement(item)}
                    >
                      <span className="announcement-settings__item-copy">
                        <strong>{item.title}</strong>
                        <time dateTime={item.publishedAt}>{formatPublishedAt(item.publishedAt)}</time>
                      </span>
                      <span className="announcement-settings__item-state">
                        {!item.read ? <i>{t("announcements.unread")}</i> : null}
                        {item.status === "withdrawn" ? <em>{t("announcements.withdrawn")}</em> : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </section>
        ) : null}

        {activeTab === "checking" ? (
        <section className="announcement-settings__checking" role="tabpanel">
          <div className="announcement-settings__preference">
            <div>
              <strong>{t("announcements.autoCheck")}</strong>
              <span>{t("announcements.autoCheckDescription")}</span>
            </div>
            <button
              aria-checked={checkOnStartup}
              aria-label={t("announcements.autoCheck")}
              className={checkOnStartup
                ? "announcement-settings__toggle announcement-settings__toggle--on"
                : "announcement-settings__toggle"}
              disabled={!settingsLoaded || savingSettings}
              role="switch"
              type="button"
              onClick={() => void toggleStartupCheck()}
            >
              <i aria-hidden="true" />
            </button>
          </div>
          <div className="announcement-settings__manual-check">
            <div>
              <strong>{t("announcements.manualCheck")}</strong>
              <span>{t("announcements.lastChecked")}: {formatOptionalDate(check?.lastSuccessfulCheckAt, t("announcements.never"))}</span>
            </div>
            <button
              className="announcement-settings__refresh"
              type="button"
              disabled={checking}
              onClick={() => void runCheck(false)}
            >
              <ArrowClockwise size={16} />
              {checking ? t("announcements.checking") : t("announcements.check")}
            </button>
          </div>
        </section>
        ) : null}
      </SettingsViewStage>
    </div>
  );
}

const announcementSettingsTabs = [
  { id: "announcement", labelKey: "announcements.announcementTab" },
  { id: "history", labelKey: "announcements.history" },
  { id: "checking", labelKey: "announcements.checkingTab" },
] as const satisfies ReadonlyArray<{
  id: AnnouncementSettingsTab;
  labelKey: "announcements.announcementTab" | "announcements.history" | "announcements.checkingTab";
}>;

const announcementSettingsViewOrder: readonly AnnouncementSettingsTab[] = [
  "announcement",
  "history",
  "checking",
];

function markItemRead(index: AnnouncementYearIndex, id: string, revision: number) {
  return {
    ...index,
    announcements: index.announcements.map((item) =>
      item.id === id && item.revision === revision ? { ...item, read: true } : item,
    ),
  };
}

function formatPublishedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatOptionalDate(value: string | null | undefined, fallback: string) {
  return value ? formatPublishedAt(value) : fallback;
}

function toErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function toAnnouncementErrorMessage(
  error: unknown,
  backendUnavailable: string,
  fallback: string,
) {
  if (error instanceof HttpRequestError && error.status === 404) {
    return backendUnavailable;
  }
  return toErrorMessage(error, fallback);
}

import { useEffect, useState } from "react";
import { ArrowClockwise, DownloadSimple, GitBranch, GithubLogo, Package } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import {
  LATEST_SOFTWARE_DOWNLOAD_URL,
  OPEN_SOURCE_REPOSITORY_URL,
} from "../../../services/system/softwareUpdate";
import { useSoftwareUpdate } from "../model/useSoftwareUpdate";
import {
  isAutomaticSoftwareUpdateCheckEnabled,
  setAutomaticSoftwareUpdateCheckEnabled,
} from "../model/softwareUpdatePreferences";
import "./software-update.css";

type SoftwareUpdatePanelProps = { onReady?: () => void };

export function SoftwareUpdatePanel({ onReady }: SoftwareUpdatePanelProps) {
  const { t } = useI18n();
  const softwareUpdate = useSoftwareUpdate();
  const [automaticCheckEnabled, setAutomaticCheckEnabled] = useState(
    isAutomaticSoftwareUpdateCheckEnabled,
  );

  useEffect(() => onReady?.(), [onReady]);

  const update = softwareUpdate.update;
  const busy = softwareUpdate.state !== "idle";
  return (
    <div className="software-update">
      <header className="software-update__head">
        <h2>{t("softwareUpdate.title")}</h2>
        <div className="software-update__head-actions">
          <nav className="software-update__links" aria-label={t("softwareUpdate.linksAria")}>
            <a href={OPEN_SOURCE_REPOSITORY_URL} target="_blank" rel="noreferrer">
              <GithubLogo size={17} />
              <span>{t("softwareUpdate.sourceLink")}</span>
            </a>
            <a href={LATEST_SOFTWARE_DOWNLOAD_URL} target="_blank" rel="noreferrer">
              <DownloadSimple size={17} />
              <span>{t("softwareUpdate.downloadLink")}</span>
            </a>
          </nav>
          <button
            className="software-update__button"
            type="button"
            disabled={busy}
            onClick={() => void softwareUpdate.check()}
          >
            <ArrowClockwise size={16} />
            {softwareUpdate.state === "checking" ? t("softwareUpdate.checking") : t("softwareUpdate.check")}
          </button>
        </div>
      </header>

      <section className="software-update__preference">
        <strong>{t("softwareUpdate.autoCheck.title")}</strong>
        <button
          aria-checked={automaticCheckEnabled}
          aria-label={t("softwareUpdate.autoCheck.title")}
          className={
            automaticCheckEnabled
              ? "software-update__toggle software-update__toggle--on"
              : "software-update__toggle"
          }
          role="switch"
          type="button"
          onClick={() => {
            const enabled = !automaticCheckEnabled;
            setAutomaticCheckEnabled(enabled);
            setAutomaticSoftwareUpdateCheckEnabled(enabled);
          }}
        >
          <i aria-hidden="true" />
        </button>
      </section>

      {softwareUpdate.error ? <div className="software-update__error" role="alert">{softwareUpdate.error}</div> : null}

      {update ? (
        <section className="software-update__card">
          <div className="software-update__versions">
            <div className="software-update__current-version">
              <Package size={22} />
              <div>
                <strong>{t("softwareUpdate.current")}</strong>
                <span>Tiance v{update.currentVersion}</span>
              </div>
            </div>
            {update.updateAvailable ? (
              <div className="software-update__version software-update__version--available">
                <span>{t("softwareUpdate.available")}</span>
                <strong>v{update.latestVersion}</strong>
              </div>
            ) : null}
            {update.updateAvailable && update.downloadSize ? (
              <div className="software-update__version">
                <span>{t("softwareUpdate.size")}</span>
                <strong>{formatBytes(update.downloadSize)}</strong>
              </div>
            ) : null}
            {update.updateAvailable && !update.sourceCheckout ? (
              <button
                className="software-update__button software-update__button--primary"
                type="button"
                disabled={busy}
                onClick={() => void softwareUpdate.install()}
              >
                <DownloadSimple size={17} />
                {softwareUpdate.state === "downloading"
                  ? t("softwareUpdate.downloading")
                  : softwareUpdate.state === "installing"
                    ? t("softwareUpdate.installing")
                    : t("softwareUpdate.install")}
              </button>
            ) : null}
          </div>

          {update.sourceCheckout ? (
            <div className="software-update__notice">
              <GitBranch size={20} />
              <div><strong>{t("softwareUpdate.sourceTitle")}</strong><span>{t("softwareUpdate.sourceDescription")}</span></div>
            </div>
          ) : null}

          {update.releaseNotes ? (
            <div className="software-update__notes">
              <h3>
                {t("softwareUpdate.notes")}
                <span>v{update.updateAvailable ? update.latestVersion : update.currentVersion}</span>
              </h3>
              <div className="software-update__notes-body">
                <LazyMarkdownPreview content={update.releaseNotes} />
              </div>
            </div>
          ) : null}
        </section>
      ) : softwareUpdate.state === "checking" ? (
        <div className="software-update__loading" role="status">{t("softwareUpdate.checking")}</div>
      ) : null}
    </div>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

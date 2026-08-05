import { useEffect } from "react";
import { ArrowClockwise, ArrowSquareOut, DownloadSimple, GitBranch, GithubLogo, Package } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import {
  LATEST_SOFTWARE_DOWNLOAD_URL,
  OPEN_SOURCE_REPOSITORY_URL,
} from "../../../services/system/softwareUpdate";
import { useSoftwareUpdate } from "../model/useSoftwareUpdate";
import "./software-update.css";

type SoftwareUpdatePanelProps = { onReady?: () => void };

export function SoftwareUpdatePanel({ onReady }: SoftwareUpdatePanelProps) {
  const { t } = useI18n();
  const softwareUpdate = useSoftwareUpdate();

  useEffect(() => onReady?.(), [onReady]);

  const update = softwareUpdate.update;
  const busy = softwareUpdate.state !== "idle";
  return (
    <div className="software-update">
      <header className="software-update__head">
        <div>
          <h2>{t("softwareUpdate.title")}</h2>
          <p>{t("softwareUpdate.description")}</p>
        </div>
        <button
          className="software-update__button"
          type="button"
          disabled={busy}
          onClick={() => void softwareUpdate.check()}
        >
          <ArrowClockwise size={16} />
          {softwareUpdate.state === "checking" ? t("softwareUpdate.checking") : t("softwareUpdate.check")}
        </button>
      </header>

      {softwareUpdate.error ? <div className="software-update__error" role="alert">{softwareUpdate.error}</div> : null}

      <nav className="software-update__links" aria-label={t("softwareUpdate.linksAria")}>
        <a href={OPEN_SOURCE_REPOSITORY_URL} target="_blank" rel="noreferrer">
          <GithubLogo size={17} />
          <span>{t("softwareUpdate.sourceLink")}</span>
          <ArrowSquareOut size={14} />
        </a>
        <a href={LATEST_SOFTWARE_DOWNLOAD_URL} target="_blank" rel="noreferrer">
          <DownloadSimple size={17} />
          <span>{t("softwareUpdate.downloadLink")}</span>
          <ArrowSquareOut size={14} />
        </a>
      </nav>

      {update ? (
        <section className="software-update__card">
          <div className="software-update__versions">
            <div><span>{t("softwareUpdate.current")}</span><strong>v{update.currentVersion}</strong></div>
            <div><span>{t("softwareUpdate.latest")}</span><strong>v{update.latestVersion}</strong></div>
            {update.downloadSize ? <div><span>{t("softwareUpdate.size")}</span><strong>{formatBytes(update.downloadSize)}</strong></div> : null}
          </div>

          {update.sourceCheckout ? (
            <div className="software-update__notice">
              <GitBranch size={20} />
              <div><strong>{t("softwareUpdate.sourceTitle")}</strong><span>{t("softwareUpdate.sourceDescription")}</span></div>
            </div>
          ) : update.updateAvailable ? (
            <div className="software-update__notice software-update__notice--available">
              <Package size={20} />
              <div><strong>{t("softwareUpdate.available")}</strong><span>{update.releaseName}</span></div>
            </div>
          ) : (
            <div className="software-update__notice">
              <Package size={20} />
              <div><strong>{t("softwareUpdate.upToDate")}</strong><span>{t("softwareUpdate.upToDateDescription")}</span></div>
            </div>
          )}

          {update.releaseNotes ? (
            <div className="software-update__notes">
              <h3>{t("softwareUpdate.notes")}</h3>
              <div>{update.releaseNotes}</div>
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

import { useEffect } from "react";

import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { useI18n } from "../../../shared/i18n";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { useSoftwareUpdate } from "../model/useSoftwareUpdate";
import { isAutomaticSoftwareUpdateCheckEnabled } from "../model/softwareUpdatePreferences";
import "./startup-software-update-prompt.css";

export function StartupSoftwareUpdatePrompt() {
  const { t } = useI18n();
  const softwareUpdate = useSoftwareUpdate(false);
  const { update, state: phase, error, prompt, checkOnStartup } = softwareUpdate;

  useEffect(() => {
    if (!isAutomaticSoftwareUpdateCheckEnabled()) return;
    void checkOnStartup();
  }, [checkOnStartup]);

  if (!update || !prompt) return null;

  const busy = phase === "downloading" || phase === "installing";
  if (prompt === "restart") {
    return (
      <ConfirmModal
        showClose
        closeLabel={t("announcements.close")}
        cancelLabel={t("softwareUpdate.restart.later")}
        cancelDisabled={phase === "installing"}
        confirmDisabled={busy}
        confirmLabel={phase === "installing" ? t("softwareUpdate.installing") : t("softwareUpdate.restart.now")}
        title={t("softwareUpdate.restart.title")}
        message={t("softwareUpdate.restart.message", { version: softwareUpdate.download?.version ?? update.latestVersion })}
        onCancel={softwareUpdate.dismiss}
        onConfirm={() => void softwareUpdate.restart()}
      >
        {error ? <p className="software-update-prompt__error" role="alert">{error}</p> : null}
      </ConfirmModal>
    );
  }

  return (
    <ConfirmModal
      showClose
      closeLabel={t("announcements.close")}
      cancelLabel={t("announcements.close")}
      confirmDisabled={busy}
      confirmLabel={
        phase === "downloading"
          ? t("softwareUpdate.downloading")
          : phase === "installing"
            ? t("softwareUpdate.installing")
            : t("softwareUpdate.prompt.update")
      }
      dialogClassName="software-update-prompt"
      message={update.releaseName}
      onCancel={softwareUpdate.dismiss}
      onConfirm={() => void softwareUpdate.install()}
      title={t("softwareUpdate.prompt.title")}
    >
      <div className="software-update-prompt__versions">
        <div>
          <span>{t("softwareUpdate.current")}</span>
          <strong>v{update.currentVersion}</strong>
        </div>
        <div>
          <span>{t("softwareUpdate.latest")}</span>
          <strong>v{update.latestVersion}</strong>
        </div>
      </div>
      <section className="software-update-prompt__notes">
        <h4>{t("softwareUpdate.notes")}</h4>
        <div className="software-update-prompt__notes-body">
          <LazyMarkdownPreview content={update.releaseNotes || t("softwareUpdate.prompt.noNotes")} />
        </div>
      </section>
      {error ? <p className="software-update-prompt__error" role="alert">{error}</p> : null}
    </ConfirmModal>
  );
}

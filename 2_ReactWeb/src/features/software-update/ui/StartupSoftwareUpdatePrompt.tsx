import { useEffect, useState } from "react";

import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { useI18n } from "../../../shared/i18n";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import {
  checkSoftwareUpdateOnStartup,
  installSoftwareUpdate,
  type SoftwareUpdateCheck,
  type SoftwareUpdateInstallPhase,
} from "../../../services/system/softwareUpdate";
import { isAutomaticSoftwareUpdateCheckEnabled } from "../model/softwareUpdatePreferences";
import "./startup-software-update-prompt.css";

export function StartupSoftwareUpdatePrompt() {
  const { t } = useI18n();
  const [update, setUpdate] = useState<SoftwareUpdateCheck | null>(null);
  const [phase, setPhase] = useState<SoftwareUpdateInstallPhase | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAutomaticSoftwareUpdateCheckEnabled()) return;
    let active = true;
    void checkSoftwareUpdateOnStartup()
      .then((result) => {
        if (active && result.updateAvailable && !result.sourceCheckout) setUpdate(result);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  if (!update) return null;

  const busy = phase !== null;
  const handleInstall = async () => {
    setError(null);
    try {
      await installSoftwareUpdate(setPhase);
    } catch (installError) {
      setError(toErrorMessage(installError));
      setPhase(null);
    }
  };

  return (
    <ConfirmModal
      cancelDisabled={busy}
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
      onCancel={() => setUpdate(null)}
      onConfirm={() => void handleInstall()}
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

function toErrorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : "软件更新操作失败。";
}

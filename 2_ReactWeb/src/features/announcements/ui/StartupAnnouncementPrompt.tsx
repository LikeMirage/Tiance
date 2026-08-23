import { useCallback, useEffect, useRef, useState } from "react";

import {
  checkAnnouncements,
  getAnnouncementContent,
  getAnnouncementSettings,
  markAnnouncementRead,
  resolveAnnouncementAssetUrl,
  type AnnouncementContent,
} from "../../../services/system/announcements";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { useI18n } from "../../../shared/i18n";
import "./announcements.css";

export function StartupAnnouncementPrompt() {
  const { t } = useI18n();
  const [announcement, setAnnouncement] = useState<AnnouncementContent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    void getAnnouncementSettings(controller.signal)
      .then(async (settings) => {
        if (!settings.checkOnStartup) return null;
        const result = await checkAnnouncements();
        if (!result.latestUnread || result.latest.status !== "published") return null;
        return getAnnouncementContent(result.latest.id, result.latest.revision, controller.signal);
      })
      .then((content) => {
        if (mountedRef.current && content) setAnnouncement(content);
      })
      .catch(() => undefined);
    return () => {
      mountedRef.current = false;
      controller.abort();
    };
  }, []);

  const handleClose = useCallback(async () => {
    if (!announcement || busy) return;
    setBusy(true);
    setError(null);
    try {
      await markAnnouncementRead(
        announcement.announcement.id,
        announcement.announcement.revision,
      );
      if (mountedRef.current) setAnnouncement(null);
    } catch (closeError) {
      if (mountedRef.current) {
        setError(toErrorMessage(closeError, t("announcements.readFailed")));
      }
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, [announcement, busy, t]);

  if (!announcement) return null;

  return (
    <ConfirmModal
      cancelDisabled={busy}
      closeOnBackdrop={false}
      confirmDisabled={busy}
      confirmLabel={busy ? t("announcements.savingRead") : t("announcements.close")}
      dialogClassName="announcement-prompt"
      message=""
      onCancel={() => void handleClose()}
      onConfirm={() => void handleClose()}
      showCancel={false}
      showHeader={false}
      title={announcement.announcement.title}
    >
      <div className="announcement-prompt__content">
        <header className="announcement-prompt__heading">
          <h1>{announcement.announcement.title}</h1>
          <time dateTime={announcement.announcement.publishedAt}>
            {formatPublishedAt(announcement.announcement.publishedAt)}
          </time>
        </header>
        <LazyMarkdownPreview
          content={announcement.content}
          resolveAssetUrl={(src) => resolveAnnouncementAssetUrl(announcement.announcement, src)}
        />
      </div>
      {error ? <p className="announcement-prompt__error" role="alert">{error}</p> : null}
    </ConfirmModal>
  );
}

function formatPublishedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function toErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

import { useEffect, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";
import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";

type Entry = { id: string; time: number; event: string; level: string; details: Record<string, string | number> };
type Page = { items: Entry[]; total: number; retention: number };
const size = 50;

export function TelegramActivityPanel({ connectionId, name, platform = "telegram" }: { connectionId: string | null; name: string; platform?: "telegram" | "feishu" | "wechat" }) {
  const { t, language } = useI18n();
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    setBusy(true); setError(null);
    const params = new URLSearchParams({ offset: String(offset), limit: String(size) });
    if (connectionId) params.set("connection_id", connectionId);
    const route = platform === "telegram" ? "telegram" : `platform/${platform}`;
    void fetchJson<Page>(`/api/mobile/${route}/logs?${params}`, { signal: abort.signal }).then(data => {
      if (!abort.signal.aborted) setPage(data);
    }).catch(cause => {
      if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    }).finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => abort.abort();
  }, [connectionId, offset, revision, platform]);
  return <section className="telegram-activity" aria-busy={busy}>
    <div className="telegram-activity__toolbar">
      <strong>{name || t("telegramAccess.logs.current")}</strong>
      <button type="button" disabled={busy} onClick={() => { setOffset(0); setRevision(value => value + 1); }}>{t("telegramAccess.logs.refresh")}</button>
    </div>
    <p className="telegram-access__hint">{t("telegramAccess.logs.hint")}</p>
    {error && <p role="alert" className="telegram-access__error">{error}</p>}
    {busy ? <p role="status">{t("telegramAccess.logs.loading")}</p> : !error && !page?.items.length ?
      <p>{t("telegramAccess.logs.empty")}</p> : null}
    {!busy && !error && !!page?.items.length && <div className="telegram-activity__table-wrap"><table>
      <thead><tr><th>{t("telegramAccess.logs.time")}</th><th>{t("telegramAccess.logs.event")}</th><th>{t("telegramAccess.logs.details")}</th></tr></thead>
      <tbody>{page.items.map(item => <tr key={item.id}>
        <td><time dateTime={new Date(item.time * 1000).toISOString()}>{new Date(item.time * 1000).toLocaleString(language)}</time></td>
        <td className={item.level === "error" ? "telegram-access__error" : undefined}>
          {t(`telegramAccess.events.${item.event}` as TranslationKey)}</td>
        <td>{Object.entries(item.details).map(([key, value]) => <div key={key}>
          <span>{t(`telegramAccess.details.${key}` as TranslationKey)}：</span><code>{value}</code>
        </div>)}</td>
      </tr>)}</tbody>
    </table></div>}
    <div className="telegram-activity__pager">
      <button type="button" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - size))}>{t("telegramAccess.logs.previous")}</button>
      <span>{Math.floor(offset / size) + 1} / {Math.max(1, Math.ceil((page?.total ?? 0) / size))}</span>
      <button type="button" disabled={busy || offset + size >= (page?.total ?? 0)} onClick={() => setOffset(value => value + size)}>{t("telegramAccess.logs.next")}</button>
    </div>
  </section>;
}

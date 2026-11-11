import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";
import { useI18n } from "../../../shared/i18n";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";
import "./telegram-access.css";

type Status = {
  connection_id: string | null;
  connections: { connection_id: string; name: string; username: string; enabled: boolean }[];
  enabled: boolean; has_token: boolean; api_base: string; error: string | null;
  desktop_online: boolean; pending_deliveries: number;
  bot: { username?: string; first_name: string } | null;
  peers: { id: string; user_id: number; name: string; username?: string; allowed: boolean; reviewed: boolean }[];
};

type Props = { active?: boolean; onConnection?: (id: string | null, name: string) => void };

export function TelegramConnectionPanel({ active = true, onConnection }: Props) {
  const { t } = useI18n();
  const [status, setStatus] = useState<Status | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [base, setBase] = useState("https://api.telegram.org");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const revision = useRef(0);
  const mutating = useRef(false);
  const loadedConnection = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (status && (!connectionId || status.connection_id === connectionId)) {
      onConnection?.(status.connection_id, status.bot?.first_name ?? "");
    }
  }, [status, connectionId, onConnection]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const currentRevision = revision.current;
      try {
        if (mutating.current) return;
        const query = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
        const data = await fetchJson<Status>(`/api/mobile/telegram${query}`, { signal: abort.signal });
        if (abort.signal.aborted || mutating.current || currentRevision !== revision.current) return;
        setStatus(data);
        setRefreshError(null);
        if (loadedConnection.current !== connectionId) {
          setBase(data.api_base); loadedConnection.current = connectionId;
        }
      } catch (cause) {
        if (!abort.signal.aborted && currentRevision === revision.current && !mutating.current) {
          setRefreshError(cause instanceof Error ? cause.message : String(cause));
        }
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(refresh, 5000);
      }
    };
    void refresh();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [connectionId, active]);
  const setEnabled = useCallback(async (enabled: boolean) => {
    if (mutating.current || !status || (connectionId && status.connection_id !== connectionId)) return;
    if (enabled && !token.trim() && !status.has_token) {
      setError(t("telegramAccess.tokenRequired"));
      return;
    }
    revision.current++; mutating.current = true;
    setBusy(true); setError(null);
    try {
      const data = await fetchJson<Status>("/api/mobile/telegram", {
        method: "PUT", body: JSON.stringify({ token: enabled ? token : "", enabled,
          api_base: enabled ? base : status.api_base, connection_id: status.connection_id }),
      });
      setStatus(data); setConnectionId(data.connection_id);
      setBase(data.api_base);
      setRefreshError(null);
      setToken("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { revision.current++; mutating.current = false; setBusy(false); }
  }, [token, base, status, connectionId, t]);
  const authorize = async (peer: string, allowed: boolean) => {
    if (mutating.current || !status || (connectionId && status.connection_id !== connectionId)) return;
    revision.current++; mutating.current = true;
    setBusy(true); setError(null);
    try {
      setStatus(await fetchJson<Status>("/api/mobile/telegram/authorization", {
        method: "POST", body: JSON.stringify({ peer, allowed }),
      }));
      setRefreshError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { revision.current++; mutating.current = false; setBusy(false); }
  };
  const unavailable = busy || !status || (!!connectionId && status.connection_id !== connectionId);
  const enabled = status?.enabled ?? false;
  return <section className="telegram-access" aria-busy={busy}>
    <div className="telegram-access__form">
      {(status?.connections?.length ?? 0) > 1 && <>
        <label htmlFor="telegram-connection">{t("telegramAccess.connection")}</label>
        <select id="telegram-connection" disabled={busy} value={status?.connection_id ?? ""}
          onChange={(event) => { revision.current++; setToken(""); setError(null); setRefreshError(null); setConnectionId(event.target.value);
            onConnection?.(event.target.value, status?.connections.find(item => item.connection_id === event.target.value)?.name ?? ""); }}>
          {status?.connections?.map((item) => <option key={item.connection_id} value={item.connection_id}>
            {item.name} {item.username ? `@${item.username}` : item.connection_id}
          </option>)}
        </select>
      </>}
      <label htmlFor="telegram-token">Bot Token</label>
      <input id="telegram-token" type="password" autoComplete="new-password" value={token}
        placeholder={t(status?.has_token ? "telegramAccess.tokenSaved" : "telegramAccess.tokenPlaceholder")}
        onChange={(event) => setToken(event.target.value)} disabled={unavailable || enabled}
        title={enabled ? t("telegramAccess.editConnection") : undefined} />
      <label htmlFor="telegram-enabled">{t("telegramAccess.enabled")}</label>
      <div className="telegram-access__connection-control">
        <AccessSwitchControl id="telegram-enabled" checked={enabled} label={t("telegramAccess.enabled")}
          disabled={unavailable} onChange={() => void setEnabled(!enabled)} />
        {status?.bot && <span>{status.bot.first_name}{status.bot.username && <> · <a href={`https://t.me/${status.bot.username}`} target="_blank" rel="noreferrer">@{status.bot.username}</a></>}</span>}
      </div>
    </div>
    <details className="telegram-access__advanced"><summary>{t("telegramAccess.advanced")}</summary>
      <label htmlFor="telegram-api">Bot API</label>
      <input id="telegram-api" value={base} onChange={(event) => setBase(event.target.value)} disabled={unavailable || enabled}
        title={enabled ? t("telegramAccess.editConnection") : undefined} />
      <p className="telegram-access__hint">{t("telegramAccess.apiHint")}</p>
    </details>
    {error && <p role="alert" className="telegram-access__error">{error}</p>}
    {(refreshError || status?.error) && <p role="alert" className="telegram-access__error">{refreshError || status?.error}</p>}
    {status?.enabled && !refreshError && !status.error && <p className="telegram-access__hint">{t(status.desktop_online ? "telegramAccess.ready" : "telegramAccess.offline")}</p>}
    {!!status?.pending_deliveries && <p>{t("telegramAccess.pendingDelivery")} {status.pending_deliveries}</p>}
    <div className="telegram-access__users">
      <h3>{t("telegramAccess.users")}</h3>
      <p className="telegram-access__hint">{t("telegramAccess.intro")}</p>
      {status?.peers.map((peer) => <div className="telegram-access__user" key={peer.id}>
        <div><strong>{peer.name}</strong><span>{peer.username ? ` @${peer.username}` : ""} · ID {peer.user_id}</span>
          <small>{t(peer.allowed ? "telegramAccess.allowed" : peer.reviewed ? "telegramAccess.denied" : "telegramAccess.waiting")}</small></div>
        <AccessSwitchControl checked={peer.allowed} disabled={unavailable}
          label={`${t("telegramAccess.allow")} · ${peer.name} · ID ${peer.user_id}`}
          onChange={() => void authorize(peer.id, !peer.allowed)} />
      </div>)}
    </div>
  </section>;
}

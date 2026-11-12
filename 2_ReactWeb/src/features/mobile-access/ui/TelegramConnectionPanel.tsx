import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";
import { useI18n } from "../../../shared/i18n";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";
import type { ProjectKind } from "@/entities/project/model/project";
import { MobileScopePanel } from "./MobileScopePanel";
import { MobileMessageReceiptControl } from "./MobileMessageReceiptControl";
import { MobileAuthorizationSummary, MobileConnectionSelect, MobilePeerList, MobileRemoveButton, type MobilePeer } from "./MobileAccountControls";
import "./telegram-access.css";

type Status = {
  connection_id: string | null;
  connections: { connection_id: string; name: string; username: string; enabled: boolean }[];
  enabled: boolean; has_token: boolean; api_base: string; error: string | null;
  desktop_online: boolean; pending_deliveries: number;
  allowed_collections: ProjectKind[];
  message_receipt_enabled: boolean;
  bot: { username?: string; first_name: string } | null;
  peers: { id: string; user_id: number; name: string; username?: string; allowed: boolean; reviewed: boolean }[];
  platform_peers?: MobilePeer[];
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
  const manageAccount = async (path: string, body: object) => {
    if (mutating.current || !status || (connectionId && status.connection_id !== connectionId)) return;
    revision.current++; mutating.current = true;
    setBusy(true); setError(null);
    try {
      const data = await fetchJson<Status>(path, { method: "POST", body: JSON.stringify(body) });
      setStatus(data); setConnectionId(data.connection_id);
      if (data.connection_id !== status.connection_id) { setToken(""); setBase(data.api_base); }
      setRefreshError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { revision.current++; mutating.current = false; setBusy(false); }
  };
  const unavailable = busy || !status || (!!connectionId && status.connection_id !== connectionId);
  const setScope = async (allowed: ProjectKind[]) => {
    if (mutating.current || unavailable || !status?.connection_id) return;
    revision.current++; mutating.current = true;
    setBusy(true); setError(null);
    try {
      const data = await fetchJson<Status>("/api/mobile/telegram/access-scope", {
        method: "PUT", body: JSON.stringify({ connection_id: status.connection_id, allowed_collections: allowed }),
      });
      setStatus(data); setRefreshError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { revision.current++; mutating.current = false; setBusy(false); }
  };
  const enabled = status?.enabled ?? false;
  const peers = status?.platform_peers ?? status?.peers ?? [];
  return <section className="telegram-access" aria-busy={busy}>
    <div className="telegram-access__form">
        <label id="telegram-connection-label">当前连接</label>
        <div className="telegram-access__connection-picker">
        <MobileConnectionSelect labelledBy="telegram-connection-label" disabled={busy || !status?.connections.length} value={status?.connection_id ?? ""}
          connections={status?.connections ?? []}
          placeholder={status ? "尚未创建连接" : "正在加载…"}
          onChange={value => { revision.current++; setToken(""); setError(null); setRefreshError(null); setConnectionId(value);
            onConnection?.(value, status?.connections.find(item => item.connection_id === value)?.name ?? ""); }} />
        <MobileRemoveButton label="删除当前连接" disabled={unavailable || !status?.connection_id}
          message={`删除连接 ${status?.connection_id} 及其登录凭据、授权和菜单记录，停止此连接的收发。项目文件和会话保留。`}
          onRemove={() => void manageAccount("/api/mobile/connections/remove", { platform: "telegram", connection_id: status?.connection_id })} />
        </div>
      <label htmlFor="telegram-enabled">启用当前连接</label>
      <div className="telegram-access__connection-control">
        <AccessSwitchControl id="telegram-enabled" checked={enabled} label={t("telegramAccess.enabled")}
          disabled={unavailable} onChange={() => void setEnabled(!enabled)} />
        <span>{status ? (enabled ? "连接已开启" : "连接已关闭") : "正在加载…"}</span>
        {status?.bot?.username && <a href={`https://t.me/${status.bot.username}`} target="_blank" rel="noreferrer">@{status.bot.username}</a>}
      </div>
      <MobileMessageReceiptControl id="telegram-message-receipt" checked={status?.message_receipt_enabled ?? true}
        disabled={unavailable || !status?.connection_id}
        onChange={() => void manageAccount("/api/mobile/connections/message-receipt", {
          platform: "telegram", connection_id: status?.connection_id, message_receipt_enabled: !(status?.message_receipt_enabled ?? true),
        })} />
      <label htmlFor="telegram-token">Bot Token</label>
      <input id="telegram-token" type="password" autoComplete="new-password" value={token}
        placeholder={t(status?.has_token ? "telegramAccess.tokenSaved" : "telegramAccess.tokenPlaceholder")}
        onChange={(event) => setToken(event.target.value)} disabled={unavailable || enabled}
        title={enabled ? t("telegramAccess.editConnection") : undefined} />
    </div>
    <details className="telegram-access__advanced"><summary>{t("telegramAccess.advanced")}</summary>
      <div className="telegram-access__form">
        <label htmlFor="telegram-api">Bot API</label>
        <div>
          <input id="telegram-api" value={base} onChange={(event) => setBase(event.target.value)} disabled={unavailable || enabled}
            title={enabled ? t("telegramAccess.editConnection") : undefined} />
          <p className="telegram-access__hint">{t("telegramAccess.apiHint")}</p>
        </div>
      </div>
    </details>
    {error && <p role="alert" className="telegram-access__error">{error}</p>}
    {(refreshError || status?.error) && <p role="alert" className="telegram-access__error">{refreshError || status?.error}</p>}
    <p className="telegram-access__hint telegram-access__status telegram-access__connection-status">
      {status?.enabled && !refreshError && !status.error ? t(status.desktop_online ? "telegramAccess.ready" : "telegramAccess.offline") : null}
    </p>
    {!!status?.pending_deliveries && <p className="telegram-access__status">{t("telegramAccess.pendingDelivery")} {status.pending_deliveries}</p>}
    <div className="telegram-access__permissions">
    <div className="telegram-access__users">
      <div className="telegram-access__section-head"><h3>用户授权<span>全部连接</span></h3><MobileAuthorizationSummary peers={peers} /></div>
      <p className="telegram-access__hint">{t("telegramAccess.intro")}</p>
      <MobilePeerList peers={peers} disabled={unavailable}
        allowLabel={peer => `${t("telegramAccess.allow")} · ${peer.name} · ID ${peer.user_id}${peer.connection_id ? ` · ${peer.connection_id}` : ""}`}
        onAuthorize={peer => void manageAccount("/api/mobile/telegram/authorization", {
          peer: peer.id, allowed: !peer.allowed, selected_connection_id: status?.connection_id,
        })}
        onRemove={peer => void manageAccount("/api/mobile/peers/remove", {
          peer: peer.id, selected_connection_id: status?.connection_id,
        })} />
    </div>
    <MobileScopePanel allowed={status?.allowed_collections ?? ["project"]} disabled={unavailable}
      connected={!!status?.connection_id} onChange={allowed => void setScope(allowed)} />
    </div>
  </section>;
}

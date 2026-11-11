import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";
import { WeChatQr } from "./WeChatQr";

export type Platform = "feishu" | "wechat";
type Status = {
  connection_id: string | null; enabled: boolean; has_token: boolean; app_id: string;
  error: string | null; desktop_online: boolean; pending_deliveries: number;
  bot: { first_name: string } | null;
  connections: { connection_id: string; name: string }[];
  peers: { id: string; user_id: string; name: string; allowed: boolean }[];
};

export function PlatformConnectionPanel({ platform, active, onConnection }: {
  platform: Platform; active: boolean; onConnection: (id: string | null, name: string) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const mutation = useRef(false);
  const epoch = useRef(0);
  const loaded = useRef<string | null | undefined>(undefined);
  const label = platform === "feishu" ? "飞书" : "微信";
  useEffect(() => {
    if (status) onConnection(status.connection_id, status.bot?.first_name ?? "");
  }, [status, onConnection]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const ticket = epoch.current;
      try {
        if (mutation.current) return;
        const query = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
        const result = await fetchJson<Status>(`/api/mobile/platform/${platform}${query}`, { signal: abort.signal });
        if (abort.signal.aborted || mutation.current || epoch.current !== ticket) return;
        setStatus(result);
        if (loaded.current !== connectionId) { setAppId(result.app_id); loaded.current = connectionId; }
        setRefreshError("");
      } catch (cause) {
        if (!abort.signal.aborted && ticket === epoch.current) setRefreshError(String(cause instanceof Error ? cause.message : cause));
      } finally { if (!abort.signal.aborted) timer = setTimeout(refresh, 5000); }
    };
    void refresh();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [platform, active, connectionId, revision]);
  const mutate = async (path: string, method: string, body: object) => {
    if (mutation.current) return;
    mutation.current = true; epoch.current++; setBusy(true); setError("");
    try {
      const result = await fetchJson<Status>(path, { method, body: JSON.stringify(body) });
      setStatus(result); setConnectionId(result.connection_id); setSecret(""); setAppId(result.app_id ?? "");
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { mutation.current = false; epoch.current++; setBusy(false); }
  };
  const disabled = busy || !status || (!!connectionId && status.connection_id !== connectionId);
  const enabled = status?.enabled ?? false;
  return <section className="telegram-access" aria-busy={busy}>
    <div className="telegram-access__form">
      {!!status?.connections.length && <><label htmlFor={`${platform}-connection`}>连接</label>
        <select id={`${platform}-connection`} value={status.connection_id ?? ""} disabled={busy}
          onChange={event => { epoch.current++; loaded.current = undefined; setError(""); setRefreshError(""); setSecret(""); setStatus(null); setConnectionId(event.target.value || null); }}>
          {status.connections.map(item => <option key={item.connection_id} value={item.connection_id}>{item.name} · {item.connection_id}</option>)}
        </select></>}
      {platform === "feishu" && <>
        <label htmlFor="feishu-app-id">App ID</label><input id="feishu-app-id" value={appId} onChange={event => setAppId(event.target.value)} disabled={disabled || enabled} />
        <label htmlFor="feishu-secret">App Secret</label><input id="feishu-secret" type="password" autoComplete="new-password" value={secret}
          placeholder={status?.has_token ? "已保存，留空沿用" : "填写应用密钥"} disabled={disabled || enabled} onChange={event => setSecret(event.target.value)} />
      </>}
      <label>启用{label}接入</label><div className="telegram-access__connection-control">
        <AccessSwitchControl checked={enabled} label={`启用${label}接入`} disabled={disabled || (platform === "wechat" && !status?.has_token)}
          onChange={() => void mutate(`/api/mobile/platform/${platform}`, "PUT", { connection_id: status?.connection_id,
            enabled: !enabled, app_id: appId, secret })} />
        <span>{status?.bot?.first_name}</span>
      </div>
    </div>
    {platform === "wechat" && <WeChatQr active={active} onConnected={id => {
      epoch.current++; setConnectionId(id); setRevision(value => value + 1);
    }} />}
    {(error || refreshError || status?.error) && <p role="alert" className="telegram-access__error">{error || refreshError || status?.error}</p>}
    {enabled && !status?.error && <p className="telegram-access__hint">{status?.desktop_online ? "已启用。天策需保持运行，可最小化到托盘。" : "请保持天策桌面界面在线，以便提交消息。"}</p>}
    {!!status?.pending_deliveries && <p>待回传消息：{status.pending_deliveries}</p>}
    <div className="telegram-access__users"><h3>允许访问的用户</h3>
      <p className="telegram-access__hint">{platform === "wechat" ? "扫码确认的本人账号会自动授权。其他账号需在此允许后才能操作天策。" : "先在飞书中找到并私聊此应用机器人，发送 /start，再在这里允许自己的账号。"}</p>
      {status?.peers.map(peer => <div className="telegram-access__user" key={peer.id}>
        <div><strong>{peer.name}</strong><small>ID {peer.user_id}</small></div>
        <AccessSwitchControl checked={peer.allowed} disabled={disabled} label={`允许 ${peer.name}`}
          onChange={() => void mutate("/api/mobile/authorization", "POST", { peer: peer.id, allowed: !peer.allowed })} />
      </div>)}
    </div>
  </section>;
}

import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";
import type { ProjectKind } from "@/entities/project/model/project";
import { MobileScopePanel } from "./MobileScopePanel";
import { MobileMessageReceiptControl } from "./MobileMessageReceiptControl";
import { WeChatQr } from "./WeChatQr";
import { FeishuQr } from "./FeishuQr";
import { MobileAuthorizationSummary, MobileConnectionSelect, MobilePeerList, MobileRemoveButton, type MobileConnection, type MobilePeer } from "./MobileAccountControls";

export type Platform = "feishu" | "wechat";
type Status = {
  connection_id: string | null; enabled: boolean; has_token: boolean; app_id: string;
  allowed_collections: ProjectKind[];
  message_receipt_enabled: boolean;
  error: string | null; desktop_online: boolean; pending_deliveries: number;
  bot: { first_name: string } | null;
  connections: MobileConnection[];
  peers: MobilePeer[];
  platform_peers?: MobilePeer[];
};

export function PlatformConnectionPanel({ platform, active, onConnection }: {
  platform: Platform; active: boolean; onConnection: (id: string | null, name: string) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const mutation = useRef(false);
  const epoch = useRef(0);
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
    const ticket = epoch.current;
    try {
      const result = await fetchJson<Status>(path, { method, body: JSON.stringify(body) });
      if (ticket !== epoch.current) return;
      setStatus(result); setConnectionId(result.connection_id); setRefreshError("");
    } catch (cause) { if (ticket === epoch.current) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { mutation.current = false; epoch.current++; setBusy(false); }
  };
  const disabled = busy || !status || (!!connectionId && status.connection_id !== connectionId);
  const enabled = status?.enabled ?? false;
  const peers = status?.platform_peers ?? status?.peers ?? [];
  return <section className="telegram-access" aria-busy={busy}>
    <div className="telegram-access__form">
      <label id={`${platform}-connection-label`}>当前连接</label>
        <div className="telegram-access__connection-picker">
        <MobileConnectionSelect labelledBy={`${platform}-connection-label`} connections={status?.connections ?? []}
          value={status?.connection_id ?? ""} disabled={busy || !status?.connections.length}
          placeholder={status ? "尚未创建连接" : "正在加载…"}
          onChange={value => { epoch.current++; setError(""); setRefreshError(""); setStatus(null); setConnectionId(value || null); }} />
        <MobileRemoveButton label="删除当前连接" disabled={disabled || !status?.connection_id} message={`删除连接 ${status?.connection_id} 及其登录凭据、授权和菜单记录，停止此连接的收发。项目文件和会话保留。`}
          onRemove={() => void mutate("/api/mobile/connections/remove", "POST", { platform, connection_id: status?.connection_id })} />
        </div>
      <label htmlFor={`${platform}-enabled`}>启用当前连接</label><div className="telegram-access__connection-control">
        <AccessSwitchControl id={`${platform}-enabled`} checked={enabled} label={`启用${label}接入`} disabled={disabled || !status?.has_token}
          onChange={() => void mutate(`/api/mobile/platform/${platform}`, "PUT", { connection_id: status?.connection_id,
            enabled: !enabled })} />
        <span>{status ? (enabled ? "连接已开启" : "连接已关闭") : "正在加载…"}</span>
      </div>
      <MobileMessageReceiptControl id={`${platform}-message-receipt`} checked={status?.message_receipt_enabled ?? true}
        disabled={disabled || !status?.connection_id}
        onChange={() => void mutate("/api/mobile/connections/message-receipt", "POST", {
          platform, connection_id: status?.connection_id, message_receipt_enabled: !(status?.message_receipt_enabled ?? true),
        })} />
    </div>
    {platform === "wechat" && <WeChatQr active={active} onConnected={id => {
      epoch.current++; setStatus(null); setConnectionId(id); setRevision(value => value + 1);
    }} />}
    {platform === "feishu" && <FeishuQr active={active} onConnected={id => {
      epoch.current++; setError(""); setRefreshError(""); setStatus(null); setConnectionId(id); setRevision(value => value + 1);
    }} />}
    {(error || refreshError || status?.error) && <p role="alert" className="telegram-access__error">{error || refreshError || status?.error}</p>}
    <p className="telegram-access__hint telegram-access__status telegram-access__connection-status">
      {enabled && !status?.error && !refreshError ? (status?.desktop_online ? "天策需保持运行，可最小化到托盘。" : "请保持天策桌面界面在线，以便提交消息。") : null}
    </p>
    {!!status?.pending_deliveries && <p className="telegram-access__status">待回传消息：{status.pending_deliveries}</p>}
    <div className="telegram-access__permissions">
    <div className="telegram-access__users">
      <div className="telegram-access__section-head"><h3>用户授权<span>全部连接</span></h3><MobileAuthorizationSummary peers={peers} /></div>
      <p className="telegram-access__hint">{platform === "wechat" ? "扫码确认的本人账号会自动授权。其他账号需在此允许后才能操作天策。" : "先在飞书中找到并私聊此应用机器人，发送 /start，再在这里允许自己的账号。"}</p>
      <MobilePeerList peers={peers} disabled={disabled}
        onAuthorize={peer => void mutate("/api/mobile/authorization", "POST", {
          peer: peer.id, allowed: !peer.allowed, selected_connection_id: status?.connection_id,
        })}
        onRemove={peer => void mutate("/api/mobile/peers/remove", "POST", {
          peer: peer.id, selected_connection_id: status?.connection_id,
        })} />
    </div>
    <MobileScopePanel allowed={status?.allowed_collections ?? ["project"]} disabled={disabled}
      connected={!!status?.connection_id} onChange={allowed => {
        if (!disabled && status?.connection_id) void mutate(`/api/mobile/platform/${platform}/access-scope`, "PUT", {
          connection_id: status.connection_id, allowed_collections: allowed,
        });
      }} />
    </div>
  </section>;
}

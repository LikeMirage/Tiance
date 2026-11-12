import { useState } from "react";
import { Trash } from "@phosphor-icons/react";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";

export type MobilePeer = {
  id: string; user_id: string | number; name: string; username?: string;
  allowed: boolean; reviewed?: boolean; connection_id?: string;
  connection_name?: string; connection_enabled?: boolean;
};
export type MobileConnection = { connection_id: string; name: string; enabled?: boolean; username?: string };

export function MobileRemoveButton({ label, message, disabled, onRemove }: {
  label: string; message: string; disabled: boolean; onRemove: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  return <>
    <button type="button" className="telegram-access__remove" aria-label={label} title={label}
      disabled={disabled} onClick={() => setConfirm(true)}><Trash size={16} /></button>
    {confirm && <ConfirmModal title={label} message={message} danger confirmLabel="删除"
      confirmDisabled={disabled} onCancel={() => setConfirm(false)}
      onConfirm={() => { setConfirm(false); onRemove(); }} />}
  </>;
}

export function MobileConnectionSelect({ connections, value, disabled, labelledBy, placeholder, onChange }: {
  connections: MobileConnection[]; value: string; disabled: boolean; labelledBy: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return <OptionSelect className="telegram-access__connection-select" value={value}
    ariaLabelledBy={labelledBy} disabled={disabled} onChange={onChange}
    variant="integrated-overlay" showSelectedOption placeholder={placeholder}
    options={connections.map(item => ({ value: item.connection_id,
      label: `${item.name} · ${item.username ? `@${item.username}` : item.connection_id}${item.enabled ? "" : " · 已关闭"}`,
    }))} />;
}

export function MobileAuthorizationSummary({ peers }: { peers: MobilePeer[] }) {
  return <span className="telegram-access__authorization-summary" aria-live="polite">
    已授权 {peers.filter(peer => peer.allowed).length} / {peers.length}
  </span>;
}

export function MobilePeerList({ peers, disabled, onAuthorize, onRemove, allowLabel }: {
  peers: MobilePeer[]; disabled: boolean;
  onAuthorize: (peer: MobilePeer) => void; onRemove: (peer: MobilePeer) => void;
  allowLabel?: (peer: MobilePeer) => string;
}) {
  return <>
    {!peers.length && <p className="telegram-access__hint">暂无接入用户。</p>}
    {peers.map(peer => <div className="telegram-access__user" key={peer.id}>
      <div className="telegram-access__user-identity"><strong title={peer.name}>{peer.name}</strong>
        {(peer.name !== String(peer.user_id) || peer.username) && <small>{peer.username ? `@${peer.username} · ` : ""}ID {peer.user_id}</small>}
        {peer.connection_id && <small title={peer.connection_name}>连接：{peer.connection_id}</small>}
        {peer.connection_enabled === false && <small>连接已关闭</small>}
      </div>
      <div className="telegram-access__user-actions">
        <span className="telegram-access__user-state">{peer.allowed ? "已授权" : peer.reviewed ? "未授权" : "待授权"}</span>
        <AccessSwitchControl checked={peer.allowed} disabled={disabled}
          label={allowLabel?.(peer) ?? `允许 ${peer.name} · ${peer.connection_id ?? peer.id}`}
          onChange={() => onAuthorize(peer)} />
        <MobileRemoveButton label={`删除用户 ${peer.name}`} disabled={disabled}
          message={`删除 ${peer.name} 在连接 ${peer.connection_id ?? "当前连接"} 下的授权、菜单和待发送引用。后续消息会被忽略，用户不会自动重新加入。项目文件和会话保留。`}
          onRemove={() => onRemove(peer)} />
      </div>
    </div>)}
  </>;
}

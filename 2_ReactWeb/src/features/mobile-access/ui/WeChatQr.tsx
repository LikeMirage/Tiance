import { useEffect, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";

type Login = { id: string; status: string; image: string; error: string | null; connection_id?: string };
const terminal = new Set(["confirmed", "expired", "error", "verify_code_blocked", "binded_redirect"]);
export function WeChatQr({ active, onConnected }: { active: boolean; onConnected: (id: string) => void }) {
  const [login, setLogin] = useState<Login | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pin, setPin] = useState("");
  useEffect(() => {
    if (!active || !login || terminal.has(login.status)) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      void fetchJson<Login>(`/api/mobile/wechat/login/${login.id}`, { signal: abort.signal }).then(result => {
        if (!abort.signal.aborted) {
          setLogin(result); setError("");
          if (result.status === "confirmed" && result.connection_id) onConnected(result.connection_id);
        }
      }).catch(cause => { if (!abort.signal.aborted) { setError(String(cause)); setLogin(old => old ? { ...old, status: "error" } : old); } });
    }, 1200);
    return () => { abort.abort(); clearTimeout(timer); };
  }, [active, login, onConnected]);
  const start = async () => {
    setBusy(true); setError(""); setPin("");
    try { setLogin(await fetchJson<Login>("/api/mobile/wechat/login", { method: "POST" })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const verify = async () => {
    if (!login) return;
    setBusy(true); setError("");
    try { await fetchJson(`/api/mobile/wechat/login/${login.id}/pin`, { method: "POST", body: JSON.stringify({ pin }) }); setPin(""); }
    catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  const status = login?.status;
  const text = status === "confirmed" ? "扫码连接成功" : status === "expired" ? "二维码已过期，请重新获取。" :
    status === "binded_redirect" ? "此机器人已绑定，微信未返回新的凭据。请在微信解除旧绑定后重新扫码。" :
    status === "verify_code_blocked" ? "验证码尝试次数过多，请重新获取二维码。" : status === "scaned" ? "已扫描，请在手机上确认。" : "请用本人微信扫码并确认连接。";
  return <div className="mobile-qr">
    <button type="button" disabled={busy} onClick={() => void start()}>{busy ? "正在获取…" : "获取连接二维码"}</button>
    {login && <><p>{text}</p>{!terminal.has(login.status) && <img src={login.image} width={220} height={220} alt="微信连接二维码" />}
      {login.status.includes("need_verifycode") && <div className="mobile-qr__pin"><label htmlFor="wechat-pin">手机显示的验证码</label>
        <input id="wechat-pin" inputMode="numeric" value={pin} onChange={event => setPin(event.target.value)} />
        <button type="button" disabled={busy || !pin} onClick={() => void verify()}>确认验证码</button></div>}
    </>}
    {(error || login?.error) && <p role="alert" className="telegram-access__error">{error || login?.error}</p>}
  </div>;
}

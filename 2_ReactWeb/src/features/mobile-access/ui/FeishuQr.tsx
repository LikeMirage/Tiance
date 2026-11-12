import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../../../services/http/httpClient";

type Login = { id: string; status: string; image: string; error: string | null; connection_id?: string };
const terminal = new Set(["confirmed", "expired", "error"]);

export function FeishuQr({ active, onConnected }: { active: boolean; onConnected: (id: string) => void }) {
  const [login, setLogin] = useState<Login | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const startRequest = useRef<AbortController | null>(null);
  const connected = useRef(onConnected);
  connected.current = onConnected;
  useEffect(() => () => startRequest.current?.abort(), []);
  useEffect(() => {
    if (!active || !login || terminal.has(login.status)) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await fetchJson<Login>(`/api/mobile/feishu/login/${login.id}`, { signal: abort.signal });
        if (abort.signal.aborted) return;
        setError(""); setLogin(result);
        if (result.status === "confirmed" && result.connection_id) connected.current(result.connection_id);
      } catch (cause) {
        if (!abort.signal.aborted) {
          setError(cause instanceof Error ? cause.message : String(cause));
          timer = setTimeout(poll, 1500);
        }
      }
    };
    timer = setTimeout(poll, 1500);
    return () => { abort.abort(); clearTimeout(timer); };
  }, [active, login]);
  const start = async () => {
    if (startRequest.current) return;
    const abort = new AbortController();
    startRequest.current = abort;
    setBusy(true); setError(""); setLogin(null);
    try { setLogin(await fetchJson<Login>("/api/mobile/feishu/login", { method: "POST", signal: abort.signal })); }
    catch (cause) { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { startRequest.current = null; if (!abort.signal.aborted) setBusy(false); }
  };
  const text = login?.status === "confirmed" ? "扫码连接成功，请在飞书向机器人发送 /start，再在下方授权账号。" :
    login?.status === "expired" ? "二维码已过期，请重新获取。" :
    login?.status === "saving" ? "正在验证并保存连接…" :
    login?.status === "error" ? "扫码连接未完成。" : "用飞书扫码，按手机提示创建机器人。";
  return <div className="mobile-qr">
    <button type="button" disabled={busy || login?.status === "saving"} onClick={() => void start()}>
      {busy ? "正在获取…" : "扫码创建并连接"}
    </button>
    {login && <><p>{text}</p>{login.status === "wait" && <img src={login.image} width={220} height={220} alt="飞书连接二维码" />}</>}
    {(error || login?.error) && <p role="alert" className="telegram-access__error">{error || login?.error}</p>}
  </div>;
}

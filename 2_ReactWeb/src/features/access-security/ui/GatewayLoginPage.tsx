import { useState } from "react";
import { LockKey } from "@phosphor-icons/react";

import { loginGateway } from "../../../services/security/gatewaySecurity";
import "./gateway-login-page.css";

export function GatewayLoginPage({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!password || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await loginGateway(password);
      onAuthenticated();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "登录失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="gateway-login">
      <form className="gateway-login__form" onSubmit={submit}>
        <LockKey size={58} weight="light" aria-hidden="true" />
        <h1>访问天策</h1>
        <label htmlFor="gateway-password">密码</label>
        <input
          id="gateway-password"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? <p className="gateway-login__error" role="alert">{error}</p> : null}
        <button type="submit" disabled={!password || submitting}>
          {submitting ? "正在验证" : "进入"}
        </button>
      </form>
    </main>
  );
}

export function GatewayUnavailablePage({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="gateway-login">
      <section className="gateway-login__form" role="alert">
        <LockKey size={58} weight="light" aria-hidden="true" />
        <h1>访问网关不可用</h1>
        <p className="gateway-login__error">无法连接天策访问网关，请重启天策后重试。</p>
        <button type="button" onClick={onRetry}>重试</button>
      </section>
    </main>
  );
}

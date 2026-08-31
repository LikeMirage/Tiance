import { useEffect, useState } from "react";

import {
  getGatewaySecurityStatus,
  removeGatewayPassword,
  revokeGatewaySessions,
  updateGatewayPassword,
  type GatewaySecurityStatus,
} from "../../../services/security/gatewaySecurity";
import { useI18n } from "../../../shared/i18n";
import "./access-security-panel.css";

export function AccessSecurityPanel({ onReady }: { onReady?: () => void }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<GatewaySecurityStatus | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => onReady?.(), [onReady]);
  useEffect(() => { void refresh(); }, []);

  async function refresh() {
    try { setStatus(await getGatewaySecurityStatus()); }
    catch (loadError) { setError(toMessage(loadError, t("accessSecurity.operationFailed"))); }
  }

  async function savePassword(event: React.FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError(t("accessSecurity.passwordMismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await updateGatewayPassword(status?.password_configured ? currentPassword : null, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage(status?.password_configured ? t("accessSecurity.passwordUpdated") : t("accessSecurity.passwordSet"));
      await refresh();
    } catch (saveError) { setError(toMessage(saveError, t("accessSecurity.operationFailed"))); }
    finally { setBusy(false); }
  }

  async function removePassword() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await removeGatewayPassword(currentPassword);
      setCurrentPassword("");
      setMessage(t("accessSecurity.passwordRemoved"));
      await refresh();
    } catch (removeError) { setError(toMessage(removeError, t("accessSecurity.operationFailed"))); }
    finally { setBusy(false); }
  }

  async function revokeSessions() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await revokeGatewaySessions();
      setMessage(t("accessSecurity.sessionsRevoked"));
    } catch (revokeError) { setError(toMessage(revokeError, t("accessSecurity.operationFailed"))); }
    finally { setBusy(false); }
  }

  return (
    <div className="access-security">
      <div className="access-security__content">
        <header className="access-security__head">
          <h2>{t("accessSecurity.title")}</h2>
          <span className={status?.password_configured
            ? "access-security__status access-security__status--active"
            : "access-security__status"}
          >
            {status?.password_configured
              ? t("accessSecurity.passwordEnabled")
              : t("accessSecurity.passwordDisabled")}
          </span>
        </header>

        {error ? <p className="access-security__feedback access-security__error" role="alert">{error}</p> : null}
        {message ? <p className="access-security__feedback access-security__message" role="status">{message}</p> : null}

        <section className="access-security__section">
          <div className="access-security__section-head">
            <h3>{status?.password_configured ? t("accessSecurity.updatePassword") : t("accessSecurity.setPassword")}</h3>
            <p>{t("accessSecurity.passwordDescription")}</p>
          </div>
          <form className="access-security__form" onSubmit={savePassword}>
            {status?.password_configured ? (
              <label>
                <span>{t("accessSecurity.currentPassword")}</span>
                <input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
              </label>
            ) : null}
            <div className="access-security__new-password-fields">
              <label>
                <span>{t("accessSecurity.newPassword")}</span>
                <input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
              </label>
              <label>
                <span>{t("accessSecurity.confirmPassword")}</span>
                <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
              </label>
            </div>
            <p className="access-security__hint">{t("accessSecurity.passwordRule")}</p>
            <div className="access-security__actions">
              <button className="access-security__primary" type="submit" disabled={busy || newPassword.length < 8}>{t("accessSecurity.savePassword")}</button>
              {status?.password_configured ? <button type="button" className="access-security__danger" disabled={busy || !currentPassword} onClick={() => void removePassword()}>{t("accessSecurity.removePassword")}</button> : null}
            </div>
          </form>
        </section>

        {status?.password_configured ? (
          <section className="access-security__section access-security__sessions">
            <div className="access-security__section-head">
              <h3>{t("accessSecurity.sessions")}</h3>
              <p>{t("accessSecurity.sessionsDescription")}</p>
            </div>
            <button type="button" disabled={busy} onClick={() => void revokeSessions()}>{t("accessSecurity.revokeSessions")}</button>
          </section>
        ) : null}
      </div>
    </div>
  );
}

function toMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Copy, WarningCircle } from "@phosphor-icons/react";

import {
  getExternalAccessStatus,
  saveExternalAccess,
  type ExternalAccessStatus,
} from "../../../services/network/networkSettings";
import {
  getGatewaySecurityStatus,
  saveGatewaySecuritySettings,
  type GatewaySecurityStatus,
} from "../../../services/security/gatewaySecurity";
import { useI18n } from "../../../shared/i18n";
import { SettingsViewStage } from "../../../shared/ui/settings-view-tabs/SettingsViewStage";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";

import "./access-management.css";

type AccessManagementPanelProps = {
  onReady?: () => void;
};

type AccessManagementView = "external" | "wechat" | "dingtalk" | "telegram";

const ACCESS_MANAGEMENT_VIEWS: readonly AccessManagementView[] = [
  "external",
  "wechat",
  "dingtalk",
  "telegram",
];

export function AccessManagementPanel({ onReady }: AccessManagementPanelProps) {
  const { t } = useI18n();
  const [activeView, setActiveView] = useState<AccessManagementView>("external");
  const [status, setStatus] = useState<ExternalAccessStatus | null>(null);
  const [securityStatus, setSecurityStatus] = useState<GatewaySecurityStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onReady?.(), [onReady]);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    void Promise.all([getExternalAccessStatus(), getGatewaySecurityStatus()])
      .then(([accessResult, securityResult]) => {
        if (!controller.signal.aborted) {
          setStatus(accessResult);
          setSecurityStatus(securityResult);
        }
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setError(toErrorMessage(loadError, t("accessManagement.loadFailed")));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [t]);

  const updateEnabled = useCallback(async (enabled: boolean) => {
    if (isSaving) return;
    setIsSaving(true);
    setError(null);
    try {
      setStatus(await saveExternalAccess(enabled));
    } catch (saveError) {
      setError(toErrorMessage(saveError, t("accessManagement.saveFailed")));
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, t]);

  const tabs = useMemo(() => ACCESS_MANAGEMENT_VIEWS.map((view) => ({
    id: view,
    label: t(`accessManagement.tabs.${view}`),
  })), [t]);

  return (
    <div className="access-management">
      <header className="access-management__head">
        <h2>{t("accessManagement.title")}</h2>
      </header>
      <SettingsViewTabs
        activeView={activeView}
        ariaLabel={t("accessManagement.tabsLabel")}
        onChange={setActiveView}
        tabs={tabs}
      />
      <SettingsViewStage
        activeView={activeView}
        className="access-management__stage"
        layout="fill"
        orderedViews={ACCESS_MANAGEMENT_VIEWS}
      >
        {activeView === "external" ? (
          <ExternalAccessView
            error={error}
            isLoading={isLoading}
            isSaving={isSaving}
            onChange={updateEnabled}
            onSecurityStatusChange={setSecurityStatus}
            securityStatus={securityStatus}
            status={status}
          />
        ) : (
          <div className="access-management__empty-view" aria-hidden="true" />
        )}
      </SettingsViewStage>
    </div>
  );
}

function ExternalAccessView({
  error,
  isLoading,
  isSaving,
  onChange,
  onSecurityStatusChange,
  securityStatus,
  status,
}: {
  error: string | null;
  isLoading: boolean;
  isSaving: boolean;
  onChange: (enabled: boolean) => void;
  onSecurityStatusChange: (status: GatewaySecurityStatus) => void;
  securityStatus: GatewaySecurityStatus | null;
  status: ExternalAccessStatus | null;
}) {
  const { t } = useI18n();
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);
  const [localBypassEnabled, setLocalBypassEnabled] = useState(false);
  const [httpsEnabled, setHttpsEnabled] = useState(false);
  const [httpsPort, setHttpsPort] = useState(18443);
  const [certificatePath, setCertificatePath] = useState("");
  const [certificatePassword, setCertificatePassword] = useState("");
  const [securitySaving, setSecuritySaving] = useState(false);
  const [securityError, setSecurityError] = useState<string | null>(null);
  const copiedTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
  }, []);
  useEffect(() => {
    if (!securityStatus) return;
    setLocalBypassEnabled(securityStatus.local_bypass_enabled);
    setHttpsEnabled(securityStatus.https_enabled);
    setHttpsPort(securityStatus.https_port);
    setCertificatePath(securityStatus.certificate_path);
  }, [securityStatus]);

  const saveSecurity = useCallback(async (overrides: Partial<{
    localBypassEnabled: boolean;
    httpsEnabled: boolean;
    httpsPort: number;
    certificatePath: string;
    certificatePassword: string;
  }> = {}) => {
    if (!securityStatus) return;
    const nextSettings = {
      localBypassEnabled,
      httpsEnabled,
      httpsPort,
      certificatePath,
      certificatePassword,
      ...overrides,
    };
    setSecuritySaving(true);
    setSecurityError(null);
    try {
      const result = await saveGatewaySecuritySettings({
        localBypassEnabled: nextSettings.localBypassEnabled,
        httpsEnabled: nextSettings.httpsEnabled,
        httpsPort: nextSettings.httpsPort,
        certificatePath: nextSettings.certificatePath,
        certificatePassword: nextSettings.certificatePassword || null,
      });
      onSecurityStatusChange({
        ...securityStatus,
        local_bypass_enabled: nextSettings.localBypassEnabled,
        https_enabled: nextSettings.httpsEnabled,
        https_port: nextSettings.httpsPort,
        certificate_path: nextSettings.certificatePath,
        restart_required: result.restart_required,
      });
      setCertificatePassword("");
    } catch (saveError) {
      setSecurityError(toErrorMessage(saveError, t("accessManagement.external.securitySaveFailed")));
    } finally { setSecuritySaving(false); }
  }, [certificatePassword, certificatePath, httpsEnabled, httpsPort, localBypassEnabled, onSecurityStatusChange, securityStatus, t]);

  const copyAddress = useCallback(async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedUrl(url);
      if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = window.setTimeout(() => {
        setCopiedUrl(null);
        copiedTimerRef.current = null;
      }, 300);
    } catch {
      setCopiedUrl(null);
    }
  }, []);

  if (isLoading) {
    return <div className="access-management__loading" role="status">{t("accessManagement.loading")}</div>;
  }

  return (
    <div className="access-management__external">
      {error ? <div className="access-management__error" role="alert">{error}</div> : null}
      <section className="access-management__section access-management__controls">
        <div className="access-management__control-row access-management__control-row--primary">
          <div className="access-management__control-copy">
            <h3>{t("accessManagement.external.enable")}</h3>
            <p>{t("accessManagement.external.enableDescription")}</p>
          </div>
          <SwitchControl
            checked={status?.configured_enabled ?? false}
            disabled={isSaving || status === null}
            label={t("accessManagement.external.enable")}
            onChange={() => onChange(!(status?.configured_enabled ?? false))}
          />
        </div>

        {securityStatus ? (
          <div className="access-management__security-controls">
            <div className="access-management__security-switches">
              <div className="access-management__control-row">
                <span>{t("accessManagement.external.localBypass")}</span>
                <SwitchControl
                  checked={localBypassEnabled}
                  disabled={securitySaving}
                  label={t("accessManagement.external.localBypass")}
                  onChange={() => {
                    const nextEnabled = !localBypassEnabled;
                    setLocalBypassEnabled(nextEnabled);
                    void saveSecurity({ localBypassEnabled: nextEnabled });
                  }}
                />
              </div>
              <div className="access-management__control-row">
                <span>{t("accessManagement.external.enableHttps")}</span>
                <SwitchControl
                  checked={httpsEnabled}
                  disabled={securitySaving}
                  label={t("accessManagement.external.enableHttps")}
                  onChange={() => {
                    const nextEnabled = !httpsEnabled;
                    setHttpsEnabled(nextEnabled);
                    if (!nextEnabled || certificatePath.trim()) {
                      void saveSecurity({ httpsEnabled: nextEnabled });
                    }
                  }}
                />
              </div>
            </div>
            {httpsEnabled ? (
              <div className="access-management__https-fields">
                <label>{t("accessManagement.external.httpsPort")}<input type="number" min={1} max={65535} value={httpsPort} disabled={securitySaving} onChange={(event) => setHttpsPort(Number(event.target.value))} onBlur={() => { if (certificatePath.trim() && httpsPort !== securityStatus.https_port) void saveSecurity(); }} /></label>
                <label>{t("accessManagement.external.certificatePath")}<input value={certificatePath} disabled={securitySaving} onChange={(event) => setCertificatePath(event.target.value)} onBlur={() => { if (certificatePath.trim() && certificatePath !== securityStatus.certificate_path) void saveSecurity(); }} /></label>
                <label>{t("accessManagement.external.certificatePassword")}<input type="password" value={certificatePassword} disabled={securitySaving} placeholder={t("accessManagement.external.certificatePasswordKeep")} onChange={(event) => setCertificatePassword(event.target.value)} onBlur={() => { if (certificatePath.trim() && certificatePassword) void saveSecurity(); }} /></label>
              </div>
            ) : null}
            {securityError ? <p className="access-management__error" role="alert">{securityError}</p> : null}
            {securityStatus.restart_required ? <p className="access-management__restart">{t("accessManagement.external.restartRequired")}</p> : null}
          </div>
        ) : (
          <div className="access-management__notice">
            <WarningCircle size={18} aria-hidden="true" />
            <span>{t("accessManagement.external.gatewayUnavailable")}</span>
          </div>
        )}
      </section>

      {status?.restart_required ? (
        <div className="access-management__restart" role="status">
          {t("accessManagement.external.restartRequired")}
        </div>
      ) : null}

      {status ? (
        <>
          <section className="access-management__section">
            <div className="access-management__section-heading">
              <h3>{t("accessManagement.external.addresses")}</h3>
              <span className={status.effective_enabled
                ? "access-management__status access-management__status--active"
                : "access-management__status"}
              >
                {status.effective_enabled
                  ? t("accessManagement.external.active")
                  : t("accessManagement.external.inactive")}
              </span>
            </div>
            <AddressRow
              copied={copiedUrl === status.local_url}
              label={t("accessManagement.external.localAddress")}
              onCopy={copyAddress}
              url={status.local_url}
            />
            {status.access_urls.map((url) => (
              <AddressRow
                copied={copiedUrl === url}
                key={url}
                label={t("accessManagement.external.networkAddress")}
                onCopy={copyAddress}
                url={url}
              />
            ))}
            {status.access_urls.length === 0 ? (
              <p className="access-management__no-address">
                {t("accessManagement.external.noNetworkAddress")}
              </p>
            ) : null}
          </section>

          <section className="access-management__section access-management__details">
            <div>
              <span>{t("accessManagement.external.port")}</span>
              <strong>{status.port}</strong>
            </div>
            <div>
              <span>{t("accessManagement.external.listenScope")}</span>
              <strong>{status.effective_enabled
                ? t("accessManagement.external.allInterfaces")
                : t("accessManagement.external.localOnly")}</strong>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function SwitchControl({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      className={checked
        ? "access-management__switch access-management__switch--on"
        : "access-management__switch"}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
    >
      <span />
    </button>
  );
}

function AddressRow({
  copied,
  label,
  onCopy,
  url,
}: {
  copied: boolean;
  label: string;
  onCopy: (url: string) => void;
  url: string;
}) {
  const { t } = useI18n();
  return (
    <div className="access-management__address-row">
      <span className="access-management__address-label">{label}</span>
      <code>{url}</code>
      <button
        className={copied
          ? "access-management__copy access-management__copy--copied"
          : "access-management__copy"}
        type="button"
        onClick={() => void onCopy(url)}
      >
        <Copy size={15} aria-hidden="true" />
        {t("accessManagement.external.copy")}
      </button>
    </div>
  );
}

function toErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

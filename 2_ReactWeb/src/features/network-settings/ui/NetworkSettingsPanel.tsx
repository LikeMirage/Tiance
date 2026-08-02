import { useEffect } from "react";
import { CheckCircle, FloppyDisk, GithubLogo, WarningCircle } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import type { NetworkSettings } from "../../../services/network/networkSettings";
import { useNetworkSettings } from "../model/useNetworkSettings";

import "./network-settings.css";

type NetworkSettingsPanelProps = {
  onReady?: () => void;
};

export function NetworkSettingsPanel({ onReady }: NetworkSettingsPanelProps) {
  const { t } = useI18n();
  const settings = useNetworkSettings();

  useEffect(() => {
    onReady?.();
  }, [onReady]);

  if (settings.isLoading || !settings.draft) {
    return (
      <div className="network-settings">
        <div className="network-settings__loading" role="status">
          {t("networkSettings.loading")}
        </div>
      </div>
    );
  }

  const draft = settings.draft;
  const isCustomProxy = draft.connection_mode === "custom_proxy";
  const isFixedPort = draft.backend_port_mode === "fixed";

  return (
    <div className="network-settings">
      <header className="network-settings__head">
        <h2 className="network-settings__title">{t("networkSettings.title")}</h2>
        <div className="network-settings__actions">
          <button
            className="network-settings__button"
            type="button"
            disabled={settings.isSaving}
            onClick={settings.reset}
          >
            {t("networkSettings.reset")}
          </button>
          <button
            className="network-settings__button network-settings__button--primary"
            type="button"
            disabled={!settings.hasChanges || settings.isSaving}
            onClick={() => void settings.save()}
          >
            <FloppyDisk size={16} aria-hidden="true" />
            {settings.isSaving
              ? t("networkSettings.saving")
              : t("networkSettings.save")}
          </button>
        </div>
      </header>

      {settings.error ? (
        <div className="network-settings__error" role="alert">
          {settings.error}
        </div>
      ) : null}

      <section className="network-settings__section">
        <div className="network-settings__section-head">
          <h3>{t("networkSettings.connection.title")}</h3>
          <p>{t("networkSettings.connection.description")}</p>
        </div>
        <label className="network-settings__field network-settings__field--wide">
          <span>{t("networkSettings.connection.mode")}</span>
          <select
            value={draft.connection_mode}
            onChange={(event) => settings.updateSetting(
              "connection_mode",
              event.currentTarget.value as NetworkSettings["connection_mode"],
            )}
          >
            <option value="system">{t("networkSettings.connection.system")}</option>
            <option value="direct">{t("networkSettings.connection.direct")}</option>
            <option value="custom_proxy">{t("networkSettings.connection.custom")}</option>
          </select>
        </label>
        {isCustomProxy ? (
          <div className="network-settings__grid network-settings__grid--proxy">
            <label className="network-settings__field">
              <span>{t("networkSettings.connection.scheme")}</span>
              <select
                value={draft.proxy_scheme}
                onChange={(event) => settings.updateSetting(
                  "proxy_scheme",
                  event.currentTarget.value as NetworkSettings["proxy_scheme"],
                )}
              >
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks5">SOCKS5</option>
              </select>
            </label>
            <TextField
              label={t("networkSettings.connection.host")}
              value={draft.proxy_host}
              onChange={(value) => settings.updateSetting("proxy_host", value)}
            />
            <NumberField
              label={t("networkSettings.connection.port")}
              min={1}
              max={65535}
              value={draft.proxy_port}
              onChange={(value) => settings.updateSetting("proxy_port", value)}
            />
          </div>
        ) : null}
      </section>

      <section className="network-settings__section">
        <div className="network-settings__section-head">
          <h3>{t("networkSettings.timeout.title")}</h3>
          <p>{t("networkSettings.timeout.description")}</p>
        </div>
        <div className="network-settings__grid">
          <NumberField
            label={t("networkSettings.timeout.connect")}
            min={1}
            max={3600}
            unit={t("networkSettings.seconds")}
            value={draft.connect_timeout_seconds}
            onChange={(value) => settings.updateSetting("connect_timeout_seconds", value)}
          />
          <NumberField
            label={t("networkSettings.timeout.read")}
            min={1}
            max={3600}
            unit={t("networkSettings.seconds")}
            value={draft.read_timeout_seconds}
            onChange={(value) => settings.updateSetting("read_timeout_seconds", value)}
          />
          <NumberField
            label={t("networkSettings.timeout.stream")}
            min={1}
            max={3600}
            unit={t("networkSettings.seconds")}
            value={draft.stream_timeout_seconds}
            onChange={(value) => settings.updateSetting("stream_timeout_seconds", value)}
          />
        </div>
      </section>

      <section className="network-settings__section">
        <div className="network-settings__section-head">
          <h3>{t("networkSettings.localService.title")}</h3>
          <p>{t("networkSettings.localService.description")}</p>
        </div>
        <div className="network-settings__segmented" role="group">
          {(["auto", "fixed"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={draft.backend_port_mode === mode
                ? "network-settings__segment network-settings__segment--active"
                : "network-settings__segment"}
              aria-pressed={draft.backend_port_mode === mode}
              onClick={() => settings.updateSetting("backend_port_mode", mode)}
            >
              {t(`networkSettings.localService.${mode}`)}
            </button>
          ))}
        </div>
        {isFixedPort ? (
          <NumberField
            label={t("networkSettings.localService.port")}
            min={1}
            max={65535}
            value={draft.fixed_backend_port}
            onChange={(value) => settings.updateSetting("fixed_backend_port", value)}
          />
        ) : null}
        <p className="network-settings__restart-note">
          {t("networkSettings.localService.restart")}
        </p>
      </section>

      <section className="network-settings__section">
        <div className="network-settings__diagnostic">
          <div>
            <h3>{t("networkSettings.diagnostic.title")}</h3>
            <p>{t("networkSettings.diagnostic.description")}</p>
          </div>
          <button
            className="network-settings__button"
            type="button"
            disabled={settings.isDiagnosing || settings.hasChanges}
            title={settings.hasChanges ? t("networkSettings.diagnostic.saveFirst") : undefined}
            onClick={() => void settings.diagnoseGithub()}
          >
            <GithubLogo size={17} aria-hidden="true" />
            {settings.isDiagnosing
              ? t("networkSettings.diagnostic.testing")
              : t("networkSettings.diagnostic.test")}
          </button>
        </div>
        {settings.diagnostic ? (
          <div className={settings.diagnostic.ok
            ? "network-settings__result network-settings__result--success"
            : "network-settings__result network-settings__result--failure"}
          >
            {settings.diagnostic.ok
              ? <CheckCircle size={18} weight="fill" aria-hidden="true" />
              : <WarningCircle size={18} weight="fill" aria-hidden="true" />}
            <span>
              {settings.diagnostic.ok
                ? t("networkSettings.diagnostic.success", {
                    elapsed: settings.diagnostic.elapsed_ms,
                  })
                : t("networkSettings.diagnostic.failure", {
                    error: settings.diagnostic.error ?? "unknown",
                  })}
            </span>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function TextField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label className="network-settings__field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function NumberField({
  label,
  max,
  min,
  onChange,
  unit,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  unit?: string;
  value: number;
}) {
  return (
    <label className="network-settings__field">
      <span>{label}</span>
      <span className="network-settings__number-shell">
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(event) => {
            const next = event.currentTarget.valueAsNumber;
            if (Number.isFinite(next)) onChange(next);
          }}
        />
        {unit ? <span>{unit}</span> : null}
      </span>
    </label>
  );
}

import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowSquareOut,
  CheckCircle,
  GithubLogo,
  SignOut,
} from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import { useGithubConnection } from "../model/useGithubConnection";
import type { GithubGuideTab, GithubSettingsTab } from "../model/githubGuideContent";
import { SettingsViewStage } from "../../../shared/ui/settings-view-tabs/SettingsViewStage";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";
import { GithubSettingsGuide } from "./GithubSettingsGuide";
import "./github-settings.css";

type GithubSettingsPanelProps = {
  onReady?: () => void;
};

export function GithubSettingsPanel({ onReady }: GithubSettingsPanelProps) {
  const { language, t } = useI18n();
  const github = useGithubConnection();
  const [activeTab, setActiveTab] = useState<GithubSettingsTab>("login");
  const [isCodeCopied, setIsCodeCopied] = useState(false);
  const copyResetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    onReady?.();
  }, [onReady]);

  useEffect(() => {
    setIsCodeCopied(false);
  }, [github.flow?.userCode]);

  useEffect(() => () => {
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
    }
  }, []);

  const copyDeviceCode = async () => {
    const code = github.flow?.userCode;
    if (!code) return;
    await navigator.clipboard.writeText(code);
    setIsCodeCopied(true);
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
    }
    copyResetTimerRef.current = window.setTimeout(() => {
      setIsCodeCopied(false);
      copyResetTimerRef.current = null;
    }, 300);
  };

  if (github.isLoading && !github.connection) {
    return <div className="github-settings__loading" role="status">{t("githubSettings.loading")}</div>;
  }

  const connection = github.connection;
  const account = connection?.account;

  return (
    <div className="github-settings">
      <header className="github-settings__head">
        <div>
          <h2>{t("githubSettings.title")}</h2>
        </div>
        {connection?.connected ? (
          <button
            className="github-settings__button"
            type="button"
            disabled={github.isLoggingOut}
            onClick={() => void github.logout()}
          >
            <SignOut size={16} aria-hidden="true" />
            {github.isLoggingOut ? t("githubSettings.loggingOut") : t("githubSettings.logout")}
          </button>
        ) : null}
      </header>

      <SettingsViewTabs
        activeView={activeTab}
        ariaLabel={t("githubSettings.tabs.aria")}
        onChange={setActiveTab}
        tabs={githubSettingsTabs.map((tab) => ({
          id: tab.id,
          label: t(tab.labelKey),
        }))}
      />

      <SettingsViewStage
        activeView={activeTab}
        className="github-settings__view-stage"
        keepLeavingView
        layout="fill"
        orderedViews={githubSettingsViewOrder}
      >
        {activeTab === "login" && github.error ? (
          <div className="github-settings__error" role="alert">{github.error}</div>
        ) : null}

        {activeTab !== "login" ? (
          <GithubSettingsGuide language={language} tab={activeTab as GithubGuideTab} />
        ) : connection?.connected && account ? (
          <>
          <section className="github-settings__account">
            <img src={account.avatarUrl} alt="" />
            <div className="github-settings__account-copy">
              <span className="github-settings__connected"><CheckCircle weight="fill" />{t("githubSettings.connected")}</span>
              <strong>{account.name || account.login}</strong>
              <span>@{account.login}</span>
            </div>
            <button
              className="github-settings__button"
              type="button"
              onClick={() => void github.openExternalUrl(account.profileUrl)}
            >
              <ArrowSquareOut size={16} aria-hidden="true" />
              {t("githubSettings.profile")}
            </button>
          </section>

          <section className="github-settings__section">
            <div className={`github-settings__permissions${connection.requiresReauthorization ? " github-settings__permissions--warning" : ""}`}>
              <div>
                <strong>{t("githubSettings.permissions.title")}</strong>
                <span>
                  {t(connection.requiresReauthorization
                    ? "githubSettings.permissions.incomplete"
                    : "githubSettings.permissions.ready")}
                </span>
              </div>
              {connection.requiresReauthorization ? (
                <button
                  className="github-settings__button github-settings__button--primary"
                  type="button"
                  onClick={() => void github.openExternalUrl(connection.authorizationUrl)}
                >
                  <ArrowSquareOut size={16} aria-hidden="true" />
                  {t("githubSettings.permissions.reauthorize")}
                </button>
              ) : null}
            </div>
            {connection.missingPermissions.length > 0 ? (
              <div className="github-settings__permission-list">
                {connection.missingPermissions.map((permission) => (
                  <span key={permission}>{permission}</span>
                ))}
              </div>
            ) : null}
            <div className="github-settings__section-head">
              <div>
                <h3>{t("githubSettings.repositories.title")}</h3>
                <p>{t("githubSettings.repositories.description")}</p>
              </div>
              <div className="github-settings__section-actions">
                <button
                  className="github-settings__button"
                  disabled={github.refreshState === "loading"}
                  type="button"
                  onClick={() => void github.refresh()}
                >
                  <ArrowClockwise size={16} aria-hidden="true" />
                  {t(
                    github.refreshState === "loading"
                      ? "githubSettings.repositories.refreshing"
                      : github.refreshState === "success"
                        ? "githubSettings.repositories.refreshed"
                        : "githubSettings.repositories.refresh",
                  )}
                </button>
                <button
                  className="github-settings__button github-settings__button--primary"
                  type="button"
                  onClick={() => void github.openExternalUrl(connection.authorizationUrl)}
                >
                  <ArrowSquareOut size={16} aria-hidden="true" />
                  {t("githubSettings.repositories.manage")}
                </button>
              </div>
            </div>
            {connection.repositories.length > 0 ? (
              <div className="github-settings__repositories">
                {connection.repositories.map((repository) => (
                  <div className="github-settings__repository" key={repository.id}>
                    <GithubLogo size={18} aria-hidden="true" />
                    <span>{repository.fullName}</span>
                    <small>
                      {repository.private
                        ? t("githubSettings.repositories.private")
                        : t("githubSettings.repositories.public")}
                      {" · "}
                      {repository.canPush
                        ? t("githubSettings.repositories.readWrite")
                        : t("githubSettings.repositories.readOnly")}
                    </small>
                  </div>
                ))}
              </div>
            ) : (
              <div className="github-settings__empty">{t("githubSettings.repositories.empty")}</div>
            )}
          </section>
          </>
        ) : (
          <section className="github-settings__login">
          <GithubLogo className="github-settings__login-mark" size={96} weight="duotone" aria-hidden="true" />
          <div className="github-settings__login-intro">
            <h3>{t("githubSettings.login.title")}</h3>
          </div>
          {github.flow ? (
            <div className="github-settings__device-flow">
              <strong>{github.flow.userCode}</strong>
              <p>{t("githubSettings.login.waiting")}</p>
              <div>
                <button className="github-settings__button" type="button" onClick={github.cancelLogin}>
                  {t("githubSettings.login.cancel")}
                </button>
                <button
                  className={`github-settings__button github-settings__button--primary github-settings__copy-button${isCodeCopied ? " github-settings__copy-button--copied" : ""}`}
                  type="button"
                  onClick={() => void copyDeviceCode()}
                >
                  {t("githubSettings.login.copyCode")}
                </button>
              </div>
            </div>
          ) : (
            <button
              className="github-settings__button github-settings__button--primary github-settings__login-button"
              type="button"
              disabled={github.isStarting}
              onClick={() => void github.startLogin()}
            >
              <GithubLogo size={18} weight="fill" aria-hidden="true" />
              {github.isStarting ? t("githubSettings.login.starting") : t("githubSettings.login.action")}
            </button>
          )}
          </section>
        )}
      </SettingsViewStage>
    </div>
  );
}

const githubSettingsTabs: ReadonlyArray<{
  id: GithubSettingsTab;
  labelKey: TranslationKey;
}> = [
  { id: "login", labelKey: "githubSettings.tabs.login" },
  { id: "quick-start", labelKey: "githubSettings.tabs.quickStart" },
  { id: "capabilities", labelKey: "githubSettings.tabs.capabilities" },
  { id: "repository-sync", labelKey: "githubSettings.tabs.repositorySync" },
  { id: "faq", labelKey: "githubSettings.tabs.faq" },
];

const githubSettingsViewOrder: readonly GithubSettingsTab[] = [
  "login",
  "quick-start",
  "capabilities",
  "repository-sync",
  "faq",
];

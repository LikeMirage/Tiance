import { useEffect } from "react";
import {
  ArrowClockwise,
  ArrowSquareOut,
  CheckCircle,
  GithubLogo,
  SignOut,
} from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import { useGithubConnection } from "../model/useGithubConnection";
import "./github-settings.css";

type GithubSettingsPanelProps = {
  onReady?: () => void;
};

export function GithubSettingsPanel({ onReady }: GithubSettingsPanelProps) {
  const { t } = useI18n();
  const github = useGithubConnection();

  useEffect(() => {
    onReady?.();
  }, [onReady]);

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
          <p>{t("githubSettings.description")}</p>
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

      {github.error ? <div className="github-settings__error" role="alert">{github.error}</div> : null}

      {connection?.connected && account ? (
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
          <GithubLogo size={44} weight="duotone" aria-hidden="true" />
          <div>
            <h3>{t("githubSettings.login.title")}</h3>
            <p>{t("githubSettings.login.description")}</p>
          </div>
          {github.flow ? (
            <div className="github-settings__device-flow">
              <span>{t("githubSettings.login.codeLabel")}</span>
              <strong>{github.flow.userCode}</strong>
              <p>{t("githubSettings.login.waiting")}</p>
              <div>
                <button className="github-settings__button" type="button" onClick={github.cancelLogin}>
                  {t("githubSettings.login.cancel")}
                </button>
                <button
                  className="github-settings__button github-settings__button--primary"
                  type="button"
                  onClick={() => void github.openExternalUrl(github.flow?.verificationUri ?? "")}
                >
                  <ArrowSquareOut size={16} aria-hidden="true" />
                  {t("githubSettings.login.openAgain")}
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
    </div>
  );
}

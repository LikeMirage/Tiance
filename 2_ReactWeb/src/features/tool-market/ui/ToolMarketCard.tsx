import { useI18n } from "../../../shared/i18n";
import type { ToolMarketTool } from "../model/toolMarket";
import type { ToolInstallState } from "../model/useToolMarket";

export function ToolMarketCard({
  installState, language, onInstall, tool,
}: {
  installState?: ToolInstallState;
  language: string;
  onInstall: () => void;
  tool: ToolMarketTool;
}) {
  const { t } = useI18n();
  const isInstalling = installState?.phase === "installing";
  const isInstalled = tool.installationStatus === "installed";
  const errorMessage = installState?.phase === "error"
    ? installState.error ?? t("toolMarket.install.failed")
    : null;

  return (
    <article className="role-market-card tool-market-card">
      <header className="role-market-card__header">
        <div className="role-market-card__identity">
          <strong title={tool.displayName}>{tool.displayName}</strong>
          <span>{tool.callName} · {tool.runtime}</span>
        </div>
        <span className={`role-market-card__status role-market-card__status--${tool.installationStatus}`}>
          {statusLabel(tool.installationStatus, t)}
        </span>
      </header>
      <p className="role-market-card__summary">{tool.summary}</p>
      <footer className="role-market-card__footer">
        <div className="role-market-card__details">
          <span className="role-market-card__metadata">
            {tool.author} · v{tool.version} · {tool.compatibility.platforms.join(" / ")} · {formatBytes(tool.size, language)}
          </span>
          {errorMessage ? <span className="role-market-card__error" title={errorMessage}>{errorMessage}</span> : null}
        </div>
        <button
          className="role-market-card__action"
          type="button"
          disabled={isInstalling || isInstalled}
          onClick={onInstall}
        >
          {isInstalling
            ? t("toolMarket.install.installingShort")
            : isInstalled
              ? t("toolMarket.install.installed")
              : tool.installationStatus === "update-available"
                ? t("toolMarket.install.update")
                : errorMessage
                  ? t("common.actions.retry")
                  : t("toolMarket.install.download")}
        </button>
      </footer>
    </article>
  );
}

function statusLabel(status: ToolMarketTool["installationStatus"], t: ReturnType<typeof useI18n>["t"]) {
  if (status === "installed") return t("toolMarket.statuses.installed");
  if (status === "update-available") return t("toolMarket.statuses.update-available");
  if (status === "call-name-conflict") return t("toolMarket.statuses.call-name-conflict");
  return t("toolMarket.statuses.not-installed");
}

function formatBytes(value: number, language: string) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(size)} ${units[unitIndex]}`;
}

import type { AppStatusBarContent } from "../model/appStatusBar";
import type { ReactNode } from "react";
import { useI18n } from "../../../shared/i18n";

type AppStatusBarProps = {
  content: AppStatusBarContent;
  systemRight?: ReactNode;
};

export function AppStatusBar({ content, systemRight }: AppStatusBarProps) {
  const { t } = useI18n();
  if (content.visible === false) {
    return null;
  }

  return (
    <footer className="app-status-bar" aria-label={t("appFrame.statusBar")}>
      <div className="app-status-bar__slot app-status-bar__slot--left">
        {content.left}
      </div>
      <div className="app-status-bar__slot app-status-bar__slot--center">
        {content.center}
      </div>
      <div className="app-status-bar__slot app-status-bar__slot--right">
        {content.right ? (
          <div className="app-status-bar__page-right">
            {content.right}
          </div>
        ) : null}
        {systemRight ? (
          <div className="app-status-bar__system-right">
            {systemRight}
          </div>
        ) : null}
      </div>
    </footer>
  );
}

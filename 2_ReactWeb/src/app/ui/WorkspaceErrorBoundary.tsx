import { Component, type ErrorInfo, type ReactNode } from "react";

import { useI18n } from "../../shared/i18n";
import { dismissFrontendBootPlaceholder } from "../../shared/model/startup-timing/startupTiming";
import { recordFrontendError } from "../model/frontendErrorLog";

import "./workspace-error-boundary.css";

export class WorkspaceErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    recordFrontendError(error, info);
    dismissFrontendBootPlaceholder();
  }

  render() {
    return this.state.failed ? <WorkspaceRecovery /> : this.props.children;
  }
}

function WorkspaceRecovery() {
  const { t } = useI18n();
  return (
    <main className="workspace-recovery">
      <section className="workspace-recovery__panel" role="alert">
        <h1>{t("common.frontendRecovery.title")}</h1>
        <p>{t("common.frontendRecovery.description")}</p>
        <button type="button" onClick={() => window.location.reload()}>
          {t("common.frontendRecovery.reload")}
        </button>
      </section>
    </main>
  );
}

import { Pulse } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import { useI18n } from "../../../shared/i18n";
import type { SystemMetricsSnapshot } from "../../../shared/types/desktopShell";
import { useWorkspaceUsageSummary } from "../model/useWorkspaceUsageSummary";
import { WorkspaceUsagePanel } from "./WorkspaceUsagePanel";

const SYSTEM_METRICS_POLL_INTERVAL_MS = 5_000;

type ReadySystemMetricsSnapshot = SystemMetricsSnapshot & {
  app: NonNullable<SystemMetricsSnapshot["app"]>;
  system: NonNullable<SystemMetricsSnapshot["system"]>;
};

type MetricsStatus =
  | {
      metrics: ReadySystemMetricsSnapshot;
      state: "ready";
    }
  | {
      message: string;
      metrics: null;
      state: "loading" | "unavailable";
    };

export function SystemMetricsStatus() {
  const { language, t } = useI18n();
  const { state } = useDesktopShell();
  const [activeTab, setActiveTab] = useState<"performance" | "usage">("performance");
  const [metricsStatus, setMetricsStatus] = useState<MetricsStatus>({
    message: t("appFrame.metrics.loading"),
    metrics: null,
    state: "loading",
  });

  useEffect(() => {
    if (!state.available) {
      setMetricsStatus({
        message: t("appFrame.metrics.shellDisconnected"),
        metrics: null,
        state: "unavailable",
      });
      return;
    }

    let cancelled = false;
    let timerId = 0;

    const markUnavailable = (message: string) => {
      if (!cancelled) {
        setMetricsStatus({
          message,
          metrics: null,
          state: "unavailable",
        });
      }
    };

    const loadMetrics = async () => {
      const api = window.pywebview?.api;
      if (!api?.get_system_metrics) {
        markUnavailable(t("appFrame.metrics.apiUnavailable"));
        return;
      }

      try {
        const nextMetrics = await api.get_system_metrics();
        if (cancelled) {
          return;
        }

        const { app, system } = nextMetrics;
        if (nextMetrics.available && app && system) {
          setMetricsStatus({
            metrics: {
              ...nextMetrics,
              app,
              system,
            },
            state: "ready",
          });
          return;
        }
        markUnavailable(nextMetrics.reason || t("appFrame.metrics.dataUnavailable"));
      } catch {
        markUnavailable(t("appFrame.metrics.readFailed"));
      }
    };

    const scheduleMetricsLoad = () => {
      if (cancelled) {
        return;
      }
      timerId = window.setTimeout(() => {
        void loadMetrics().finally(scheduleMetricsLoad);
      }, SYSTEM_METRICS_POLL_INTERVAL_MS);
    };

    void loadMetrics().finally(scheduleMetricsLoad);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [state.available, t]);

  const summary = useMemo(() => {
    if (metricsStatus.state !== "ready") {
      return metricsStatus.state === "loading"
        ? t("appFrame.metrics.statusLoading")
        : t("appFrame.metrics.statusUnavailable");
    }
    return `CPU ${formatPercent(metricsStatus.metrics.app.cpuPercent)} · ${formatBytes(
      metricsStatus.metrics.app.memoryBytes,
    )}`;
  }, [metricsStatus, t]);

  const metrics = metricsStatus.state === "ready" ? metricsStatus.metrics : null;
  const usageSummaryModel = useWorkspaceUsageSummary(activeTab === "usage");

  return (
    <div className="system-metrics-status">
      <button
        type="button"
        className="system-metrics-status__trigger"
        aria-label={t("appFrame.metrics.aria")}
      >
        <Pulse size={13} weight="bold" aria-hidden="true" />
        <span>{summary}</span>
      </button>
      <div
        className="system-metrics-popover"
        role="dialog"
        aria-label={t("appFrame.metrics.panelAria")}
      >
        <div className="system-metrics-popover__tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "performance"}
            aria-controls="system-metrics-performance-panel"
            className={activeTab === "performance" ? "is-active" : undefined}
            onClick={() => setActiveTab("performance")}
          >
            {t("appFrame.metrics.performanceTab")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "usage"}
            aria-controls="system-metrics-usage-panel"
            className={activeTab === "usage" ? "is-active" : undefined}
            onClick={() => setActiveTab("usage")}
          >
            {t("appFrame.metrics.usageTab")}
          </button>
        </div>
        {activeTab === "performance" ? (
          <div id="system-metrics-performance-panel" role="tabpanel">
            <div className="system-metrics-popover__header">
              <span>{t("appFrame.metrics.title")}</span>
              <span>
                {metrics ? formatSampleTime(metrics.sampledAt, language) : getStatusLabel(metricsStatus.state, t)}
              </span>
            </div>
            {metrics ? (
              <>
                <MetricRow
                  label={t("appFrame.metrics.app")}
                  primary={`CPU ${formatPercent(metrics.app.cpuPercent)}`}
                  secondary={`${formatBytes(metrics.app.memoryBytes)} · ${t("appFrame.metrics.processCount", { count: metrics.app.processCount })}`}
                />
                <MetricRow
                  label={t("appFrame.metrics.system")}
                  primary={`CPU ${formatPercent(metrics.system.cpuPercent)}`}
                  secondary={t("appFrame.metrics.memory", {
                    percent: formatPercent(metrics.system.memoryPercent),
                    used: formatBytes(metrics.system.memoryUsedBytes),
                    total: formatBytes(metrics.system.memoryTotalBytes),
                  })}
                />
                {metrics.processes && metrics.processes.length > 0 ? (
                  <div className="system-metrics-popover__processes">
                    {metrics.processes.slice(0, 4).map((process) => (
                      <div key={process.pid} className="system-metrics-popover__process">
                        <span>{process.name}</span>
                        <span>
                          {formatPercent(process.cpuPercent)} · {formatBytes(process.memoryBytes)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <div className="system-metrics-popover__empty">
                {metricsStatus.state !== "ready" ? metricsStatus.message : null}
              </div>
            )}
          </div>
        ) : (
          <div id="system-metrics-usage-panel" role="tabpanel">
            <WorkspaceUsagePanel
              summary={usageSummaryModel.summary}
              onConversationCountChange={usageSummaryModel.setConversationTotal}
            />
          </div>
        )}
      </div>
    </div>
  );
}

type MetricRowProps = {
  label: string;
  primary: string;
  secondary: string;
};

function MetricRow({ label, primary, secondary }: MetricRowProps) {
  return (
    <div className="system-metrics-popover__row">
      <span className="system-metrics-popover__label">{label}</span>
      <span className="system-metrics-popover__primary">{primary}</span>
      <span className="system-metrics-popover__secondary">{secondary}</span>
    </div>
  );
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0MB";
  }
  const megabytes = bytes / 1024 / 1024;
  if (megabytes < 1024) {
    return `${Math.round(megabytes)}MB`;
  }
  return `${(megabytes / 1024).toFixed(1)}GB`;
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) {
    return "0%";
  }
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded}%`;
}

function formatSampleTime(value: string, language: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString(language, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getStatusLabel(state: MetricsStatus["state"], t: ReturnType<typeof useI18n>["t"]) {
  if (state === "loading") {
    return t("appFrame.metrics.reading");
  }
  if (state === "unavailable") {
    return t("appFrame.metrics.unavailable");
  }
  return "";
}

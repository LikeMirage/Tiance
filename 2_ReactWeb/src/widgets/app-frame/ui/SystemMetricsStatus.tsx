import { Pulse } from "@phosphor-icons/react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import { useI18n } from "../../../shared/i18n";
import type { WorkspaceStatisticsKind } from "../../../services/workspace/getWorkspaceStatistics";
import { localMonth } from "../model/statisticFormatting";
import { WorkspaceUsagePanel } from "./WorkspaceUsagePanel";
import { SystemPerformancePanel } from "./SystemPerformancePanel";
import { useWorkspaceStorage } from "../model/useWorkspaceStorage";
import { useSystemMetrics } from "../model/useSystemMetrics";
import { formatMetricBytes as formatBytes, formatMetricPercent as formatPercent } from "../model/metricsFormatting";

export function SystemMetricsStatus() {
  const { t } = useI18n();
  const { state } = useDesktopShell();
  const [activeTab, setActiveTab] = useState<"performance" | WorkspaceStatisticsKind>("performance");
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(localMonth);
  const containerRef = useRef<HTMLDivElement>(null);
  const closeTimerRef = useRef(0);
  const panelId = useId();
  const tabs = ["performance", "tokens", "runtime", "tools"] as const;
  const tabLabels = ["performanceTab", "usageTab", "runtimeTab", "toolsTab"] as const;
  const show = () => {
    window.clearTimeout(closeTimerRef.current);
    setOpen(true);
  };
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) setOpen(false);
    };
    if (open) document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => () => window.clearTimeout(closeTimerRef.current), []);
  const { status: metricsStatus } = useSystemMetrics(state.available, open && activeTab === "performance");

  const { data: storage, error: storageError } = useWorkspaceStorage(state.available && open && activeTab === "performance");

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

  return (
    <div className="system-metrics-status" ref={containerRef}
      onMouseEnter={show}
      onMouseLeave={() => {
        closeTimerRef.current = window.setTimeout(() => {
          if (!containerRef.current?.contains(document.activeElement)) setOpen(false);
        }, 180);
      }}
      onFocusCapture={show}
      onBlurCapture={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={event => {
        if (event.key === "Escape") {
          event.stopPropagation();
          containerRef.current?.querySelector<HTMLButtonElement>(".system-metrics-status__trigger")?.focus();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className="system-metrics-status__trigger"
        aria-label={t("appFrame.metrics.aria")}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={show}
      >
        <Pulse size={13} weight="bold" aria-hidden="true" />
        <span>{summary}</span>
      </button>
      <div
        className="system-metrics-popover"
        id={panelId}
        data-open={open}
        aria-hidden={!open}
        role="dialog"
        aria-label={t("appFrame.metrics.panelAria")}
      >
        <div className="system-metrics-popover__tabs" role="tablist" onKeyDown={event => {
          const index = tabs.indexOf(activeTab);
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
            : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
            : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next !== null) {
            event.preventDefault();
            setActiveTab(tabs[next]);
            document.getElementById(`${panelId}-${tabs[next]}`)?.focus();
          }
        }}>
          {tabs.map((tab, index) => <button key={tab} type="button" role="tab"
            id={`${panelId}-${tab}`} tabIndex={activeTab === tab ? 0 : -1}
            aria-selected={activeTab === tab} aria-controls={`${panelId}-content`}
            className={activeTab === tab ? "is-active" : undefined}
            onClick={() => setActiveTab(tab)}>{t(`appFrame.metrics.${tabLabels[index]}`)}</button>)}
        </div>
        <div id={`${panelId}-content`} role="tabpanel" aria-labelledby={`${panelId}-${activeTab}`}
          className="system-metrics-popover__body">
        {activeTab === "performance" ? (
          metrics ? <SystemPerformancePanel metrics={metrics} storage={storage} storageError={storageError} /> :
            <div className="system-metrics-popover__empty">
              {metricsStatus.state !== "ready" ? t(`appFrame.metrics.${metricsStatus.message}`) : null}
            </div>
        ) : (
          <WorkspaceUsagePanel kind={activeTab} month={month} visible={open} onMonthChange={setMonth} onRequestOpen={show} />
        )}
        </div>
      </div>
    </div>
  );
}

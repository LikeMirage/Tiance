import { Cpu, HardDrive, Memory } from "@phosphor-icons/react";
import { useI18n } from "../../../shared/i18n";
import { formatMetricBytes, formatMetricPercent } from "../model/metricsFormatting";
import type { ReadySystemMetrics } from "../model/useSystemMetrics";
import type { WorkspaceStorage } from "../../../services/workspace/getWorkspaceStorage";
import "./system-performance-panel.css";

type Props = { metrics: ReadySystemMetrics; storage: WorkspaceStorage | null; storageError: boolean };

export function SystemPerformancePanel({ metrics, storage, storageError }: Props) {
  const { language, t } = useI18n();
  const { app, system } = metrics;
  const sampledAt = new Date(metrics.sampledAt);
  const clock = Number.isNaN(sampledAt.getTime()) ? "" : sampledAt.toLocaleTimeString(language,
    { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return <div className="system-performance">
    <div className="system-performance__heading"><span>{t("appFrame.metrics.app")}</span><time>{clock}</time></div>
    <div className="system-performance__columns">
      <section className="performance-metric performance-metric--cpu">
        <div className="performance-metric__label"><Cpu size={14} /><span>CPU</span></div>
        <strong className="performance-metric__value">{formatMetricPercent(app.cpuPercent)}</strong>
      </section>
      <section className="performance-metric performance-metric--memory">
        <div className="performance-metric__label"><Memory size={14} /><span>{t("appFrame.metrics.memoryLabel")}</span><small>{t("appFrame.metrics.processCount", { count: app.processCount })}</small></div>
        <strong className="performance-metric__value">{formatMetricBytes(app.memoryBytes)}</strong>
      </section>
    </div>
    <div className="system-performance__heading system-performance__heading--system"><span>{t("appFrame.metrics.system")}</span><span>{t("appFrame.metrics.availableMemory", { value: formatMetricBytes(system.memoryAvailableBytes) })}</span></div>
    <div className="system-performance__columns">
      <section className="performance-metric performance-metric--cpu performance-metric--system">
        <div className="performance-metric__label"><Cpu size={14} /><span>CPU</span></div>
        <div className="performance-metric__gauge-row"><strong className="performance-metric__value">{formatMetricPercent(system.cpuPercent)}</strong><UsageRing value={system.cpuPercent} /></div>
        <UsageBar value={system.cpuPercent} label={t("appFrame.metrics.systemCpu")} />
      </section>
      <section className="performance-metric performance-metric--memory performance-metric--system">
        <div className="performance-metric__label"><Memory size={14} /><span>{t("appFrame.metrics.memoryLabel")}</span></div>
        <div className="performance-metric__gauge-row"><strong className="performance-metric__value">{formatMetricPercent(system.memoryPercent)}</strong><UsageRing value={system.memoryPercent} /></div>
        <UsageBar value={system.memoryPercent} label={t("appFrame.metrics.systemMemory")} />
        <small className="performance-metric__capacity">{formatMetricBytes(system.memoryUsedBytes)} / {formatMetricBytes(system.memoryTotalBytes)}</small>
      </section>
    </div>
    <section className="performance-storage" title={t("appFrame.metrics.storageScope")}>
      <div className="system-performance__heading"><span className="performance-storage__label"><HardDrive size={14} />{t("appFrame.metrics.storageLabel")}</span>
        <strong>{storageError ? "—" : storage ? `${storage.complete ? "" : "≥ "}${formatMetricBytes(storage.total_bytes)}` : "—"}</strong>
      </div>
      {storage && !storageError ? <>
        <div className="performance-storage__bar" data-empty={storage.total_bytes === 0} aria-hidden="true"><span style={{ width: `${storage.total_bytes ? storage.database_bytes / storage.total_bytes * 100 : 0}%` }} /></div>
        <div className="performance-storage__details"><span>{t("appFrame.metrics.storageDatabase")} {formatMetricBytes(storage.database_bytes)}</span><span>{t("appFrame.metrics.storageOther")} {formatMetricBytes(storage.other_bytes)}</span></div>
        {!storage.complete ? <small>{t("appFrame.metrics.storagePartial")}</small> : null}
      </> : <small>{t(storageError ? "appFrame.metrics.storageFailed" : "appFrame.metrics.loading")}</small>}
    </section>
  </div>;
}

function UsageRing({ value }: { value: number | null }) {
  const percent = Math.max(0, Math.min(100, value ?? 0));
  return <svg className="performance-ring" viewBox="0 0 44 44" aria-hidden="true">
    <circle cx="22" cy="22" r="17" className="performance-ring__track" />
    <circle cx="22" cy="22" r="17" pathLength="100" strokeDasharray={`${percent} 100`} transform="rotate(-90 22 22)" />
  </svg>;
}

function UsageBar({ value, label }: { value: number | null; label: string }) {
  return <div className="performance-meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
    aria-valuenow={value === null ? undefined : value} aria-valuetext={formatMetricPercent(value)}>
    <span style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} />
  </div>;
}

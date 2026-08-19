import { memo, useState } from "react";
import { ArrowSquareIn, FolderOpen } from "@phosphor-icons/react";

import type { ToolCallRecordSummaryItem } from "../../../entities/tool/model/toolCallRecord";
import type { ToolFolder, Toolset } from "../../../entities/tool/model/toolset";
import { useToolsetCallRecordSummary } from "../model/useToolsetCallRecordSummary";
import { useToolRuntimeSettings } from "../model/useToolRuntimeSettings";

import "./toolset-overview.css";

type ToolsetOverviewProps = {
  error?: string | null;
  folders: ToolFolder[];
  isActive?: boolean;
  onOpenFolder: (folderId: string) => void;
  onSelectFolder: (folderId: string) => void;
  onReload: () => void;
  onRevealFolder: (folderId: string) => Promise<void>;
  readonly: boolean;
  selectedFolderId: string | null;
  state: "idle" | "loading" | "ready" | "error";
  toolset: Toolset | null;
};

export const ToolsetOverview = memo(function ToolsetOverview({
  error = null,
  folders,
  isActive = true,
  onOpenFolder,
  onSelectFolder,
  onReload,
  onRevealFolder,
  readonly,
  selectedFolderId,
  state,
  toolset,
}: ToolsetOverviewProps) {
  const [revealingFolderId, setRevealingFolderId] = useState<string | null>(null);
  const callSummary = useToolsetCallRecordSummary(toolset?.category_id ?? null, { isActive });
  const runtimeSettings = useToolRuntimeSettings({
    itemsByFolderId: callSummary.itemsByFolderId,
    onReload: callSummary.reload,
    readonly,
    summaryVersion: callSummary.summary,
    toolsetId: toolset?.category_id ?? null,
  });

  if (!toolset) {
    return <div className="toolset-overview__status">请选择一个工具集。</div>;
  }

  if (state === "loading" && folders.length === 0) {
    return <div className="toolset-overview__status">正在载入工具集总览……</div>;
  }

  if (state === "error") {
    return (
      <div className="toolset-overview__status toolset-overview__status--error">
        <span>{error ?? "工具集总览载入失败。"}</span>
        <button type="button" onClick={onReload}>
          重试
        </button>
      </div>
    );
  }

  const rootClassName = [
    "toolset-overview",
    callSummary.state === "loading" ? "toolset-overview--summary-loading" : "",
  ].filter(Boolean).join(" ");

  return (
    <section className={rootClassName} aria-label={`${toolset.name} 工具集总览`}>
      {error && state === "ready" ? (
        <div className="toolset-overview__inline-error" role="status">
          {error}
        </div>
      ) : null}

      {callSummary.error ? (
        <div className="toolset-overview__inline-error" role="status">
          {callSummary.error}
        </div>
      ) : runtimeSettings.error ? (
        <div className="toolset-overview__inline-error" role="status">
          {runtimeSettings.error}
        </div>
      ) : callSummary.state === "loading" && !callSummary.summary ? (
        <div className="toolset-overview__inline-note" role="status">
          正在读取调用统计。
        </div>
      ) : null}

      {folders.length > 0 ? (
        <div className="toolset-overview__grid">
          {folders.map((folder) => {
            const stats = callSummary.itemsByFolderId.get(folder.project_id) ?? null;
            const displayStats = runtimeSettings.resolveStats(folder.project_id, stats);
            const effectiveEnabled = displayStats?.enabled ?? null;
            const effectiveDynamic = displayStats?.dynamic ?? null;
            const effectiveParallel = displayStats?.parallel ?? null;
            const canUpdateRuntime = !readonly && stats != null;
            const isUpdatingRuntime = runtimeSettings.updatingFolderId === folder.project_id;
            const injectionMetric = getInjectionMetric(displayStats);
            return (
              <article
                className={
                  selectedFolderId === folder.project_id
                    ? "toolset-overview__card toolset-overview__card--selected"
                    : "toolset-overview__card"
                }
                key={folder.project_id}
                onClick={() => onSelectFolder(folder.project_id)}
                onDoubleClick={() => onOpenFolder(folder.project_id)}
              >
                <header className="toolset-overview__card-header">
                  <h3 className="toolset-overview__folder-name" title={folder.name}>
                    {folder.name}
                  </h3>
                  <div className="toolset-overview__card-actions">
                    <button
                      className="toolset-overview__card-action"
                      type="button"
                      aria-label={`进入 ${folder.name}`}
                      title="进入工具工作区"
                      onClick={() => onOpenFolder(folder.project_id)}
                    >
                      <ArrowSquareIn size={15} weight="regular" aria-hidden="true" />
                    </button>
                    <button
                      className="toolset-overview__card-action"
                      type="button"
                      aria-label={`在资源管理器中显示 ${folder.name}`}
                      title="在资源管理器中显示"
                      disabled={revealingFolderId === folder.project_id}
                      onClick={() => {
                        setRevealingFolderId(folder.project_id);
                        void onRevealFolder(folder.project_id)
                          .catch(() => undefined)
                          .finally(() => {
                            setRevealingFolderId((current) =>
                              current === folder.project_id ? null : current,
                            );
                          });
                      }}
                    >
                      <FolderOpen size={15} weight="regular" aria-hidden="true" />
                    </button>
                  </div>
                </header>

                <div className="toolset-overview__activity" aria-label={`${folder.name} 调用统计`}>
                  <span className="toolset-overview__call-count">
                    <strong>{formatInteger(stats?.call_count ?? 0)}</strong>
                    <small>次调用</small>
                  </span>
                  <span className="toolset-overview__highlights">
                    <Metric label="成功" value={formatSuccessRate(stats)} />
                    <Metric label="平均" value={formatElapsed(stats?.average_elapsed_ms ?? null)} />
                  </span>
                </div>

                <div className="toolset-overview__metadata">
                  <span>
                    注入 <strong>{injectionMetric.value}</strong>
                    {injectionMetric.detail ? <small>{injectionMetric.detail}</small> : null}
                  </span>
                  <span>全局 <strong>{formatPercent(stats?.global_call_share ?? 0)}</strong></span>
                </div>

                <footer className="toolset-overview__card-footer">
                  <span className="toolset-overview__runtime-switches">
                    <RuntimeSwitch
                      checked={effectiveEnabled === true}
                      disabled={!canUpdateRuntime || effectiveEnabled == null || isUpdatingRuntime}
                      label="启用"
                      onChange={() => {
                        if (displayStats) void runtimeSettings.updateSetting(folder, displayStats, "enabled");
                      }}
                    />
                    <RuntimeSwitch
                      checked={effectiveDynamic === true}
                      disabled={!canUpdateRuntime || effectiveDynamic == null || isUpdatingRuntime}
                      label="动态"
                      onChange={() => {
                        if (displayStats) void runtimeSettings.updateSetting(folder, displayStats, "dynamic");
                      }}
                    />
                    <RuntimeSwitch
                      checked={effectiveParallel === true}
                      disabled={!canUpdateRuntime || effectiveParallel == null || isUpdatingRuntime}
                      label="并发"
                      onChange={() => {
                        if (displayStats) void runtimeSettings.updateSetting(folder, displayStats, "parallel");
                      }}
                    />
                  </span>
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="toolset-overview__empty">
          当前工具集没有工具。
        </div>
      )}
    </section>
  );
});

function RuntimeSwitch({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      className={[
        "toolset-overview__runtime-switch",
        checked ? "toolset-overview__runtime-switch--on" : "",
      ].filter(Boolean).join(" ")}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      title={`切换${label}`}
      onClick={(event) => {
        event.stopPropagation();
        onChange();
      }}
    >
      <span>{label}</span>
      <i aria-hidden="true" />
    </button>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <span className="toolset-overview__metric">
      <span className="toolset-overview__metric-label">{label}</span>
      <strong className="toolset-overview__metric-value">{value}</strong>
    </span>
  );
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatPercent(value: number) {
  const safeValue = Number.isFinite(value) ? value : 0;
  if (safeValue > 0 && safeValue < 0.001) return "<0.1%";
  return `${(safeValue * 100).toFixed(1)}%`;
}

function formatSuccessRate(stats: ToolCallRecordSummaryItem | null) {
  const count = stats?.call_count ?? 0;
  if (count <= 0) return "-";
  return formatPercent((stats?.success_count ?? 0) / count);
}

function getInjectionMetric(stats: ToolCallRecordSummaryItem | null) {
  if (!stats) return { detail: undefined, value: "-" };
  return stats.dynamic === true
    ? { detail: "动态", value: formatInteger(stats.dynamic_injection_char_count) }
    : { detail: "全量", value: formatInteger(stats.full_injection_char_count) };
}

function formatElapsed(value: number | null) {
  if (value === null) return "-";
  if (value < 1000) return `${value}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

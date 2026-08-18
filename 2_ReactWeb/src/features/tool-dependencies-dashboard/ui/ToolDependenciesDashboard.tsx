import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, DownloadSimple } from "@phosphor-icons/react";

import type {
  ToolDependency,
  ToolDependencyInstallTaskStatus,
  ToolDependencyListResponse,
  ToolDependencyStatus,
} from "../../../entities/tool/model/toolDependency";
import {
  getToolDependencyInstallTask,
  getToolFolderDependencies,
  startToolFolderDependencyInstallTask,
  uninstallToolFolderDependency,
} from "../../../services/tools/toolDependencies";
import "./tool-dependencies-dashboard.css";

type LoadState = "loading" | "ready" | "error";

type ToolDependenciesDashboardProps = {
  folderId: string;
  toolsetId: string;
};

type DependencyActionKey = `install:${string}` | `uninstall:${string}`;

export function ToolDependenciesDashboard({
  folderId,
  toolsetId,
}: ToolDependenciesDashboardProps) {
  const targetKey = `${toolsetId}:${folderId}`;
  const activeTargetKeyRef = useRef(targetKey);
  const requestIdRef = useRef(0);
  const completeTimerRef = useRef<number | null>(null);
  const installTaskTimerRef = useRef<number | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [report, setReport] = useState<ToolDependencyListResponse | null>(null);
  const [indexUrl, setIndexUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<DependencyActionKey | null>(null);
  const [completedAction, setCompletedAction] = useState<DependencyActionKey | null>(null);
  const [isBulkInstallRunning, setIsBulkInstallRunning] = useState(false);
  const [installTaskStatus, setInstallTaskStatus] = useState<ToolDependencyInstallTaskStatus | null>(null);

  useEffect(() => {
    activeTargetKeyRef.current = targetKey;
    requestIdRef.current += 1;
    setReport(null);
    setIndexUrl("");
    setError(null);
    setRunningAction(null);
    setCompletedAction(null);
    setIsBulkInstallRunning(false);
    setInstallTaskStatus(null);
    if (installTaskTimerRef.current !== null) {
      window.clearTimeout(installTaskTimerRef.current);
      installTaskTimerRef.current = null;
    }
  }, [targetKey]);

  useEffect(() => () => {
    if (completeTimerRef.current !== null) {
      window.clearTimeout(completeTimerRef.current);
    }
    if (installTaskTimerRef.current !== null) {
      window.clearTimeout(installTaskTimerRef.current);
    }
  }, []);

  const markActionComplete = useCallback((actionKey: DependencyActionKey) => {
    setCompletedAction(actionKey);
    if (completeTimerRef.current !== null) {
      window.clearTimeout(completeTimerRef.current);
    }
    completeTimerRef.current = window.setTimeout(() => {
      setCompletedAction((current) => current === actionKey ? null : current);
      completeTimerRef.current = null;
    }, 1000);
  }, []);

  const loadDependencies = useCallback(async (signal?: AbortSignal) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    setState("loading");
    setError(null);
    try {
      const nextReport = await getToolFolderDependencies(toolsetId, folderId, {
        signal,
      });
      if (activeTargetKeyRef.current !== targetKey || requestIdRef.current !== requestId) return;
      setReport(nextReport);
      setIndexUrl((current) => current.trim() || nextReport.index_url);
      setState("ready");
    } catch (err) {
      if (signal?.aborted || activeTargetKeyRef.current !== targetKey || requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "依赖读取失败。");
      setState("error");
    }
  }, [folderId, targetKey, toolsetId]);

  const finishInstallTask = useCallback((installTargetKey: string) => {
    if (activeTargetKeyRef.current !== installTargetKey) return;
    setRunningAction(null);
    setIsBulkInstallRunning(false);
    setInstallTaskStatus(null);
  }, []);

  const pollInstallTask = useCallback((
    taskId: string,
    installTargetKey: string,
    actionKey: DependencyActionKey,
  ) => {
    const poll = async () => {
      try {
        const task = await getToolDependencyInstallTask(taskId);
        if (activeTargetKeyRef.current !== installTargetKey) return;
        setInstallTaskStatus(task.status);
        if (task.status === "done") {
          if (task.report) {
            setReport(task.report);
            setIndexUrl(task.report.index_url);
          }
          markActionComplete(actionKey);
          setState("ready");
          finishInstallTask(installTargetKey);
          return;
        }
        if (task.status === "error") {
          setError(task.error || task.message || "依赖安装失败。");
          setState("error");
          finishInstallTask(installTargetKey);
          return;
        }
        installTaskTimerRef.current = window.setTimeout(poll, 1000);
      } catch (err) {
        if (activeTargetKeyRef.current !== installTargetKey) return;
        setError(err instanceof Error ? err.message : "依赖安装状态读取失败。");
        setState("error");
        finishInstallTask(installTargetKey);
      }
    };
    void poll();
  }, [finishInstallTask, markActionComplete]);

  useEffect(() => {
    const controller = new AbortController();
    void loadDependencies(controller.signal);
    return () => {
      controller.abort();
      requestIdRef.current += 1;
    };
  }, [loadDependencies]);

  const installDependency = async (requirement: string | null) => {
    if (runningAction || isBulkInstallRunning) return;
    const installTargetKey = targetKey;
    const actionKey: DependencyActionKey = `install:${requirement ?? "__all__"}`;
    setRunningAction(actionKey);
    setInstallTaskStatus("queued");
    setCompletedAction(null);
    setError(null);
    try {
      const task = await startToolFolderDependencyInstallTask(toolsetId, folderId, {
        requirement,
        index_url: indexUrl.trim() || null,
      });
      if (activeTargetKeyRef.current !== installTargetKey) return;
      setInstallTaskStatus(task.status);
      pollInstallTask(task.task_id, installTargetKey, actionKey);
    } catch (err) {
      if (activeTargetKeyRef.current !== installTargetKey) return;
      setError(err instanceof Error ? err.message : "依赖安装失败。");
      setState("error");
      finishInstallTask(installTargetKey);
    }
  };

  const installAllDependencies = async () => {
    if (runningAction || isBulkInstallRunning) return;
    const installTargetKey = targetKey;
    const targets = installableDependencies.map((dependency) => dependency.requirement);
    if (targets.length === 0) return;

    setIsBulkInstallRunning(true);
    setRunningAction("install:__all__");
    setInstallTaskStatus("queued");
    setCompletedAction(null);
    setError(null);
    try {
      const task = await startToolFolderDependencyInstallTask(toolsetId, folderId, {
        requirement: null,
        index_url: indexUrl.trim() || null,
      });
      if (activeTargetKeyRef.current !== installTargetKey) return;
      setInstallTaskStatus(task.status);
      pollInstallTask(task.task_id, installTargetKey, "install:__all__");
    } catch (err) {
      if (activeTargetKeyRef.current !== installTargetKey) return;
      setError(err instanceof Error ? err.message : "依赖安装失败。");
      setState("error");
      finishInstallTask(installTargetKey);
    }
  };

  const uninstallDependency = async (requirement: string) => {
    if (runningAction || isBulkInstallRunning) return;
    const uninstallTargetKey = targetKey;
    const actionKey: DependencyActionKey = `uninstall:${requirement}`;
    setRunningAction(actionKey);
    setCompletedAction(null);
    setError(null);
    try {
      const result = await uninstallToolFolderDependency(toolsetId, folderId, {
        requirement,
      });
      if (activeTargetKeyRef.current !== uninstallTargetKey) return;
      setReport(result.report);
      setState("ready");
    } catch (err) {
      if (activeTargetKeyRef.current !== uninstallTargetKey) return;
      setError(err instanceof Error ? err.message : "依赖卸载失败。");
      setState("error");
    } finally {
      if (activeTargetKeyRef.current === uninstallTargetKey) {
        setRunningAction(null);
      }
    }
  };

  const dependencies = report?.items ?? [];
  const installableDependencies = dependencies.filter((item) => isInstallableStatus(item.status));
  const isBusy = runningAction !== null || isBulkInstallRunning;
  const isBulkInstalling = isBulkInstallRunning;
  const isBulkInstallComplete = completedAction === "install:__all__";

  return (
    <article className="tool-dependencies-dashboard">
      <header className="tool-dependencies-dashboard__header">
        <div>
          <h1>工具依赖</h1>
          <ul className="tool-dependencies-dashboard__description">
            <li>读取当前工具的 program/requirements.txt，检查依赖是否已安装到工具专用 Python 环境。</li>
            <li>可修改镜像源后安装缺失或版本不匹配的依赖，不会影响后端自身依赖。</li>
            <li>依赖安装在当前工具目录的 dependencies/py313/ 专用环境中。</li>
          </ul>
        </div>
        <button
          className="tool-dependencies-dashboard__icon-button"
          type="button"
          aria-label="刷新依赖状态"
          title="刷新"
          disabled={state === "loading" || isBusy}
          onClick={() => { void loadDependencies(); }}
        >
          <ArrowClockwise size={15} weight="bold" aria-hidden="true" />
        </button>
      </header>

      <section className="tool-dependencies-dashboard__toolbar">
        <label className="tool-dependencies-dashboard__field">
          <span>镜像源</span>
          <input
            className="tool-dependencies-dashboard__input"
            value={indexUrl}
            disabled={isBusy}
            onChange={(event) => setIndexUrl(event.target.value)}
          />
        </label>
        <button
          className={[
            "tool-dependencies-dashboard__primary-button",
            isBulkInstalling ? "tool-dependencies-dashboard__primary-button--running" : "",
            isBulkInstallComplete ? "tool-dependencies-dashboard__primary-button--success" : "",
          ].filter(Boolean).join(" ")}
          type="button"
          disabled={isBusy || (!isBulkInstallComplete && installableDependencies.length === 0) || report?.pip_available === false}
          onClick={() => { void installAllDependencies(); }}
        >
          <DownloadSimple size={15} weight="bold" aria-hidden="true" />
          <span>
            {runningAction === "install:__all__"
              ? formatInstallTaskStatus(installTaskStatus)
              : isBulkInstallComplete
                ? "已完成"
                : "安装缺失依赖"}
          </span>
        </button>
      </section>

      {report?.pip_available === false ? (
        <div className="tool-dependencies-dashboard__notice tool-dependencies-dashboard__notice--error">
          内置 pip 不可用，暂时不能安装依赖。
        </div>
      ) : null}
      {error ? (
        <div className="tool-dependencies-dashboard__notice tool-dependencies-dashboard__notice--error" role="status">
          {error}
        </div>
      ) : null}

      <section className="tool-dependencies-dashboard__list" aria-label="依赖列表">
        <div className="tool-dependencies-dashboard__row tool-dependencies-dashboard__row--head">
          <span>依赖</span>
          <span>当前版本</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        {state === "loading" && dependencies.length === 0 ? (
          <div className="tool-dependencies-dashboard__empty">正在读取依赖。</div>
        ) : null}
        {state !== "loading" && dependencies.length === 0 ? (
          <div className="tool-dependencies-dashboard__empty">暂无依赖。</div>
        ) : null}
        {dependencies.map((dependency) => (
          <DependencyRow
            dependency={dependency}
            completedAction={completedAction}
            disabled={report?.pip_available === false}
            key={`${dependency.line_number}:${dependency.requirement}`}
            runningAction={runningAction}
            onInstall={() => { void installDependency(dependency.requirement); }}
            onUninstall={() => { void uninstallDependency(dependency.requirement); }}
          />
        ))}
      </section>
    </article>
  );
}

function DependencyRow({
  completedAction,
  dependency,
  disabled,
  runningAction,
  onInstall,
  onUninstall,
}: {
  completedAction: DependencyActionKey | null;
  dependency: ToolDependency;
  disabled: boolean;
  runningAction: DependencyActionKey | null;
  onInstall: () => void;
  onUninstall: () => void;
}) {
  const canInstall = isInstallableStatus(dependency.status);
  const canUninstall = dependency.status === "installed";
  const installActionKey: DependencyActionKey = `install:${dependency.requirement}`;
  const uninstallActionKey: DependencyActionKey = `uninstall:${dependency.requirement}`;
  const isInstalling = runningAction === installActionKey;
  const isUninstalling = runningAction === uninstallActionKey;
  const didInstall = completedAction === installActionKey;
  const isBusy = runningAction !== null;
  const buttonClassName = [
    "tool-dependencies-dashboard__secondary-button",
    canInstall ? "tool-dependencies-dashboard__secondary-button--install" : "",
    isInstalling || isUninstalling ? "tool-dependencies-dashboard__secondary-button--running" : "",
    didInstall ? "tool-dependencies-dashboard__secondary-button--success" : "",
    canUninstall ? "tool-dependencies-dashboard__secondary-button--danger" : "",
  ].filter(Boolean).join(" ");
  const buttonLabel = didInstall
    ? "已完成"
    : canUninstall
      ? isUninstalling ? "卸载中" : "卸载"
      : isInstalling ? "安装中" : "安装";
  return (
    <div className="tool-dependencies-dashboard__row">
      <div className="tool-dependencies-dashboard__dependency-name">
        <strong>{dependency.requirement}</strong>
        <span>{dependency.name || `第 ${dependency.line_number} 行`}</span>
      </div>
      <span>{dependency.installed_version || "未安装"}</span>
      <span className={buildStatusClassName(dependency.status)}>
        {formatStatus(dependency.status)}
      </span>
      <button
        className={buttonClassName}
        type="button"
        disabled={disabled || isBusy || didInstall || (!canInstall && !canUninstall)}
        onClick={canUninstall ? onUninstall : onInstall}
      >
        {buttonLabel}
      </button>
    </div>
  );
}

function isInstallableStatus(status: ToolDependencyStatus) {
  return status === "missing" || status === "version_mismatch";
}

function formatStatus(status: ToolDependencyStatus) {
  if (status === "installed") return "已安装";
  if (status === "missing") return "未安装";
  if (status === "version_mismatch") return "版本不匹配";
  return "格式无效";
}

function formatInstallTaskStatus(status: ToolDependencyInstallTaskStatus | null) {
  if (status === "queued") return "排队中";
  return "安装中";
}

function buildStatusClassName(status: ToolDependencyStatus) {
  return [
    "tool-dependencies-dashboard__status",
    `tool-dependencies-dashboard__status--${status}`,
  ].join(" ");
}

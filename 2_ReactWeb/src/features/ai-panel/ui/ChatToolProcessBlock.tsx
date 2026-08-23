import { useMemo, useState } from "react";
import { CaretDown, CaretRight, Check, X } from "@phosphor-icons/react";

import { submitToolPermissionDecision } from "../../../services/llm/submitToolPermissionDecision";

import type {
  ChatAssistantProcessItem,
  ChatToolProcessItem,
} from "../model/chatMessage";

export type ToolProcessEntry =
  | {
      id: string;
      type: "tool";
      tool: ChatToolProcessItem;
    }
  | Extract<ChatAssistantProcessItem, { type: "tool_preparing" }>;

export function toolProcessEntriesFromTools(items: ChatToolProcessItem[]): ToolProcessEntry[] {
  return items.map((tool) => ({
    id: tool.id,
    type: "tool" as const,
    tool,
  }));
}

export function ToolProcessBlock({
  clockTick,
  entries,
  isExpanded: controlledExpanded,
  onToggleExpanded,
}: {
  clockTick: number;
  entries: ToolProcessEntry[];
  isExpanded?: boolean;
  onToggleExpanded?: () => void;
}) {
  const [localExpanded, setLocalExpanded] = useState(false);
  const isExpanded = controlledExpanded ?? localExpanded;
  const toggleExpanded = onToggleExpanded ?? (() => setLocalExpanded((value) => !value));
  const toolSummary = useMemo(() => {
    const tools: ChatToolProcessItem[] = [];
    let preparingCount = 0;
    let preparingToolCount = 0;
    let runningCount = 0;
    let waitingPermissionCount = 0;
    let doneCount = 0;
    let errorCount = 0;
    let cancelledCount = 0;

    entries.forEach((entry) => {
      if (entry.type === "tool_preparing") {
        preparingCount += 1;
        return;
      }
      tools.push(entry.tool);
      if (entry.tool.status === "preparing") {
        preparingToolCount += 1;
      } else if (entry.tool.status === "running") {
        runningCount += 1;
      } else if (entry.tool.status === "waiting_permission") {
        waitingPermissionCount += 1;
      } else if (entry.tool.status === "done") {
        doneCount += 1;
      } else if (entry.tool.status === "error") {
        errorCount += 1;
      } else if (entry.tool.status === "cancelled") {
        cancelledCount += 1;
      }
    });

    return {
      cancelledCount,
      doneCount,
      errorCount,
      runningCount,
      tools,
      totalPreparingCount: preparingCount + preparingToolCount,
      waitingPermissionCount,
    };
  }, [entries]);
  const elapsedSeconds = resolveToolGroupElapsedSeconds(entries, clockTick);

  return (
    <section className="chat-msg__tools">
      <button
        className="chat-msg__tools-toggle"
        type="button"
        aria-expanded={isExpanded}
        onClick={toggleExpanded}
      >
        <span className="chat-msg__tools-caret" aria-hidden="true">
          {isExpanded ? (
            <CaretDown size={14} weight="bold" />
          ) : (
            <CaretRight size={14} weight="bold" />
          )}
        </span>
        <span className="chat-msg__tools-title">工具调用</span>
        <span className="chat-msg__tools-summary">
          {toolSummary.tools.length > 0 ? (
            <span className="chat-msg__tools-count">{toolSummary.tools.length} 个</span>
          ) : null}
          {toolSummary.doneCount > 0 ? (
            <span className="chat-msg__tools-status">完成 {toolSummary.doneCount}</span>
          ) : null}
          {toolSummary.errorCount > 0 ? (
            <span className="chat-msg__tools-status chat-msg__tools-status--error">
              失败 {toolSummary.errorCount}
            </span>
          ) : null}
          {toolSummary.cancelledCount > 0 ? (
            <span className="chat-msg__tools-status">
              已取消 {toolSummary.cancelledCount}
            </span>
          ) : null}
          {toolSummary.runningCount > 0 ? (
            <span className="chat-msg__tools-status chat-msg__tools-status--running">
              调用中 {toolSummary.runningCount}
            </span>
          ) : null}
          {toolSummary.waitingPermissionCount > 0 ? (
            <span className="chat-msg__tools-status chat-msg__tools-status--waiting">
              等待确认 {toolSummary.waitingPermissionCount}
            </span>
          ) : null}
          {toolSummary.totalPreparingCount > 0 ? (
            <span className="chat-msg__tools-status chat-msg__tools-status--running">
              准备中
            </span>
          ) : null}
          {elapsedSeconds !== null ? (
            <span className="chat-msg__tools-timer">
              {formatElapsedSeconds(elapsedSeconds)}
            </span>
          ) : null}
        </span>
      </button>
      {isExpanded ? (
        <div className="chat-msg__tools-list">
          {entries.map((entry) => (
            entry.type === "tool_preparing" ? (
              <ToolPreparingRow
                key={entry.id}
                clockTick={clockTick}
                item={entry}
              />
            ) : (
              <ToolProcessCard
                key={entry.id}
                clockTick={clockTick}
                item={entry.tool}
              />
            )
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ToolPreparingRow({
  clockTick,
  item,
}: {
  clockTick: number;
  item: Extract<ChatAssistantProcessItem, { type: "tool_preparing" }>;
}) {
  const elapsedSeconds = resolveToolPreparingElapsedSeconds(item, clockTick);
  return (
    <article className="chat-msg__tool-card chat-msg__tool-card--preparing">
      <div className="chat-msg__tool-head chat-msg__tool-head--static">
        <span className="chat-msg__tool-caret" aria-hidden="true">
          <CaretRight size={14} weight="bold" />
        </span>
        <span className="chat-msg__tool-name">正在准备工具调用</span>
        <span className="chat-msg__tool-meta">
          {elapsedSeconds !== null ? (
            <span className="chat-msg__tool-timer">
              {formatElapsedSeconds(elapsedSeconds)}
            </span>
          ) : null}
          <span className="chat-msg__tool-status chat-msg__tool-status--running">准备中</span>
        </span>
      </div>
    </article>
  );
}

function ToolProcessCard({
  clockTick,
  item,
}: {
  clockTick: number;
  item: ChatToolProcessItem;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [submittingDecision, setSubmittingDecision] = useState<"allow" | "deny" | null>(null);
  const result = item.error || item.result;
  const elapsedSeconds = resolveToolProcessElapsedSeconds(item, clockTick);
  const permissionRequest = item.permissionRequest ?? null;

  const decidePermission = async (decision: "allow" | "deny") => {
    if (!permissionRequest || submittingDecision) return;
    setSubmittingDecision(decision);
    try {
      const response = await submitToolPermissionDecision(
        permissionRequest.request_id,
        decision,
      );
      if (!response.accepted) setSubmittingDecision(null);
    } catch {
      setSubmittingDecision(null);
    }
  };

  return (
    <article className="chat-msg__tool-card">
      <div className="chat-msg__tool-head chat-msg__tool-head--button">
        <button
          className="chat-msg__tool-head-main"
          type="button"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded((value) => !value)}
        >
          <span className="chat-msg__tool-caret" aria-hidden="true">
            {isExpanded ? (
              <CaretDown size={14} weight="bold" />
            ) : (
              <CaretRight size={14} weight="bold" />
            )}
          </span>
          <span className="chat-msg__tool-name">{item.name || "tool"}</span>
        </button>
        <span className="chat-msg__tool-meta">
          {permissionRequest ? (
            <span className="chat-msg__tool-permission-actions">
              <button
                className="chat-msg__tool-permission-action chat-msg__tool-permission-action--allow"
                type="button"
                title="允许本次调用"
                aria-label="允许本次调用"
                disabled={submittingDecision !== null}
                onClick={() => void decidePermission("allow")}
              >
                <Check size={15} weight="bold" />
              </button>
              <button
                className="chat-msg__tool-permission-action chat-msg__tool-permission-action--deny"
                type="button"
                title="拒绝本次调用"
                aria-label="拒绝本次调用"
                disabled={submittingDecision !== null}
                onClick={() => void decidePermission("deny")}
              >
                <X size={15} weight="bold" />
              </button>
            </span>
          ) : null}
          {item.status !== "waiting_permission" ? (
            <span
              className={[
                "chat-msg__tool-status",
                item.status === "error" ? "chat-msg__tool-status--error" : "",
                item.status === "running" || item.status === "preparing"
                  ? "chat-msg__tool-status--running"
                  : "",
              ].filter(Boolean).join(" ")}
            >
              {item.status === "preparing"
                ? "准备中"
                : item.status === "running"
                  ? "调用中"
                  : item.status === "error"
                    ? "失败"
                    : item.status === "cancelled"
                      ? "已取消"
                      : "完成"}
            </span>
          ) : null}
          {elapsedSeconds !== null ? (
            <span className="chat-msg__tool-timer">
              {formatElapsedSeconds(elapsedSeconds)}
            </span>
          ) : null}
          {item.status === "waiting_permission" ? (
            <span
              className="chat-msg__tool-waiting-dot"
              aria-label="等待确认"
              title="等待确认"
            />
          ) : null}
        </span>
      </div>
      {isExpanded ? (
        <>
          {item.arguments ? (
            <ToolProcessPayload label="参数" value={item.arguments} />
          ) : null}
          {result ? (
            <ToolProcessPayload
              label={item.error ? "错误" : "结果"}
              tone={item.error ? "error" : "normal"}
              value={result}
            />
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function ToolProcessPayload({
  label,
  tone = "normal",
  value,
}: {
  label: string;
  tone?: "normal" | "error";
  value: string;
}) {
  const formattedValue = useMemo(() => formatToolPayload(value), [value]);

  return (
    <div className="chat-msg__tool-payload">
      <div className="chat-msg__tool-payload-label">{label}</div>
      <pre
        className={[
          "chat-msg__tool-pre",
          tone === "error" ? "chat-msg__tool-pre--error" : "",
        ].filter(Boolean).join(" ")}
      >
        {formattedValue}
      </pre>
    </div>
  );
}

export function formatToolPayload(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return trimmed;
  }
}

function resolveToolPreparingElapsedSeconds(
  item: Extract<ChatAssistantProcessItem, { type: "tool_preparing" }>,
  clockTick: number,
) {
  if (!clockTick) return null;
  return Math.max(0, Math.floor((clockTick - item.startedAt) / 1000));
}

function resolveToolProcessElapsedSeconds(
  item: ChatToolProcessItem,
  clockTick: number,
) {
  if (item.startedAt === null) return null;
  const end = item.finishedAt ?? clockTick;
  if (!end) return null;
  return Math.max(0, Math.floor((end - item.startedAt) / 1000));
}

export function resolveToolGroupElapsedSeconds(
  entries: ToolProcessEntry[],
  clockTick: number,
) {
  const starts: number[] = [];
  const ends: number[] = [];
  let hasActiveEntry = false;

  entries.forEach((entry) => {
    if (entry.type === "tool_preparing") {
      starts.push(entry.startedAt);
      hasActiveEntry = true;
      return;
    }
    if (entry.tool.startedAt !== null) {
      starts.push(entry.tool.startedAt);
    }
    if (
      entry.tool.status === "preparing" ||
      entry.tool.status === "running" ||
      entry.tool.finishedAt === null
    ) {
      hasActiveEntry = true;
      return;
    }
    ends.push(entry.tool.finishedAt);
  });

  if (starts.length === 0) return null;
  const start = Math.min(...starts);
  const end = hasActiveEntry
    ? clockTick
    : ends.length > 0
      ? Math.max(...ends)
      : start;
  if (!end) return null;
  return Math.max(0, Math.floor((end - start) / 1000));
}

export function formatElapsedSeconds(seconds: number) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const totalMinutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  const secondsText = String(remainingSeconds).padStart(2, "0");
  if (totalMinutes < 60) {
    return `${totalMinutes}m ${secondsText}s`;
  }
  const hours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes % 60;
  return `${hours}h ${String(remainingMinutes).padStart(2, "0")}m ${secondsText}s`;
}

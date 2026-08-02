import { CaretDown, CaretRight, DownloadSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { Handle, NodeToolbar, Position, type NodeProps } from "@xyflow/react";

import type { ConversationBranchFlowNode } from "../model/conversationBranchLayout";

export function ConversationBranchTurnCard({ data }: NodeProps<ConversationBranchFlowNode>) {
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const isActivePath = Boolean(
    data.activeSessionId && data.turn.targets.some(
      (target) => target.session_id === data.activeSessionId,
    ),
  );
  const replyPreview = data.turn.assistant_preview || replyStatusLabel(data.turn.reply_status);
  const cardClassName = [
    "conversation-branch-card",
    isActivePath ? "conversation-branch-card--active-path" : "",
    data.isSelected ? "conversation-branch-card--selected" : "",
  ].filter(Boolean).join(" ");
  return (
    <div className={cardClassName}>
      <Handle className="conversation-branch-card__handle" type="target" position={Position.Left} />
      <button
        className="conversation-branch-card__main"
        type="button"
        title={data.turn.user_preview}
        onClick={() => data.onSelect(data.turn)}
      >
        <strong>{data.turn.user_preview || "空消息"}</strong>
        <small>{replyPreview}</small>
      </button>
      <footer className="conversation-branch-card__footer">
        <span>版本 {data.turn.variant_index}</span>
        <span>{data.insight.depth} 级</span>
        <span>后续 {data.insight.downstreamBranchPoints.length}</span>
        <button
          className="conversation-branch-card__export"
          type="button"
          aria-label="导出此回复"
          title="导出此回复"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            data.onExport(data.turn);
          }}
        >
          <DownloadSimple size={12} weight="regular" aria-hidden="true" />
        </button>
        {data.insight.downstreamBranchPoints.length > 0 ? (
          <button
            className="conversation-branch-card__details-toggle"
            type="button"
            aria-expanded={isDetailsOpen}
            aria-label={isDetailsOpen ? "收起后续分支" : "展开后续分支"}
            title={isDetailsOpen ? "收起后续分支" : "展开后续分支"}
            onClick={() => setIsDetailsOpen((current) => !current)}
          >
            {isDetailsOpen
              ? <CaretDown size={12} weight="bold" aria-hidden="true" />
              : <CaretRight size={12} weight="bold" aria-hidden="true" />}
          </button>
        ) : null}
      </footer>
      <NodeToolbar
        align="center"
        isVisible={isDetailsOpen}
        offset={8}
        position={Position.Bottom}
      >
        <div className="conversation-branch-card__details" role="menu" aria-label="后续分支">
          {data.insight.downstreamBranchPoints.map((point, index) => (
            <button
              className="conversation-branch-card__details-item"
              type="button"
              role="menuitem"
              title={point.preview}
              onClick={() => data.onFocusBranchPoint(point)}
              key={point.id}
            >
              <span>{index + 1}. {point.preview}</span>
              <small>{point.variantCount} 个版本</small>
            </button>
          ))}
        </div>
      </NodeToolbar>
      <Handle className="conversation-branch-card__handle" type="source" position={Position.Right} />
    </div>
  );
}

function replyStatusLabel(status: "done" | "running" | "missing" | "error") {
  if (status === "running") return "AI 正在回复";
  if (status === "error") return "本轮回复失败";
  if (status === "missing") return "本轮尚无最终回复";
  return "本轮回复为空";
}

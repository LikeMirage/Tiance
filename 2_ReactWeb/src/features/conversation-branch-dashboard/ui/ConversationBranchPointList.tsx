import { GitBranch } from "@phosphor-icons/react";
import { useState } from "react";

import type { ConversationBranchPoint } from "../model/conversationBranchLayout";

type ConversationBranchPointListProps = {
  activePointId: string | null;
  onSelect: (point: ConversationBranchPoint) => void;
  points: ConversationBranchPoint[];
};

export function ConversationBranchPointList({
  activePointId,
  onSelect,
  points,
}: ConversationBranchPointListProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (points.length === 0) return null;

  return (
    <div
      className={isOpen
        ? "conversation-branch-point-picker conversation-branch-point-picker--open"
        : "conversation-branch-point-picker"}
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => setIsOpen(false)}
      onFocusCapture={() => setIsOpen(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
      }}
    >
      <button
        className="conversation-branch-point-picker__trigger"
        type="button"
        aria-expanded={isOpen}
        aria-haspopup="menu"
      >
        <GitBranch size={14} weight="regular" aria-hidden="true" />
        <span>分叉点</span>
        <small>{activePointId
          ? `${points.findIndex((point) => point.id === activePointId) + 1}/${points.length}`
          : points.length}</small>
      </button>
      {isOpen ? (
        <div className="conversation-branch-point-picker__menu" role="menu">
          {points.map((point, index) => (
            <button
              className={point.id === activePointId
                ? "conversation-branch-point-picker__item conversation-branch-point-picker__item--active"
                : "conversation-branch-point-picker__item"}
              type="button"
              role="menuitem"
              title={point.preview}
              onClick={() => onSelect(point)}
              key={point.id}
            >
              <span>{index + 1}. {point.preview}</span>
              <small>{point.variantCount} 个版本</small>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

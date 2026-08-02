import { type ReactNode, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import "./tooltip.css";

type TooltipPlacement = "top" | "bottom";

export type TooltipProps = {
  children: ReactNode;
  content: ReactNode;
  disabled?: boolean;
  maxWidth?: number;
  placement?: TooltipPlacement;
};

type TooltipPosition = {
  left: number;
  top: number;
  placement: TooltipPlacement;
};

const VIEWPORT_MARGIN = 12;
const GAP = 8;
const DEFAULT_MAX_WIDTH = 280;

export function Tooltip({
  children,
  content,
  disabled = false,
  maxWidth = DEFAULT_MAX_WIDTH,
  placement = "top",
}: TooltipProps) {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const normalizedContent = useMemo(() => {
    if (typeof content !== "string") {
      return content;
    }
    return content.trim();
  }, [content]);
  const isDisabled = disabled || !normalizedContent;

  const show = () => {
    if (isDisabled) {
      return;
    }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    setPosition(positionTooltip(rect, placement, maxWidth));
  };

  const hide = () => {
    setPosition(null);
  };

  return (
    <span
      ref={triggerRef}
      className="ds-tooltip__trigger"
      aria-describedby={position ? tooltipId : undefined}
      onBlur={hide}
      onFocus={show}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      {children}
      {position
        ? createPortal(
            <span
              id={tooltipId}
              className="ds-tooltip"
              data-placement={position.placement}
              role="tooltip"
              style={{
                left: position.left,
                maxWidth,
                top: position.top,
              }}
            >
              {normalizedContent}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}

function positionTooltip(
  rect: DOMRect,
  preferredPlacement: TooltipPlacement,
  maxWidth: number,
): TooltipPosition {
  const halfWidth = maxWidth / 2;
  const left = clamp(
    rect.left + rect.width / 2,
    VIEWPORT_MARGIN + halfWidth,
    window.innerWidth - VIEWPORT_MARGIN - halfWidth,
  );
  const hasTopSpace = rect.top >= 72;
  const actualPlacement = preferredPlacement === "top" && hasTopSpace ? "top" : "bottom";
  return {
    left,
    placement: actualPlacement,
    top: actualPlacement === "top" ? rect.top - GAP : rect.bottom + GAP,
  };
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) {
    return value;
  }
  return Math.min(Math.max(value, min), max);
}

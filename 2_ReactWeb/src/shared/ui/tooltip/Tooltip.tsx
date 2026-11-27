import { type ReactNode, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import "./tooltip.css";

type TooltipPlacement = "top" | "bottom";

export type TooltipProps = {
  children: ReactNode;
  content: ReactNode;
  disabled?: boolean;
  focusable?: boolean;
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
  focusable = false,
  maxWidth = DEFAULT_MAX_WIDTH,
  placement = "top",
}: TooltipProps) {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
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
    // Hover and focus can open the same tooltip. Keep its measured position until it closes.
    setPosition(current => current ?? positionTooltip(rect, placement, maxWidth));
  };

  const hide = () => {
    setPosition(null);
  };

  const visible = position !== null;
  useLayoutEffect(() => {
    const anchor = triggerRef.current;
    const tooltip = tooltipRef.current;
    if (!visible || !anchor || !tooltip) return;
    const rect = anchor.getBoundingClientRect();
    const bounds = tooltip.getBoundingClientRect();
    const measured = positionTooltip(rect, placement, bounds.width, bounds.height);
    setPosition(current => current?.placement === measured.placement && current.left === measured.left
      && current.top === measured.top ? current : measured);
  }, [visible, placement, maxWidth]);

  return (
    <span
      ref={triggerRef}
      className="ds-tooltip__trigger"
      tabIndex={focusable ? 0 : undefined}
      onKeyDown={focusable ? (event) => { if (event.key === "Escape") hide(); } : undefined}
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
              ref={tooltipRef}
              id={tooltipId}
              className="ds-tooltip"
              data-placement={position.placement}
              role="tooltip"
              style={{
                left: position.left,
                maxWidth: `min(${maxWidth}px, calc(100vw - ${VIEWPORT_MARGIN * 2}px))`,
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
  width: number,
  height = 52,
): TooltipPosition {
  const halfWidth = width / 2;
  const left = clamp(
    rect.left + rect.width / 2,
    VIEWPORT_MARGIN + halfWidth,
    window.innerWidth - VIEWPORT_MARGIN - halfWidth,
  );
  const required = height + GAP + VIEWPORT_MARGIN;
  const above = rect.top, below = window.innerHeight - rect.bottom;
  const onTop = preferredPlacement === "top" ? above >= required || above > below : below < required && above > below;
  const actualPlacement = onTop ? "top" : "bottom";
  return {
    left,
    placement: actualPlacement,
    top: onTop
      ? Math.max(height + VIEWPORT_MARGIN, rect.top - GAP)
      : Math.max(VIEWPORT_MARGIN, Math.min(rect.bottom + GAP, window.innerHeight - height - VIEWPORT_MARGIN)),
  };
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) {
    return value;
  }
  return Math.min(Math.max(value, min), max);
}

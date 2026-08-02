import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";

import type { UserMessageNavigationItem } from "../model/userMessageNavigation";
import {
  getMessageNavigatorHoverTickWidth,
  resolveNearestMessageNavigatorIndex,
} from "../model/messageNavigatorInteraction";

type UserMessageNavigatorProps = {
  activeTurnNumber: number | null;
  items: UserMessageNavigationItem[];
  onSelect: (item: UserMessageNavigationItem) => void;
};

type NavigatorMarkStyle = CSSProperties & {
  "--message-nav-hover-width"?: string;
};

type NavigatorMarksStyle = CSSProperties & {
  "--message-nav-count": number;
};

export function UserMessageNavigator({
  activeTurnNumber,
  items,
  onSelect,
}: UserMessageNavigatorProps) {
  const navigatorRef = useRef<HTMLElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const marksRef = useRef<HTMLDivElement>(null);
  const pointerClientYRef = useRef<number | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [previewPosition, setPreviewPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);

  useEffect(() => {
    if (!isExpanded) return undefined;
    const collapseOutsideNavigator = (event: globalThis.PointerEvent) => {
      const navigator = navigatorRef.current;
      if (!navigator) return;
      const bounds = navigator.getBoundingClientRect();
      const isInside = event.clientX >= bounds.left && event.clientX <= bounds.right &&
        event.clientY >= bounds.top && event.clientY <= bounds.bottom;
      if (!isInside) {
        pointerClientYRef.current = null;
        setHoveredIndex(null);
        setIsExpanded(false);
      }
    };
    window.addEventListener("pointermove", collapseOutsideNavigator);
    return () => window.removeEventListener("pointermove", collapseOutsideNavigator);
  }, [isExpanded]);

  useLayoutEffect(() => {
    if (hoveredIndex === null) {
      setPreviewPosition(null);
      return undefined;
    }

    const updatePreviewPosition = () => {
      const navigator = navigatorRef.current;
      const mark = marksRef.current?.children.item(hoveredIndex);
      if (!(mark instanceof HTMLElement) || !navigator) return;

      const navigatorBounds = navigator.getBoundingClientRect();
      const markBounds = mark.getBoundingClientRect();
      const previewWidth = Math.min(270, Math.max(0, window.innerWidth - 72));
      const preferredLeft = navigatorBounds.left - previewWidth - 6;
      setPreviewPosition({
        left: Math.max(8, Math.min(preferredLeft, window.innerWidth - previewWidth - 8)),
        top: Math.max(
          42,
          Math.min(markBounds.top + markBounds.height / 2, window.innerHeight - 42),
        ),
      });
    };

    updatePreviewPosition();
    const frame = window.requestAnimationFrame(updatePreviewPosition);
    window.addEventListener("resize", updatePreviewPosition);
    window.addEventListener("scroll", updatePreviewPosition, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePreviewPosition);
      window.removeEventListener("scroll", updatePreviewPosition, true);
    };
  }, [hoveredIndex, items.length]);

  useLayoutEffect(() => {
    const activeIndex = items.findIndex((item) => item.turnNumber === activeTurnNumber);
    const track = trackRef.current;
    const mark = activeIndex < 0 ? null : marksRef.current?.children.item(activeIndex);
    if (!track || !(mark instanceof HTMLElement)) return;

    const markTop = mark.offsetTop;
    const markBottom = markTop + mark.offsetHeight;
    if (markTop < track.scrollTop) {
      track.scrollTop = markTop;
    } else if (markBottom > track.scrollTop + track.clientHeight) {
      track.scrollTop = markBottom - track.clientHeight;
    }
  }, [activeTurnNumber, items]);

  if (items.length < 2) return null;

  const hoveredItem = hoveredIndex === null ? null : items[hoveredIndex] ?? null;

  const updateHoveredIndex = (index: number) => {
    setHoveredIndex(index);
  };

  const resolveNearestIndex = (clientY: number) => {
    const marks = marksRef.current;
    if (!marks) return null;
    const firstMark = marks.children.item(0);
    const lastMark = marks.children.item(items.length - 1);
    if (!(firstMark instanceof HTMLElement) || !(lastMark instanceof HTMLElement)) {
      return null;
    }
    const firstBounds = firstMark.getBoundingClientRect();
    const lastBounds = lastMark.getBoundingClientRect();
    return resolveNearestMessageNavigatorIndex(
      items.length,
      clientY,
      firstBounds.top,
      lastBounds.bottom - firstBounds.top,
    );
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    pointerClientYRef.current = event.clientY;
    setIsExpanded(true);
    const nearestIndex = resolveNearestIndex(event.clientY);
    if (nearestIndex !== null && nearestIndex !== hoveredIndex) {
      updateHoveredIndex(nearestIndex);
    }
  };

  const handleTrackScroll = () => {
    const pointerClientY = pointerClientYRef.current;
    if (pointerClientY === null) return;
    const nearestIndex = resolveNearestIndex(pointerClientY);
    if (nearestIndex !== null && nearestIndex !== hoveredIndex) {
      updateHoveredIndex(nearestIndex);
    }
  };

  const handleNavigatorClick = (event: ReactMouseEvent<HTMLElement>) => {
    if ((event.target as Element).closest("button")) return;
    const nearestIndex = resolveNearestIndex(event.clientY);
    if (nearestIndex === null) return;
    updateHoveredIndex(nearestIndex);
    onSelect(items[nearestIndex]);
  };

  return (
    <nav
      className={[
        "ai-panel__message-navigator",
        isExpanded ? "ai-panel__message-navigator--expanded" : "",
        hoveredIndex !== null ? "ai-panel__message-navigator--hovering" : "",
      ].filter(Boolean).join(" ")}
      ref={navigatorRef}
      aria-label="用户消息导航"
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          pointerClientYRef.current = null;
          setHoveredIndex(null);
          setIsExpanded(false);
        }
      }}
      onFocusCapture={() => setIsExpanded(true)}
      onPointerEnter={(event) => {
        pointerClientYRef.current = event.clientY;
        setIsExpanded(true);
      }}
      onPointerMove={handlePointerMove}
      onClick={handleNavigatorClick}
    >
      <div
        className="ai-panel__message-navigator-track"
        ref={trackRef}
        onScroll={handleTrackScroll}
      >
        <div
          className="ai-panel__message-navigator-marks"
          ref={marksRef}
          style={{ "--message-nav-count": items.length } as NavigatorMarksStyle}
        >
          {items.map((item, index) => {
            const isActive = item.turnNumber === activeTurnNumber;
            const hoverWidth = getMessageNavigatorHoverTickWidth(
              hoveredIndex === null ? null : Math.abs(index - hoveredIndex),
            );
            const classes = [
              "ai-panel__message-navigator-mark",
              isActive ? "ai-panel__message-navigator-mark--active" : "",
              hoveredIndex === index ? "ai-panel__message-navigator-mark--hovered" : "",
              hoverWidth !== null ? "ai-panel__message-navigator-mark--near-hover" : "",
            ].filter(Boolean).join(" ");
            return (
              <button
                className={classes}
                style={hoverWidth === null
                  ? undefined
                  : { "--message-nav-hover-width": `${hoverWidth}px` } as NavigatorMarkStyle}
                type="button"
                aria-current={isActive ? "location" : undefined}
                aria-label={`第 ${item.turnNumber} 个用户回合：${item.userPreview}`}
                onClick={() => {
                  updateHoveredIndex(index);
                  onSelect(item);
                }}
                onFocus={() => updateHoveredIndex(index)}
                key={item.userMessageId}
              >
                <span className="ai-panel__message-navigator-tick" aria-hidden="true" />
              </button>
            );
          })}
        </div>
      </div>
      {hoveredItem && previewPosition && typeof document !== "undefined"
        ? createPortal(
            <span
              className="ai-panel__message-navigator-preview"
              style={{
                left: `${previewPosition.left}px`,
                top: `${previewPosition.top}px`,
              }}
            >
              <strong>{hoveredItem.userPreview}</strong>
              <small>{hoveredItem.assistantPreview}</small>
            </span>,
            document.body,
          )
        : null}
    </nav>
  );
}

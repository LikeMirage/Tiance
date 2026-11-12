import { useEffect, useRef, type RefObject } from "react";

import { useOverlayScrollbar } from "../../model/overlay-scrollbar/useOverlayScrollbar";
import "./edge-scrollbar.css";

type EdgeScrollbarProps = {
  scrollRef: RefObject<HTMLDivElement | null>;
  scrollId: string;
  label: string;
  refreshKey: string;
  side?: "left" | "right";
  enabled?: boolean;
  /** Called before a user changes scroll position; never for layout changes. */
  onUserScroll?: () => void;
};

/** Overlay on a positioned parent; the caller keeps its existing scroll viewport. */
export function EdgeScrollbar({
  scrollRef, scrollId, label, refreshKey, side = "right", enabled = true, onUserScroll,
}: EdgeScrollbarProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const scrollbar = useOverlayScrollbar(`${enabled}:${refreshKey}`, scrollRef);
  const { handleScroll } = scrollbar;
  const trackRange = Math.max(0, (scrollRef.current?.clientHeight ?? 0) - scrollbar.thumbHeight);
  const position = trackRange ? Math.round(scrollbar.thumbTop / trackRange * 100) : 0;

  useEffect(() => {
    if (!enabled) return;
    const viewport = scrollRef.current;
    if (!viewport) return;
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, [enabled, handleScroll, refreshKey, scrollRef]);

  useEffect(() => {
    const track = trackRef.current;
    if (!enabled || !scrollbar.isVisible || !track) return;
    const onWheel = (event: WheelEvent) => {
      const viewport = scrollRef.current;
      if (!viewport || event.ctrlKey || event.deltaY === 0) return;
      event.preventDefault();
      event.stopPropagation();
      onUserScroll?.();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
      viewport.scrollTop += event.deltaY * unit;
      handleScroll();
    };
    track.addEventListener("wheel", onWheel, { passive: false });
    return () => track.removeEventListener("wheel", onWheel);
  }, [enabled, handleScroll, onUserScroll, scrollbar.isVisible, scrollRef]);

  if (!enabled) return null;

  return (
    <div
      ref={trackRef}
      className={`edge-scrollbar edge-scrollbar--${side}${scrollbar.isVisible ? " edge-scrollbar--scrollable" : ""}`}
      role={scrollbar.isVisible ? "scrollbar" : undefined}
      tabIndex={scrollbar.isVisible ? 0 : undefined}
      aria-hidden={!scrollbar.isVisible || undefined}
      aria-label={label}
      aria-controls={scrollId}
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={position}
      onPointerDown={(event) => {
        if (event.button !== 0 || event.target !== event.currentTarget) return;
        event.preventDefault();
        event.stopPropagation();
        onUserScroll?.();
        scrollbar.handleTrackPointerDown(event);
      }}
      onKeyDown={(event) => {
        const viewport = scrollRef.current;
        if (!viewport) return;
        const offsets: Record<string, number> = {
          ArrowUp: -32, ArrowDown: 32,
          PageUp: -viewport.clientHeight, PageDown: viewport.clientHeight,
          Home: -viewport.scrollHeight, End: viewport.scrollHeight,
        };
        const offset = offsets[event.key];
        if (offset === undefined) return;
        event.preventDefault();
        event.stopPropagation();
        onUserScroll?.();
        viewport.scrollTop += offset;
        handleScroll();
      }}
    >
      {scrollbar.isVisible ? <div
        className="edge-scrollbar__thumb"
        style={{ height: scrollbar.thumbHeight, transform: `translateY(${scrollbar.thumbTop}px)` }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          onUserScroll?.();
          scrollbar.handleThumbPointerDown(event);
        }}
        onPointerMove={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) onUserScroll?.();
          scrollbar.handleThumbPointerMove(event);
        }}
        onPointerUp={scrollbar.handleThumbPointerUp}
        onPointerCancel={scrollbar.handleThumbPointerCancel}
        onLostPointerCapture={scrollbar.handleThumbPointerCancel}
      /> : null}
    </div>
  );
}

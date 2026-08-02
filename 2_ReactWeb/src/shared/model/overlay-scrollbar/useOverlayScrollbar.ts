import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";

const MIN_THUMB_HEIGHT = 24;

type OverlayScrollbarState = {
  isActive: boolean;
  isVisible: boolean;
  thumbHeight: number;
  thumbTop: number;
};

const HIDDEN_SCROLLBAR_STATE: OverlayScrollbarState = {
  isActive: false,
  isVisible: false,
  thumbHeight: 0,
  thumbTop: 0,
};

export function useOverlayScrollbar(refreshKey: string) {
  const hideTimerRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    startScrollTop: number;
    startY: number;
  } | null>(null);
  const [state, setState] = useState<OverlayScrollbarState>(HIDDEN_SCROLLBAR_STATE);

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current === null) {
      return;
    }

    window.clearTimeout(hideTimerRef.current);
    hideTimerRef.current = null;
  }, []);

  const scheduleHide = useCallback(() => {
    clearHideTimer();
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null;
      setState((current) =>
        current.isActive ? { ...current, isActive: false } : current,
      );
    }, 1000);
  }, [clearHideTimer]);

  const refresh = useCallback((options?: { activate?: boolean }) => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) {
      clearHideTimer();
      setState(HIDDEN_SCROLLBAR_STATE);
      return;
    }

    const { clientHeight, scrollHeight, scrollTop } = scrollElement;
    if (scrollHeight <= clientHeight + 1) {
      clearHideTimer();
      setState(HIDDEN_SCROLLBAR_STATE);
      return;
    }

    const thumbHeight = Math.max(
      MIN_THUMB_HEIGHT,
      Math.round((clientHeight / scrollHeight) * clientHeight),
    );
    const maxThumbTop = Math.max(0, clientHeight - thumbHeight);
    const maxScrollTop = Math.max(1, scrollHeight - clientHeight);
    const thumbTop = Math.round((scrollTop / maxScrollTop) * maxThumbTop);

    setState((current) => {
      const nextState = {
        isActive: options?.activate ? true : current.isActive,
        isVisible: true,
        thumbHeight,
        thumbTop,
      };

      return current.isActive === nextState.isActive &&
        current.isVisible === nextState.isVisible &&
        current.thumbHeight === nextState.thumbHeight &&
        current.thumbTop === nextState.thumbTop
        ? current
        : nextState;
    });
  }, [clearHideTimer]);

  useLayoutEffect(() => {
    refresh();

    const scrollElement = scrollRef.current;
    if (!scrollElement || typeof ResizeObserver === "undefined") {
      return;
    }

    const resizeObserver = new ResizeObserver(() => refresh());
    resizeObserver.observe(scrollElement);
    if (scrollElement.firstElementChild) {
      resizeObserver.observe(scrollElement.firstElementChild);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [refresh, refreshKey]);

  useEffect(() => {
    const handleWindowResize = () => refresh();

    window.addEventListener("resize", handleWindowResize);
    return () => {
      window.removeEventListener("resize", handleWindowResize);
      clearHideTimer();
    };
  }, [clearHideTimer, refresh]);

  const scrollToThumbTop = useCallback(
    (nextThumbTop: number) => {
      const scrollElement = scrollRef.current;
      if (!scrollElement) {
        return;
      }

      const maxThumbTop = Math.max(1, scrollElement.clientHeight - state.thumbHeight);
      const maxScrollTop = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
      const clampedThumbTop = clamp(nextThumbTop, 0, maxThumbTop);
      scrollElement.scrollTop = (clampedThumbTop / maxThumbTop) * maxScrollTop;
      refresh({ activate: true });
      scheduleHide();
    },
    [refresh, scheduleHide, state.thumbHeight],
  );

  const handleScroll = useCallback(() => {
    refresh({ activate: true });
    scheduleHide();
  }, [refresh, scheduleHide]);

  const handleTrackPointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget) {
        return;
      }

      const trackRect = event.currentTarget.getBoundingClientRect();
      scrollToThumbTop(event.clientY - trackRect.top - state.thumbHeight / 2);
    },
    [scrollToThumbTop, state.thumbHeight],
  );

  const handleThumbPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    clearHideTimer();
    refresh({ activate: true });
    dragStateRef.current = {
      pointerId: event.pointerId,
      startScrollTop: scrollElement.scrollTop,
      startY: event.clientY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [clearHideTimer, refresh]);

  const handleThumbPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const scrollElement = scrollRef.current;
      const dragState = dragStateRef.current;
      if (!scrollElement || !dragState || dragState.pointerId !== event.pointerId) {
        return;
      }

      const maxThumbTop = Math.max(1, scrollElement.clientHeight - state.thumbHeight);
      const maxScrollTop = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
      const scrollDelta = ((event.clientY - dragState.startY) / maxThumbTop) * maxScrollTop;
      scrollElement.scrollTop = clamp(
        dragState.startScrollTop + scrollDelta,
        0,
        maxScrollTop,
      );
      refresh({ activate: true });
    },
    [refresh, state.thumbHeight],
  );

  const handleThumbPointerEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current?.pointerId !== event.pointerId) {
      return;
    }

    dragStateRef.current = null;
    scheduleHide();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, [scheduleHide]);

  return {
    handleScroll,
    handleThumbPointerCancel: handleThumbPointerEnd,
    handleThumbPointerDown,
    handleThumbPointerMove,
    handleThumbPointerUp: handleThumbPointerEnd,
    handleTrackPointerDown,
    isActive: state.isActive,
    isVisible: state.isVisible,
    scrollRef,
    thumbHeight: state.thumbHeight,
    thumbTop: state.thumbTop,
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import {
  WORKSPACE_LAYOUT_DEFAULTS,
  WORKSPACE_LAYOUT_LIMITS,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

type UseComposerResizeOptions = {
  initialHeight?: number;
  minHeight?: number;
  maxHeight?: number;
  onHeightCommit?: (height: number) => void;
};

type ActiveResize = {
  handleMove: (event: PointerEvent) => void;
  handleStop: () => void;
  previousCursor: string;
  previousUserSelect: string;
};

export function useComposerResize({
  initialHeight = WORKSPACE_LAYOUT_DEFAULTS.composerHeight,
  minHeight = WORKSPACE_LAYOUT_LIMITS.composerHeight.min,
  maxHeight = WORKSPACE_LAYOUT_LIMITS.composerHeight.max,
  onHeightCommit,
}: UseComposerResizeOptions = {}) {
  const [composerHeight, setComposerHeight] = useState(() =>
    clampComposerHeight(initialHeight, minHeight, maxHeight),
  );
  const [isResizing, setIsResizing] = useState(false);
  const resizeStartRef = useRef({ startY: 0, startHeight: initialHeight });
  const activeResizeRef = useRef<ActiveResize | null>(null);
  const heightRef = useRef(composerHeight);
  const onHeightCommitRef = useRef(onHeightCommit);

  useEffect(() => {
    onHeightCommitRef.current = onHeightCommit;
  }, [onHeightCommit]);

  const stopResize = useCallback(() => {
    const activeResize = activeResizeRef.current;
    if (!activeResize) {
      return;
    }

    window.removeEventListener("pointermove", activeResize.handleMove);
    window.removeEventListener("pointerup", activeResize.handleStop);
    window.removeEventListener("pointercancel", activeResize.handleStop);
    window.removeEventListener("blur", activeResize.handleStop);
    document.body.style.cursor = activeResize.previousCursor;
    document.body.style.userSelect = activeResize.previousUserSelect;
    activeResizeRef.current = null;
    setIsResizing(false);
    onHeightCommitRef.current?.(heightRef.current);
  }, []);

  const handleResizeStart = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    event.preventDefault();
    stopResize();

    resizeStartRef.current = {
      startY: event.clientY,
      startHeight: composerHeight,
    };

    const handleMove = (moveEvent: PointerEvent) => {
      const nextHeight = resizeStartRef.current.startHeight
        + (resizeStartRef.current.startY - moveEvent.clientY);
      const clampedHeight = clampComposerHeight(nextHeight, minHeight, maxHeight);
      heightRef.current = clampedHeight;
      setComposerHeight(clampedHeight);
    };
    const handleStop = () => stopResize();

    activeResizeRef.current = {
      handleMove,
      handleStop,
      previousCursor: document.body.style.cursor,
      previousUserSelect: document.body.style.userSelect,
    };

    setIsResizing(true);
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleStop);
    window.addEventListener("pointercancel", handleStop);
    window.addEventListener("blur", handleStop);
  }, [composerHeight, maxHeight, minHeight, stopResize]);

  useEffect(() => stopResize, [stopResize]);

  return {
    composerHeight,
    handleResizeStart,
    isResizing,
  };
}

function clampComposerHeight(height: number, minHeight: number, maxHeight: number): number {
  const safeHeight = Number.isFinite(height)
    ? height
    : WORKSPACE_LAYOUT_DEFAULTS.composerHeight;
  return Math.min(Math.max(Math.round(safeHeight), minHeight), maxHeight);
}

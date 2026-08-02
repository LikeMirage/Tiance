import { useCallback, useEffect, useRef, useState } from "react";

import {
  WORKSPACE_LAYOUT_DEFAULTS,
  WORKSPACE_LAYOUT_LIMITS,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

const MAX_WIDTH_RATIO = 0.45;
const RESIZING_BODY_CLASS = "workspace-ai-panel-resizing";

type UseAiPanelLayoutOptions = {
  initialWidth?: number;
  onWidthCommit?: (width: number) => void;
};

const DEFAULT_WIDTH = WORKSPACE_LAYOUT_DEFAULTS.aiPanelWidth;
const MIN_WIDTH = WORKSPACE_LAYOUT_LIMITS.aiPanelWidth.min;

export function useAiPanelLayout({
  initialWidth = DEFAULT_WIDTH,
  onWidthCommit,
}: UseAiPanelLayoutOptions = {}) {
  const [width, setWidth] = useState(() => clampAiPanelWidth(initialWidth, window.innerWidth));
  const [isResizing, setIsResizing] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_WIDTH);
  const widthRef = useRef(width);
  const onWidthCommitRef = useRef(onWidthCommit);

  useEffect(() => {
    onWidthCommitRef.current = onWidthCommit;
  }, [onWidthCommit]);

  const handleResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setIsResizing(true);
    document.body.classList.add(RESIZING_BODY_CLASS);
    startXRef.current = e.clientX;
    startWidthRef.current = width;
  }, [width]);

  useEffect(() => {
    if (!isResizing) return;

    const handleMove = (e: PointerEvent) => {
      const delta = startXRef.current - e.clientX;
      const next = clampAiPanelWidth(startWidthRef.current + delta, window.innerWidth);
      widthRef.current = next;
      setWidth(next);
    };

    const stopResize = () => {
      document.body.classList.remove(RESIZING_BODY_CLASS);
      setIsResizing(false);
      onWidthCommitRef.current?.(widthRef.current);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("blur", stopResize);
    if (isResizing) {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("blur", stopResize);
      document.body.classList.remove(RESIZING_BODY_CLASS);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizing]);

  const resetWidth = useCallback(() => {
    const nextWidth = clampAiPanelWidth(DEFAULT_WIDTH, window.innerWidth);
    widthRef.current = nextWidth;
    setWidth(nextWidth);
    onWidthCommitRef.current?.(nextWidth);
  }, []);

  return { isResizing, resetWidth, width, handleResizeStart };
}

function clampAiPanelWidth(width: number, viewportWidth: number): number {
  const safeWidth = Number.isFinite(width) ? width : DEFAULT_WIDTH;
  const viewportMaxWidth = Math.max(MIN_WIDTH, Math.floor(viewportWidth * MAX_WIDTH_RATIO));
  return Math.min(Math.max(Math.round(safeWidth), MIN_WIDTH), viewportMaxWidth);
}

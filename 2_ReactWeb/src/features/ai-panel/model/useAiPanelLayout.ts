import { useCallback, useEffect, useRef, useState } from "react";

import {
  WORKSPACE_LAYOUT_DEFAULTS,
  WORKSPACE_LAYOUT_LIMITS,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

const MAX_WIDTH_RATIO = 0.45;
const MIN_EDITOR_WIDTH = 280;
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
  const preferredWidthRef = useRef(initialWidth);
  const containerWidthRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const onWidthCommitRef = useRef(onWidthCommit);

  useEffect(() => {
    onWidthCommitRef.current = onWidthCommit;
  }, [onWidthCommit]);

  useEffect(() => {
    preferredWidthRef.current = initialWidth;
    const nextWidth = clampAiPanelWidth(initialWidth, window.innerWidth, containerWidthRef.current);
    widthRef.current = nextWidth;
    setWidth(nextWidth);
  }, [initialWidth]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateWidth = (containerWidth: number) => {
      if (containerWidth <= 0) return;
      containerWidthRef.current = containerWidth;
      const nextWidth = clampAiPanelWidth(preferredWidthRef.current, window.innerWidth, containerWidth);
      widthRef.current = nextWidth;
      setWidth(nextWidth);
    };
    const handleWindowResize = () => updateWidth(container.getBoundingClientRect().width);
    handleWindowResize();
    window.addEventListener("resize", handleWindowResize);
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(([entry]) => updateWidth(entry.contentRect.width));
    observer?.observe(container);

    return () => {
      window.removeEventListener("resize", handleWindowResize);
      observer?.disconnect();
    };
  }, []);

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
      const next = clampAiPanelWidth(startWidthRef.current + delta, window.innerWidth, containerWidthRef.current);
      preferredWidthRef.current = next;
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
    preferredWidthRef.current = DEFAULT_WIDTH;
    const nextWidth = clampAiPanelWidth(DEFAULT_WIDTH, window.innerWidth, containerWidthRef.current);
    widthRef.current = nextWidth;
    setWidth(nextWidth);
    onWidthCommitRef.current?.(nextWidth);
  }, []);

  return { containerRef, isResizing, resetWidth, width, handleResizeStart };
}

function clampAiPanelWidth(width: number, viewportWidth: number, containerWidth: number | null = null): number {
  const safeWidth = Number.isFinite(width) ? width : DEFAULT_WIDTH;
  const viewportMaxWidth = Math.max(MIN_WIDTH, Math.floor(viewportWidth * MAX_WIDTH_RATIO));
  const containerMaxWidth = containerWidth === null
    ? viewportMaxWidth
    : Math.max(MIN_WIDTH, Math.floor(containerWidth - MIN_EDITOR_WIDTH - 1));
  return Math.min(Math.max(Math.round(safeWidth), MIN_WIDTH), viewportMaxWidth, containerMaxWidth);
}

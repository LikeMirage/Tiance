import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import {
  WORKSPACE_LAYOUT_DEFAULTS,
  WORKSPACE_LAYOUT_LIMITS,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";

const RESIZING_BODY_CLASS = "workspace-side-panel-resizing";

type UseSidePanelLayoutOptions = {
  initialWidth?: number;
  onWidthCommit?: (width: number) => void;
};

const DEFAULT_SIDE_PANEL_WIDTH = WORKSPACE_LAYOUT_DEFAULTS.sidePanelWidth;
const MIN_SIDE_PANEL_WIDTH = WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.min;
const MAX_SIDE_PANEL_WIDTH = WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.max;

export function useSidePanelLayout({
  initialWidth = DEFAULT_SIDE_PANEL_WIDTH,
  onWidthCommit,
}: UseSidePanelLayoutOptions = {}) {
  const [sidePanelWidth, setSidePanelWidth] = useState(() =>
    clampSidePanelWidth(initialWidth, window.innerWidth),
  );
  const [isPanelResizing, setIsPanelResizing] = useState(false);
  const resizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const widthRef = useRef(sidePanelWidth);
  const onWidthCommitRef = useRef(onWidthCommit);

  useEffect(() => {
    onWidthCommitRef.current = onWidthCommit;
  }, [onWidthCommit]);

  useEffect(() => {
    const handleWindowResize = () => {
      setSidePanelWidth((currentWidth) => {
        const nextWidth = clampSidePanelWidth(currentWidth, window.innerWidth);
        widthRef.current = nextWidth;
        return nextWidth;
      });
    };

    window.addEventListener("resize", handleWindowResize);

    return () => {
      window.removeEventListener("resize", handleWindowResize);
      document.body.classList.remove(RESIZING_BODY_CLASS);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, []);

  useEffect(() => {
    if (!isPanelResizing) {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      const resizeState = resizeStateRef.current;
      if (!resizeState) {
        return;
      }

      const nextWidth = clampSidePanelWidth(
        resizeState.startWidth + event.clientX - resizeState.startX,
        window.innerWidth,
      );

      widthRef.current = nextWidth;
      setSidePanelWidth(nextWidth);
    };

    const stopResize = () => {
      if (!resizeStateRef.current) {
        return;
      }

      resizeStateRef.current = null;
      setIsPanelResizing(false);
      document.body.classList.remove(RESIZING_BODY_CLASS);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      onWidthCommitRef.current?.(widthRef.current);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("mouseup", stopResize);
    window.addEventListener("blur", stopResize);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("mouseup", stopResize);
      window.removeEventListener("blur", stopResize);
      if (resizeStateRef.current) {
        resizeStateRef.current = null;
        document.body.classList.remove(RESIZING_BODY_CLASS);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
  }, [isPanelResizing]);

  const handleResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeStateRef.current = {
      startX: event.clientX,
      startWidth: sidePanelWidth,
    };
    setIsPanelResizing(true);
    document.body.classList.add(RESIZING_BODY_CLASS);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const resetWidth = () => {
    const nextWidth = clampSidePanelWidth(DEFAULT_SIDE_PANEL_WIDTH, window.innerWidth);
    widthRef.current = nextWidth;
    setSidePanelWidth(nextWidth);
    onWidthCommitRef.current?.(nextWidth);
  };

  return {
    sidePanelWidth,
    isPanelResizing,
    handleResizeStart,
    resetWidth,
  };
}
function clampSidePanelWidth(width: number, viewportWidth: number): number {
  const safeWidth = Number.isFinite(width) ? width : DEFAULT_SIDE_PANEL_WIDTH;
  const dynamicMaxWidth = Math.min(
    MAX_SIDE_PANEL_WIDTH,
    Math.max(MIN_SIDE_PANEL_WIDTH, Math.floor(viewportWidth * 0.46)),
  );

  return Math.min(Math.max(Math.round(safeWidth), MIN_SIDE_PANEL_WIDTH), dynamicMaxWidth);
}

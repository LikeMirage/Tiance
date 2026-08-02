import { useCallback, useEffect, useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { WindowBounds } from "../../../shared/types/desktopShell";
import {
  clampDragAnchor,
  hasDragStarted,
  type DragSession,
} from "./titlebarDrag";

type UseWindowTitlebarDragInput = {
  canStartNativeDrag: boolean;
  getBounds: () => Promise<WindowBounds>;
  isAvailable: boolean;
  isFrameless: boolean;
  isMaximized: boolean;
  moveWindow: (x: number, y: number) => Promise<unknown>;
  startNativeDrag: (
    screenX: number,
    screenY: number,
    anchorX: number,
    clientY: number,
  ) => Promise<boolean>;
  restoreForDrag: (
    screenX: number,
    screenY: number,
    anchorX: number,
    clientY: number,
  ) => Promise<WindowBounds>;
};

type WindowDragMode = "native" | "fallback";
type WindowDragDiagnosticMode = WindowDragMode | "native-failed";

const WINDOW_DRAGGING_CLASS = "tiance-window-dragging";
const WINDOW_DRAGGING_NATIVE_CLASS = "tiance-window-dragging--native";
const WINDOW_DRAGGING_FALLBACK_CLASS = "tiance-window-dragging--fallback";
const WINDOW_DRAG_PERFORMANCE_TIMEOUT_MS = 8000;

function reportWindowDragMode(mode: WindowDragDiagnosticMode) {
  const label = `window drag mode: ${mode}`;

  if (import.meta.env.DEV) {
    console.info(`[tiance] ${label}`);
  }

  const recordStartupMark = window.pywebview?.api?.record_startup_mark;
  if (!recordStartupMark) {
    return;
  }

  try {
    const result = recordStartupMark(label, null);
    if (typeof result === "object" && result !== null && "catch" in result) {
      void result.catch(() => undefined);
    }
  } catch {
    // Drag diagnostics must never affect window movement.
  }
}

export function useWindowTitlebarDrag({
  canStartNativeDrag,
  getBounds,
  isAvailable,
  isFrameless,
  isMaximized,
  moveWindow,
  startNativeDrag,
  restoreForDrag,
}: UseWindowTitlebarDragInput) {
  const frameRef = useRef<number | null>(null);
  const dragSessionRef = useRef<DragSession | null>(null);
  const dragPerformanceTimeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const clearDragPerformanceMode = useCallback(() => {
    if (dragPerformanceTimeoutRef.current !== null) {
      window.clearTimeout(dragPerformanceTimeoutRef.current);
      dragPerformanceTimeoutRef.current = null;
    }

    const root = document.documentElement;
    root.classList.remove(
      WINDOW_DRAGGING_CLASS,
      WINDOW_DRAGGING_NATIVE_CLASS,
      WINDOW_DRAGGING_FALLBACK_CLASS,
    );
    delete root.dataset.windowDragMode;
  }, []);

  const setDragPerformanceMode = useCallback(
    (mode: WindowDragMode) => {
      if (dragPerformanceTimeoutRef.current !== null) {
        window.clearTimeout(dragPerformanceTimeoutRef.current);
        dragPerformanceTimeoutRef.current = null;
      }

      const root = document.documentElement;
      root.classList.add(WINDOW_DRAGGING_CLASS);
      root.classList.toggle(WINDOW_DRAGGING_NATIVE_CLASS, mode === "native");
      root.classList.toggle(WINDOW_DRAGGING_FALLBACK_CLASS, mode === "fallback");
      root.dataset.windowDragMode = mode;

      dragPerformanceTimeoutRef.current = window.setTimeout(() => {
        clearDragPerformanceMode();
      }, WINDOW_DRAG_PERFORMANCE_TIMEOUT_MS);
    },
    [clearDragPerformanceMode],
  );

  const clearActiveDrag = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }

    dragSessionRef.current = null;
    clearDragPerformanceMode();
  }, [clearDragPerformanceMode]);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      clearActiveDrag();
    };
  }, [clearActiveDrag]);

  const applyMove = useCallback(async () => {
    frameRef.current = null;

    const session = dragSessionRef.current;
    if (!mountedRef.current || !session || !session.latestPointer) {
      return;
    }

    if (!session.draggingStarted) {
      if (
        !hasDragStarted(
          session.latestPointer,
          session.startScreenX,
          session.startScreenY,
        )
      ) {
        return;
      }

      session.draggingStarted = true;
    }

    if (session.dragOffsetX === null || session.dragOffsetY === null) {
      session.startBounds ??= await session.startBoundsPromise;
      if (!mountedRef.current || !dragSessionRef.current?.latestPointer) {
        return;
      }

      session.dragOffsetX = session.startScreenX - session.startBounds.x;
      session.dragOffsetY = session.startScreenY - session.startBounds.y;
    }

    if (session.activeMaximized) {
      const restoredBounds = await restoreForDrag(
        session.startScreenX,
        session.startScreenY,
        clampDragAnchor(session.startClientX / Math.max(window.innerWidth, 1)),
        session.startClientY,
      );

      session.dragOffsetX = session.startScreenX - restoredBounds.x;
      session.dragOffsetY = session.startScreenY - restoredBounds.y;
      session.activeMaximized = false;
    }

    if (
      session.dragOffsetX === null ||
      session.dragOffsetY === null ||
      !session.latestPointer
    ) {
      return;
    }

    const nextX = session.latestPointer.screenX - session.dragOffsetX;
    const nextY = session.latestPointer.screenY - session.dragOffsetY;
    await moveWindow(nextX, nextY);
  }, [moveWindow, restoreForDrag]);

  const handleDragPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 || !isAvailable || !isFrameless) {
        return;
      }

      clearActiveDrag();
      event.preventDefault();

      if (canStartNativeDrag) {
        const dragTarget = event.currentTarget;
        const pointerId = event.pointerId;
        const startScreenX = event.screenX;
        const startScreenY = event.screenY;
        const startClientX = event.clientX;
        const startClientY = event.clientY;
        setDragPerformanceMode("native");
        void startNativeDrag(
          startScreenX,
          startScreenY,
          clampDragAnchor(startClientX / Math.max(window.innerWidth, 1)),
          startClientY,
        ).then((didStart) => {
          if (didStart) {
            reportWindowDragMode("native");
            return;
          }

          if (!mountedRef.current || dragSessionRef.current) {
            return;
          }

          reportWindowDragMode("native-failed");
          setDragPerformanceMode("fallback");
          reportWindowDragMode("fallback");

          try {
            dragTarget.setPointerCapture(pointerId);
          } catch {
            clearActiveDrag();
            return;
          }

          dragSessionRef.current = {
            pointerId,
            startScreenX,
            startScreenY,
            startClientX,
            startClientY,
            startBoundsPromise: getBounds(),
            startBounds: null,
            dragOffsetX: null,
            dragOffsetY: null,
            activeMaximized: isMaximized,
            draggingStarted: false,
            latestPointer: null,
          };
        });
        return;
      }

      event.currentTarget.setPointerCapture(event.pointerId);
      setDragPerformanceMode("fallback");
      reportWindowDragMode("fallback");

      dragSessionRef.current = {
        pointerId: event.pointerId,
        startScreenX: event.screenX,
        startScreenY: event.screenY,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startBoundsPromise: getBounds(),
        startBounds: null,
        dragOffsetX: null,
        dragOffsetY: null,
        activeMaximized: isMaximized,
        draggingStarted: false,
        latestPointer: null,
      };
    },
    [
      canStartNativeDrag,
      clearActiveDrag,
      getBounds,
      isAvailable,
      isFrameless,
      isMaximized,
      startNativeDrag,
      setDragPerformanceMode,
    ],
  );

  const handleDragPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const session = dragSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) {
        clearDragPerformanceMode();
        return;
      }

      session.latestPointer = {
        screenX: event.screenX,
        screenY: event.screenY,
      };

      if (frameRef.current !== null) {
        return;
      }

      frameRef.current = window.requestAnimationFrame(() => {
        void applyMove();
      });
    },
    [applyMove],
  );

  const handleDragPointerEnd = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const session = dragSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) {
        return;
      }

      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }

      clearActiveDrag();
    },
    [clearActiveDrag, clearDragPerformanceMode],
  );

  return {
    clearActiveDrag,
    handleDragPointerDown,
    handleDragPointerEnd,
    handleDragPointerMove,
  };
}

import type { PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";

import "./window-resize-handles.css";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import type { WindowBounds } from "../../../shared/types/desktopShell";
import {
  calculateResizeBounds,
  resizeHandleEdges,
  type ResizeEdge,
  type ResizeSession,
} from "../model/resizeBounds";

export function WindowResizeHandles() {
  const {
    state,
    canStartNativeResize,
    getBounds,
    nativeResizeMode,
    persistWindowSizePreferences,
    setBounds,
    startNativeResize,
  } = useDesktopShell();
  const frameRef = useRef<number | null>(null);
  const isApplyingResizeRef = useRef(false);
  const lastRequestedBoundsRef = useRef<WindowBounds | null>(null);
  const needsLatestResizeRef = useRef(false);
  const resizeSessionRef = useRef<ResizeSession | null>(null);
  const captureTargetRef = useRef<HTMLDivElement | null>(null);
  const resizeAttemptRef = useRef(0);
  const mountedRef = useRef(true);

  const disabled =
    !state.available ||
    !state.frameless ||
    state.maximized ||
    nativeResizeMode === "system-edge";

  const clearActiveResize = useCallback(() => {
    resizeAttemptRef.current += 1;
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }

    const session = resizeSessionRef.current;
    const target = captureTargetRef.current;
    resizeSessionRef.current = null;
    captureTargetRef.current = null;
    if (session && target?.hasPointerCapture(session.pointerId)) {
      target.releasePointerCapture(session.pointerId);
    }
    isApplyingResizeRef.current = false;
    lastRequestedBoundsRef.current = null;
    needsLatestResizeRef.current = false;
    setWindowResizingClass(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      clearActiveResize();
    };
  }, [clearActiveResize]);

  useEffect(() => {
    const endInterruptedResize = () => {
      const wasResizing = resizeSessionRef.current !== null;
      clearActiveResize();
      if (wasResizing) void persistWindowSizePreferences();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") endInterruptedResize();
    };
    window.addEventListener("blur", endInterruptedResize);
    window.addEventListener("pointerup", endInterruptedResize);
    window.addEventListener("pointercancel", endInterruptedResize);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("blur", endInterruptedResize);
      window.removeEventListener("pointerup", endInterruptedResize);
      window.removeEventListener("pointercancel", endInterruptedResize);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [clearActiveResize, persistWindowSizePreferences]);

  useEffect(() => {
    if (disabled) clearActiveResize();
  }, [clearActiveResize, disabled]);

  const applyResize = useCallback(async () => {
    frameRef.current = null;

    const session = resizeSessionRef.current;
    if (!mountedRef.current || !session || !session.latestPointer) {
      return;
    }

    if (isApplyingResizeRef.current) {
      needsLatestResizeRef.current = true;
      return;
    }

    isApplyingResizeRef.current = true;
    const attempt = resizeAttemptRef.current;

    try {
      session.startBounds ??= await session.startBoundsPromise;
      if (!mountedRef.current || resizeSessionRef.current !== session || !session.latestPointer) {
        return;
      }

      const nextBounds = calculateResizeBounds(
        session.edge,
        session.startBounds,
        session.startPointer,
        session.latestPointer,
        state.minWidth,
        state.minHeight,
      );

      if (areWindowBoundsEqual(lastRequestedBoundsRef.current, nextBounds)) {
        return;
      }

      lastRequestedBoundsRef.current = nextBounds;
      await setBounds(nextBounds);
    } finally {
      if (resizeAttemptRef.current === attempt) {
        isApplyingResizeRef.current = false;

        if (
          needsLatestResizeRef.current &&
          mountedRef.current &&
          resizeSessionRef.current?.latestPointer
        ) {
          needsLatestResizeRef.current = false;
          frameRef.current = window.requestAnimationFrame(() => {
            void applyResize();
          });
        }
      }
    }
  }, [setBounds, state.minHeight, state.minWidth]);

  const beginFallbackResize = useCallback(
    (
      edge: ResizeEdge,
      target: HTMLDivElement,
      pointerId: number,
      screenX: number,
      screenY: number,
    ) => {
      try {
        target.setPointerCapture(pointerId);
      } catch {
        return;
      }

      setWindowResizingClass(true);
      captureTargetRef.current = target;
      resizeSessionRef.current = {
        pointerId,
        edge,
        startPointer: {
          screenX,
          screenY,
        },
        startBoundsPromise: getBounds(),
        startBounds: null,
        latestPointer: null,
      };
    },
    [getBounds],
  );

  const startResize = useCallback(
    (edge: ResizeEdge, event: ReactPointerEvent<HTMLDivElement>) => {
      if (disabled || event.button !== 0) {
        return;
      }

      clearActiveResize();
      const attempt = resizeAttemptRef.current;
      event.preventDefault();
      event.stopPropagation();

      const target = event.currentTarget;
      const pointerId = event.pointerId;
      const screenX = event.screenX;
      const screenY = event.screenY;

      if (canStartNativeResize) {
        void startNativeResize(edge, screenX, screenY).catch(() => false).then((didStart) => {
          if (didStart) {
            void persistWindowSizePreferences();
            return;
          }

          if (!mountedRef.current || resizeAttemptRef.current !== attempt || resizeSessionRef.current) {
            return;
          }

          beginFallbackResize(edge, target, pointerId, screenX, screenY);
        });
        return;
      }

      beginFallbackResize(edge, target, pointerId, screenX, screenY);
    },
    [
      beginFallbackResize,
      canStartNativeResize,
      clearActiveResize,
      disabled,
      persistWindowSizePreferences,
      startNativeResize,
    ],
  );

  const handleResizePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const session = resizeSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) {
        return;
      }

      if ((event.buttons & 1) === 0) {
        clearActiveResize();
        void persistWindowSizePreferences();
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
        void applyResize();
      });
    },
    [applyResize, clearActiveResize, persistWindowSizePreferences],
  );

  const handleResizePointerEnd = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const session = resizeSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) {
        return;
      }

      clearActiveResize();
      void persistWindowSizePreferences();
    },
    [clearActiveResize, persistWindowSizePreferences],
  );

  const handles = useMemo(
    () =>
      resizeHandleEdges.map((edge) => (
        <div
          key={edge}
          className={`window-resize-handle window-resize-handle--${edge}`}
          onPointerDown={(event) => startResize(edge, event)}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerEnd}
          onPointerCancel={handleResizePointerEnd}
          onLostPointerCapture={clearActiveResize}
        />
      )),
    [clearActiveResize, handleResizePointerEnd, handleResizePointerMove, startResize],
  );

  if (disabled) {
    return null;
  }

  // Window chrome must remain outside the workspace's isolated stacking context.
  return createPortal(<div className="window-resize-handles">{handles}</div>, document.body);
}

function setWindowResizingClass(active: boolean) {
  document.documentElement.classList.toggle("ds-window-resizing", active);
}

function areWindowBoundsEqual(left: WindowBounds | null, right: WindowBounds) {
  if (!left) {
    return false;
  }

  return (
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height
  );
}

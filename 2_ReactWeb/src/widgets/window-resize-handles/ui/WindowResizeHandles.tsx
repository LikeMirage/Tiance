import type { PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";

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
  const mountedRef = useRef(true);

  const disabled =
    !state.available ||
    !state.frameless ||
    state.maximized ||
    nativeResizeMode === "system-edge";

  const clearActiveResize = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }

    resizeSessionRef.current = null;
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

    try {
      session.startBounds ??= await session.startBoundsPromise;
      if (!mountedRef.current || !resizeSessionRef.current?.latestPointer) {
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
      if (disabled) {
        return;
      }

      clearActiveResize();
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

          if (!mountedRef.current || resizeSessionRef.current) {
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
    [applyResize],
  );

  const handleResizePointerEnd = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const session = resizeSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) {
        return;
      }

      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
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

  return <div className="window-resize-handles">{handles}</div>;
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

import type { WindowBounds } from "../../../shared/types/desktopShell";

export interface DragPointerSnapshot {
  screenX: number;
  screenY: number;
}

export interface DragSession {
  pointerId: number;
  startScreenX: number;
  startScreenY: number;
  startClientX: number;
  startClientY: number;
  startBoundsPromise: Promise<WindowBounds>;
  startBounds: WindowBounds | null;
  dragOffsetX: number | null;
  dragOffsetY: number | null;
  activeMaximized: boolean;
  draggingStarted: boolean;
  latestPointer: DragPointerSnapshot | null;
}

export function hasDragStarted(
  pointer: DragPointerSnapshot,
  startScreenX: number,
  startScreenY: number,
) {
  const moveDistance =
    Math.abs(pointer.screenX - startScreenX) +
    Math.abs(pointer.screenY - startScreenY);

  return moveDistance >= 4;
}

export function clampDragAnchor(value: number) {
  return Math.min(Math.max(value, 0.12), 0.88);
}

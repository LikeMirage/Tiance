import type { WindowBounds } from "../../../shared/types/desktopShell";

export type ResizeEdge =
  | "top"
  | "right"
  | "bottom"
  | "left"
  | "top-left"
  | "top-right"
  | "bottom-right"
  | "bottom-left";

export interface ResizePointerSnapshot {
  screenX: number;
  screenY: number;
}

export interface ResizeSession {
  pointerId: number;
  edge: ResizeEdge;
  startPointer: ResizePointerSnapshot;
  startBoundsPromise: Promise<WindowBounds>;
  startBounds: WindowBounds | null;
  latestPointer: ResizePointerSnapshot | null;
}

export const resizeHandleEdges: readonly ResizeEdge[] = [
  "top",
  "right",
  "bottom",
  "left",
  "top-left",
  "top-right",
  "bottom-right",
  "bottom-left",
];

export function calculateResizeBounds(
  edge: ResizeEdge,
  startBounds: WindowBounds,
  startPointer: ResizePointerSnapshot,
  pointer: ResizePointerSnapshot,
  minWidth: number,
  minHeight: number,
): WindowBounds {
  const deltaX = pointer.screenX - startPointer.screenX;
  const deltaY = pointer.screenY - startPointer.screenY;

  let x = startBounds.x;
  let y = startBounds.y;
  let width = startBounds.width;
  let height = startBounds.height;

  if (edge.includes("left")) {
    width = startBounds.width - deltaX;
    if (width < minWidth) {
      width = minWidth;
      x = startBounds.x + (startBounds.width - minWidth);
    } else {
      x = startBounds.x + deltaX;
    }
  }

  if (edge.includes("right")) {
    width = Math.max(minWidth, startBounds.width + deltaX);
  }

  if (edge.includes("top")) {
    height = startBounds.height - deltaY;
    if (height < minHeight) {
      height = minHeight;
      y = startBounds.y + (startBounds.height - minHeight);
    } else {
      y = startBounds.y + deltaY;
    }
  }

  if (edge.includes("bottom")) {
    height = Math.max(minHeight, startBounds.height + deltaY);
  }

  return {
    x: Math.round(x),
    y: Math.round(y),
    width: Math.round(width),
    height: Math.round(height),
  };
}

const HOVER_TICK_WIDTHS = [28, 20, 16, 13] as const;

export function getMessageNavigatorHoverTickWidth(distance: number | null) {
  if (distance === null || distance < 0) return null;
  return HOVER_TICK_WIDTHS[distance] ?? null;
}

export function resolveNearestMessageNavigatorIndex(
  itemCount: number,
  pointerY: number,
  trackTop: number,
  trackHeight: number,
) {
  if (itemCount <= 0 || trackHeight <= 0) return null;
  const relativeY = Math.min(trackHeight, Math.max(0, pointerY - trackTop));
  return Math.min(itemCount - 1, Math.floor((relativeY / trackHeight) * itemCount));
}

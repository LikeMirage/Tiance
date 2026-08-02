import { useLayoutEffect, useRef, useState } from "react";

export type AssistantProcessArchiveMode = "all" | "except-last" | "none";

type AssistantProcessCollapseAnchor = {
  archiveMode: AssistantProcessArchiveMode;
  scrollElement: HTMLElement;
  targetBottomViewportOffset: number;
};

type AssistantProcessCollapseGeometry = {
  regionBottom: number;
  regionTop: number;
  viewportBottom: number;
  viewportTop: number;
};

const COLLAPSED_CONTENT_LANDING_OFFSET = 8;

export function useAssistantProcessAutoCollapse(
  desiredArchiveMode: AssistantProcessArchiveMode,
) {
  const processRegionRef = useRef<HTMLElement>(null);
  const [archiveMode, setArchiveMode] = useState(desiredArchiveMode);
  const pendingAnchorRef = useRef<AssistantProcessCollapseAnchor | null>(null);

  useLayoutEffect(() => {
    if (archiveMode === desiredArchiveMode) return;

    pendingAnchorRef.current = isMoreCollapsed(desiredArchiveMode, archiveMode)
      ? captureCollapseAnchor(processRegionRef.current, desiredArchiveMode)
      : null;
    setArchiveMode(desiredArchiveMode);
  }, [archiveMode, desiredArchiveMode]);

  useLayoutEffect(() => {
    const anchor = pendingAnchorRef.current;
    if (!anchor || anchor.archiveMode !== archiveMode) return;
    pendingAnchorRef.current = null;
    restoreCollapseAnchor(processRegionRef.current, anchor);
  }, [archiveMode]);

  return {
    archiveMode,
    processRegionRef,
  };
}

export function resolveCollapseBottomViewportOffset({
  regionBottom,
  regionTop,
  viewportBottom,
  viewportTop,
}: AssistantProcessCollapseGeometry) {
  if (regionTop >= viewportTop) {
    return null;
  }
  if (regionBottom <= viewportBottom) {
    return regionBottom - viewportTop;
  }
  return COLLAPSED_CONTENT_LANDING_OFFSET;
}

export function resolveCollapseScrollAdjustment(
  currentBottomViewportOffset: number,
  targetBottomViewportOffset: number,
) {
  return currentBottomViewportOffset - targetBottomViewportOffset;
}

function captureCollapseAnchor(
  regionElement: HTMLElement | null,
  archiveMode: AssistantProcessArchiveMode,
): AssistantProcessCollapseAnchor | null {
  if (!regionElement) return null;
  const scrollElement = regionElement.closest<HTMLElement>(".ai-panel__body");
  if (!scrollElement) return null;

  const viewportRect = scrollElement.getBoundingClientRect();
  const regionRect = regionElement.getBoundingClientRect();
  const targetBottomViewportOffset = resolveCollapseBottomViewportOffset({
    regionBottom: regionRect.bottom,
    regionTop: regionRect.top,
    viewportBottom: viewportRect.bottom,
    viewportTop: viewportRect.top,
  });
  if (targetBottomViewportOffset === null) return null;

  return {
    archiveMode,
    scrollElement,
    targetBottomViewportOffset,
  };
}

function restoreCollapseAnchor(
  regionElement: HTMLElement | null,
  anchor: AssistantProcessCollapseAnchor,
) {
  if (!regionElement || !regionElement.isConnected || !anchor.scrollElement.isConnected) {
    return;
  }
  const viewportRect = anchor.scrollElement.getBoundingClientRect();
  const currentBottomViewportOffset =
    regionElement.getBoundingClientRect().bottom - viewportRect.top;
  anchor.scrollElement.scrollTop += resolveCollapseScrollAdjustment(
    currentBottomViewportOffset,
    anchor.targetBottomViewportOffset,
  );
}

function isMoreCollapsed(
  next: AssistantProcessArchiveMode,
  previous: AssistantProcessArchiveMode,
) {
  return archiveModeRank(next) > archiveModeRank(previous);
}

function archiveModeRank(mode: AssistantProcessArchiveMode) {
  if (mode === "all") return 2;
  if (mode === "except-last") return 1;
  return 0;
}

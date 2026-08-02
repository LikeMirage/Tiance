import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type WheelEvent,
} from "react";

type ZoomAnchorPoint = {
  clientX: number;
  clientY: number;
};

type ZoomAnchorState = {
  contentHeight: number;
  contentRatioX: number;
  contentRatioY: number;
  contentWidth: number;
  viewportOffsetX: number;
  viewportOffsetY: number;
};

type PanStart = {
  scrollLeft: number;
  scrollTop: number;
  x: number;
  y: number;
};

type ResolveCurrentZoomState<TViewport extends HTMLElement, TContent extends HTMLElement> = {
  content: TContent | null;
  viewport: TViewport | null;
  zoom: number;
};

type UsePanZoomViewportOptions<TViewport extends HTMLElement, TContent extends HTMLElement> = {
  canInteract?: boolean;
  getZoomStep?: (currentZoom: number) => number;
  maxZoom?: number;
  minZoom?: number;
  onZoomChange: (zoom: number) => void;
  resolveCurrentZoom?: (state: ResolveCurrentZoomState<TViewport, TContent>) => number;
  shouldStartPan?: (event: PointerEvent<TViewport>) => boolean;
  zoom: number;
};

const defaultMinZoom = 0.1;
const defaultMaxZoom = 8;

export function usePanZoomViewport<TViewport extends HTMLElement, TContent extends HTMLElement>({
  canInteract = true,
  getZoomStep = getDefaultZoomStep,
  maxZoom = defaultMaxZoom,
  minZoom = defaultMinZoom,
  onZoomChange,
  resolveCurrentZoom,
  shouldStartPan,
  zoom,
}: UsePanZoomViewportOptions<TViewport, TContent>) {
  const contentRef = useRef<TContent | null>(null);
  const pendingAnchorRef = useRef<ZoomAnchorState | null>(null);
  const panStartRef = useRef<PanStart | null>(null);
  const restoreFrameRef = useRef<number | null>(null);
  const viewportRef = useRef<TViewport | null>(null);
  const [isPanning, setIsPanning] = useState(false);

  const getCurrentZoom = useCallback(() => (
    resolveCurrentZoom
      ? resolveCurrentZoom({
        content: contentRef.current,
        viewport: viewportRef.current,
        zoom,
      })
      : zoom
  ), [resolveCurrentZoom, zoom]);

  const restorePendingAnchor = useCallback(() => {
    const anchor = pendingAnchorRef.current;
    const content = contentRef.current;
    const viewport = viewportRef.current;
    if (!anchor || !content || !viewport) return;

    const contentRect = content.getBoundingClientRect();
    if (contentRect.width <= 0 || contentRect.height <= 0) return;
    if (
      Math.abs(contentRect.width - anchor.contentWidth) < 0.5
      && Math.abs(contentRect.height - anchor.contentHeight) < 0.5
    ) {
      return;
    }

    const viewportRect = viewport.getBoundingClientRect();
    const nextAnchorX = contentRect.left + contentRect.width * anchor.contentRatioX;
    const nextAnchorY = contentRect.top + contentRect.height * anchor.contentRatioY;
    viewport.scrollLeft += nextAnchorX - (viewportRect.left + anchor.viewportOffsetX);
    viewport.scrollTop += nextAnchorY - (viewportRect.top + anchor.viewportOffsetY);
    pendingAnchorRef.current = null;
  }, []);

  const scheduleAnchorRestore = useCallback(() => {
    if (restoreFrameRef.current !== null) {
      window.cancelAnimationFrame(restoreFrameRef.current);
    }
    restoreFrameRef.current = window.requestAnimationFrame(() => {
      restoreFrameRef.current = null;
      restorePendingAnchor();
    });
  }, [restorePendingAnchor]);

  const applyZoom = useCallback((nextZoom: number, anchor?: ZoomAnchorPoint) => {
    if (!canInteract) return;

    const currentZoom = getCurrentZoom();
    const resolvedZoom = clampZoom(nextZoom, minZoom, maxZoom);
    if (Math.abs(resolvedZoom - currentZoom) < 0.001) return;

    pendingAnchorRef.current = resolveZoomAnchor(
      viewportRef.current,
      contentRef.current,
      anchor,
    );
    onZoomChange(resolvedZoom);
    scheduleAnchorRestore();
  }, [canInteract, getCurrentZoom, maxZoom, minZoom, onZoomChange, scheduleAnchorRestore]);

  const zoomOut = useCallback((anchor?: ZoomAnchorPoint) => {
    const currentZoom = getCurrentZoom();
    applyZoom(currentZoom - getZoomStep(currentZoom), anchor);
  }, [applyZoom, getCurrentZoom, getZoomStep]);

  const zoomIn = useCallback((anchor?: ZoomAnchorPoint) => {
    const currentZoom = getCurrentZoom();
    applyZoom(currentZoom + getZoomStep(currentZoom), anchor);
  }, [applyZoom, getCurrentZoom, getZoomStep]);

  const handleWheel = useCallback((event: WheelEvent<TViewport>) => {
    if (!canInteract) return;

    event.preventDefault();
    const currentZoom = getCurrentZoom();
    const direction = event.deltaY < 0 ? 1 : -1;
    applyZoom(currentZoom + direction * getZoomStep(currentZoom), {
      clientX: event.clientX,
      clientY: event.clientY,
    });
  }, [applyZoom, canInteract, getCurrentZoom, getZoomStep]);

  const startPan = useCallback((event: PointerEvent<TViewport>) => {
    if (!canInteract || event.button !== 0 || shouldStartPan?.(event) === false) {
      return;
    }

    const viewport = viewportRef.current;
    if (!viewport) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panStartRef.current = {
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
      x: event.clientX,
      y: event.clientY,
    };
    setIsPanning(true);
  }, [canInteract, shouldStartPan]);

  const movePan = useCallback((event: PointerEvent<TViewport>) => {
    const panStart = panStartRef.current;
    const viewport = viewportRef.current;
    if (!panStart || !viewport) return;

    event.preventDefault();
    viewport.scrollLeft = panStart.scrollLeft - (event.clientX - panStart.x);
    viewport.scrollTop = panStart.scrollTop - (event.clientY - panStart.y);
  }, []);

  const stopPan = useCallback((event: PointerEvent<TViewport>) => {
    if (!panStartRef.current) return;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panStartRef.current = null;
    setIsPanning(false);
  }, []);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver(() => {
      scheduleAnchorRestore();
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [scheduleAnchorRestore]);

  useEffect(() => () => {
    if (restoreFrameRef.current !== null) {
      window.cancelAnimationFrame(restoreFrameRef.current);
    }
  }, []);

  return {
    applyZoom,
    contentRef,
    handleWheel,
    isPanning,
    movePan,
    startPan,
    stopPan,
    viewportRef,
    zoomIn,
    zoomOut,
  };
}

function getDefaultZoomStep(current: number) {
  if (current < 0.5) return 0.1;
  if (current < 2) return 0.25;
  return 0.5;
}

function clampZoom(value: number, minZoom: number, maxZoom: number) {
  return Math.max(minZoom, Math.min(maxZoom, Math.round(value * 100) / 100));
}

function clampRatio(value: number) {
  return Math.max(0, Math.min(1, value));
}

function resolveZoomAnchor(
  viewport: HTMLElement | null,
  content: HTMLElement | null,
  anchor: ZoomAnchorPoint | undefined,
) {
  if (!viewport || !content || !anchor) return null;

  const viewportRect = viewport.getBoundingClientRect();
  const contentRect = content.getBoundingClientRect();
  if (contentRect.width <= 0 || contentRect.height <= 0) return null;

  return {
    contentHeight: contentRect.height,
    contentRatioX: clampRatio((anchor.clientX - contentRect.left) / contentRect.width),
    contentRatioY: clampRatio((anchor.clientY - contentRect.top) / contentRect.height),
    contentWidth: contentRect.width,
    viewportOffsetX: anchor.clientX - viewportRect.left,
    viewportOffsetY: anchor.clientY - viewportRect.top,
  };
}

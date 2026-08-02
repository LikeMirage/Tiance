import { useCallback, useEffect, useRef } from "react";

type HorizontalScrollOptions = {
  animate?: boolean;
  durationMs?: number;
};

const DEFAULT_DURATION_MS = 240;

export function useHorizontalScrollAnimation() {
  const frameRef = useRef<number | null>(null);

  const cancelHorizontalScroll = useCallback(() => {
    if (frameRef.current === null) return;
    window.cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
  }, []);

  const scrollHorizontallyTo = useCallback((
    element: HTMLElement,
    requestedLeft: number,
    options: HorizontalScrollOptions = {},
  ) => {
    cancelHorizontalScroll();

    const maxScrollLeft = Math.max(0, element.scrollWidth - element.clientWidth);
    const targetLeft = Math.min(Math.max(0, requestedLeft), maxScrollLeft);
    const startLeft = element.scrollLeft;
    const distance = targetLeft - startLeft;
    const prefersReducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const shouldAnimate = options.animate !== false
      && Math.abs(distance) >= 0.5
      && !prefersReducedMotion;

    if (!shouldAnimate) {
      element.scrollLeft = targetLeft;
      return;
    }

    const durationMs = Math.max(1, options.durationMs ?? DEFAULT_DURATION_MS);
    const startedAt = window.performance.now();

    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / durationMs);
      const easedProgress = 1 - Math.pow(1 - progress, 4);
      element.scrollLeft = startLeft + distance * easedProgress;

      if (progress < 1) {
        frameRef.current = window.requestAnimationFrame(step);
        return;
      }

      element.scrollLeft = targetLeft;
      frameRef.current = null;
    };

    frameRef.current = window.requestAnimationFrame(step);
  }, [cancelHorizontalScroll]);

  useEffect(() => cancelHorizontalScroll, [cancelHorizontalScroll]);

  return {
    cancelHorizontalScroll,
    scrollHorizontallyTo,
  };
}

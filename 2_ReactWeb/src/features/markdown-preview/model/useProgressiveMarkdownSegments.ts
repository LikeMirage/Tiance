import { useEffect, useMemo, useState } from "react";

import { buildProgressiveMarkdownSegments } from "./markdownSegments";

export function useProgressiveMarkdownSegments(content: string) {
  const segments = useMemo(
    () => buildProgressiveMarkdownSegments(content),
    [content],
  );
  const [progress, setProgress] = useState({ content, visibleCount: 0 });
  // An external edit must not collapse an already visible document to zero height.
  // Keep the visible prefix and progressively reveal only any additional segments.
  const visibleCount = Math.min(progress.visibleCount, segments.length);

  useEffect(() => {
    let disposed = false;
    let frameId: number | null = null;
    let timerId: number | null = null;
    let nextVisibleCount = Math.min(progress.visibleCount, segments.length);

    setProgress({ content, visibleCount: nextVisibleCount });

    const scheduleNextSegment = () => {
      timerId = window.setTimeout(() => {
        frameId = window.requestAnimationFrame(() => {
          if (disposed) return;
          nextVisibleCount += 1;
          setProgress({ content, visibleCount: nextVisibleCount });
          if (nextVisibleCount < segments.length) {
            scheduleNextSegment();
          }
        });
      }, 0);
    };

    if (nextVisibleCount < segments.length) {
      scheduleNextSegment();
    }

    return () => {
      disposed = true;
      if (frameId !== null) window.cancelAnimationFrame(frameId);
      if (timerId !== null) window.clearTimeout(timerId);
    };
  }, [content, segments.length]);

  return {
    isComplete: visibleCount >= segments.length,
    visibleSegments: segments.slice(0, visibleCount),
  };
}

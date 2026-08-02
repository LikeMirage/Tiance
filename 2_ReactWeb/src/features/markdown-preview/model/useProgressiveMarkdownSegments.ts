import { useEffect, useMemo, useState } from "react";

import { buildProgressiveMarkdownSegments } from "./markdownSegments";

export function useProgressiveMarkdownSegments(content: string) {
  const segments = useMemo(
    () => buildProgressiveMarkdownSegments(content),
    [content],
  );
  const [progress, setProgress] = useState({ content, visibleCount: 0 });
  const visibleCount = progress.content === content ? progress.visibleCount : 0;

  useEffect(() => {
    let disposed = false;
    let frameId: number | null = null;
    let timerId: number | null = null;
    let nextVisibleCount = 0;

    setProgress({ content, visibleCount: 0 });

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

    if (segments.length > 0) {
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

import { useEffect, useRef, useState } from "react";

export function useMinimumLoading(isLoading: boolean, minimumMs = 200): boolean {
  const [isVisible, setIsVisible] = useState(isLoading);
  const loadingStartedAtRef = useRef<number | null>(isLoading ? performance.now() : null);

  useEffect(() => {
    let timeoutId = 0;

    if (isLoading) {
      loadingStartedAtRef.current = performance.now();
      setIsVisible(true);
      return () => window.clearTimeout(timeoutId);
    }

    const startedAt = loadingStartedAtRef.current;
    if (startedAt === null) {
      setIsVisible(false);
      return () => window.clearTimeout(timeoutId);
    }

    const elapsedMs = performance.now() - startedAt;
    const remainingMs = Math.max(0, minimumMs - elapsedMs);
    timeoutId = window.setTimeout(() => {
      loadingStartedAtRef.current = null;
      setIsVisible(false);
    }, remainingMs);

    return () => window.clearTimeout(timeoutId);
  }, [isLoading, minimumMs]);

  return isVisible;
}

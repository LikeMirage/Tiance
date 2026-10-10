import { useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import { createContentReadiness } from "../../../shared/lib/contentReadiness";

/** Reveal a session once its fetched messages, rich content and layout are ready.
 * Later sends and stream updates must never hide the already visible history.
 */
export function useChatContentReadiness(sessionKey: string | null, isFetching: boolean, onReady?: () => void) {
  const readiness = useMemo(() => createContentReadiness(), [sessionKey]);
  const pending = useSyncExternalStore(readiness.subscribe, readiness.getSnapshot, readiness.getSnapshot);
  const [revealed, setRevealed] = useState<typeof readiness | null>(null);
  const isPreparing = Boolean(sessionKey) && revealed !== readiness;
  useLayoutEffect(() => {
    if (!isPreparing || isFetching || pending) return;
    let first = 0;
    let second = 0;
    first = window.requestAnimationFrame(() => {
      if (readiness.getSnapshot()) return;
      onReady?.();
      second = window.requestAnimationFrame(() => {
        if (readiness.getSnapshot()) return;
        onReady?.();
        setRevealed(readiness);
      });
    });
    return () => { window.cancelAnimationFrame(first); window.cancelAnimationFrame(second); };
  }, [isFetching, isPreparing, onReady, pending, readiness]);
  return { readiness, isPreparing };
}

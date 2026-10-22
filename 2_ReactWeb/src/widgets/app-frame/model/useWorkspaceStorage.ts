import { useEffect, useRef, useState } from "react";
import { getWorkspaceStorage, type WorkspaceStorage } from "../../../services/workspace/getWorkspaceStorage";

const REFRESH_MS = 5 * 60_000;

export function useWorkspaceStorage(enabled: boolean) {
  const [data, setData] = useState<WorkspaceStorage | null>(null);
  const [error, setError] = useState(false);
  const completedAt = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let inFlight = false;
    let timer = 0;
    let controller: AbortController | null = null;
    const schedule = () => {
      window.clearTimeout(timer);
      if (disposed || inFlight || document.visibilityState === "hidden") return;
      const delay = completedAt.current === null ? 0 : Math.max(0, REFRESH_MS - (Date.now() - completedAt.current));
      timer = window.setTimeout(() => void load(), delay);
    };
    const load = async () => {
      if (disposed || inFlight || document.visibilityState === "hidden") return;
      inFlight = true;
      controller = new AbortController();
      try {
        const snapshot = await getWorkspaceStorage(controller.signal);
        if (!disposed) { setData(snapshot); setError(false); }
      } catch {
        if (!disposed) setError(true);
      } finally {
        inFlight = false;
        if (!disposed) completedAt.current = Date.now();
        schedule();
      }
    };
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => {
      disposed = true;
      controller?.abort();
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [enabled]);
  return { data, error };
}

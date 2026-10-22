import { useEffect, useRef, useState } from "react";
import type { SystemMetricsSnapshot } from "../../../shared/types/desktopShell";

export type ReadySystemMetrics = SystemMetricsSnapshot & {
  app: NonNullable<SystemMetricsSnapshot["app"]>;
  system: NonNullable<SystemMetricsSnapshot["system"]>;
};
type MetricsMessage = "loading" | "shellDisconnected" | "apiUnavailable" | "dataUnavailable" | "readFailed";
type MetricsState = { state: "loading" | "unavailable"; message: MetricsMessage; metrics: null }
  | { state: "ready"; metrics: ReadySystemMetrics };
const ACTIVE_INTERVAL_MS = 5_000;
const IDLE_INTERVAL_MS = 15_000;
const isPageHidden = () => document.visibilityState === "hidden";

export function useSystemMetrics(available: boolean, detailed: boolean) {
  const [status, setStatus] = useState<MetricsState>({ state: "loading", metrics: null, message: "loading" });
  const detailedRef = useRef(detailed);
  const rescheduleRef = useRef<() => void>(() => {});
  detailedRef.current = detailed;

  useEffect(() => {
    if (!available) {
      setStatus({ state: "unavailable", metrics: null, message: "shellDisconnected" });
      return;
    }
    let disposed = false;
    let inFlight = false;
    let timer = 0;
    let completedAt: number | null = null;
    const fail = (message: MetricsMessage) => setStatus({ state: "unavailable", metrics: null, message });
    const schedule = () => {
      window.clearTimeout(timer);
      if (disposed || inFlight || isPageHidden()) return;
      const interval = detailedRef.current ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS;
      const remaining = completedAt === null ? 0 : Math.max(0, interval - (Date.now() - completedAt));
      timer = window.setTimeout(() => void load(), remaining);
    };
    const load = async () => {
      if (disposed || inFlight || isPageHidden()) return;
      inFlight = true;
      try {
        const api = window.pywebview?.api;
        if (!api?.get_system_metrics) {
          if (!disposed) fail("apiUnavailable");
          return;
        }
        const snapshot = await api.get_system_metrics();
        if (disposed || isPageHidden()) return;
        if (snapshot.available && snapshot.app && snapshot.system) {
          const metrics = { ...snapshot, app: snapshot.app, system: snapshot.system };
          setStatus({ state: "ready", metrics });
        } else fail("dataUnavailable");
      } catch {
        if (!disposed) fail("readFailed");
      } finally {
        inFlight = false;
        completedAt = Date.now();
        schedule();
      }
    };
    rescheduleRef.current = schedule;
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
      rescheduleRef.current = () => {};
    };
  }, [available]);

  useEffect(() => { rescheduleRef.current(); }, [detailed]);
  return { status };
}

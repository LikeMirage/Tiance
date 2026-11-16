import { useEffect } from "react";
import { collectRendererSourceMetrics } from "@/shared/diagnostics/rendererDiagnostics";
import { getMarkdownDomCacheMetrics } from "@/features/markdown-preview/model/markdownDomCache";

const intervalMs = 30_000;
type HeapPerformance = Performance & {
  memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number };
};

export function useRendererDiagnostics(available: boolean) {
  useEffect(() => {
    const api = window.pywebview?.api;
    if (!available || !api?.record_renderer_diagnostics) return;
    let stopped = false;
    let errors = 0;
    let rejections = 0;
    let due = performance.now() + 1000;
    const onError = () => { errors++; };
    const onRejection = () => { rejections++; };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    const sample = async () => {
      if (stopped) return;
      try {
        const started = performance.now();
        const heap = (performance as HeapPerformance).memory;
        const metrics = {
          ...collectRendererSourceMetrics(), ...getMarkdownDomCacheMetrics(),
          uptime_ms: started, interval_lag_ms: Math.max(0, started - due),
          visible: document.visibilityState === "visible" ? 1 : 0,
          development: import.meta.env.DEV ? 1 : 0,
          heap_available: heap ? 1 : 0,
          ...(heap ? { heap_used: heap.usedJSHeapSize, heap_total: heap.totalJSHeapSize, heap_limit: heap.jsHeapSizeLimit } : {}),
          dom_nodes: document.getElementsByTagName("*").length,
          resources: performance.getEntriesByType("resource").length,
          js_errors: errors, unhandled_rejections: rejections,
          sample_duration_ms: performance.now() - started,
        };
        await api.record_renderer_diagnostics!(metrics);
      } catch {
        // Diagnostics cannot interrupt a conversation; native sampling remains independent.
      } finally {
        if (!stopped) {
          due = performance.now() + intervalMs;
          timer = window.setTimeout(() => { void sample(); }, intervalMs);
        }
      }
    };
    // Schedule only after settlement: a blocked bridge cannot accumulate requests.
    let timer = window.setTimeout(() => { void sample(); }, 1000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [available]);
}

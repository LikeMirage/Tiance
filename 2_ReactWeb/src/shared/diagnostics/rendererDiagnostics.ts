type DiagnosticSource = () => Record<string, number>;

// Sources read current refs only when sampled; never retain message snapshots.
const sources = new Set<DiagnosticSource>();

export function registerRendererDiagnosticSource(source: DiagnosticSource) {
  sources.add(source);
  return () => { sources.delete(source); };
}

export function collectRendererSourceMetrics() {
  const metrics: Record<string, number> = { diagnostic_source_errors: 0 };
  for (const source of sources) {
    try {
      for (const [key, value] of Object.entries(source())) {
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0) continue;
        metrics[key] = key.endsWith("_age_ms") || key.startsWith("largest_")
          ? Math.max(metrics[key] ?? 0, value) : (metrics[key] ?? 0) + value;
      }
    } catch {
      metrics.diagnostic_source_errors++;
    }
  }
  return metrics;
}

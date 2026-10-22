export function formatMetricBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0MB";
  const megabytes = bytes / 1024 / 1024;
  return megabytes < 1024 ? `${Math.round(megabytes)}MB` : `${(megabytes / 1024).toFixed(1)}GB`;
}

export function formatMetricPercent(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded}%`;
}

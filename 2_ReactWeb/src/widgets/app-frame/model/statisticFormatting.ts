export function localMonth(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export function formatStatistic(value: number, duration: boolean, language: string, compact = false) {
  if (!duration) return new Intl.NumberFormat(language, compact ? { notation: "compact", maximumFractionDigits: 1 } : {}).format(value);
  const seconds = Math.floor(value / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return compact || seconds % 60 === 0 ? `${minutes}m` : `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return compact || minutes % 60 === 0 ? `${hours}h` : `${hours}h ${minutes % 60}m`;
}

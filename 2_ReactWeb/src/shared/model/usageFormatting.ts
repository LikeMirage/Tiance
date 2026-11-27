export type UsageCostSummary = {
  cost_amount?: number | null;
  cost_currency?: string | null;
};

const TOKEN_UNITS = ["", "k", "M", "B", "T"] as const;

export function formatTokenCount(value: number | null | undefined) {
  const tokenCount = value ?? 0;
  const absValue = Math.abs(tokenCount);
  let scale = 1;
  let unit = 0;
  while (unit < TOKEN_UNITS.length - 1 && absValue > 999 * scale) {
    scale *= 1_000;
    unit++;
  }
  return unit === 0 ? String(tokenCount) : formatScaledNumber(tokenCount / scale) + TOKEN_UNITS[unit];
}

type CacheUsage = {
  prompt_cache_hit_tokens?: number | null;
  prompt_cache_miss_tokens?: number | null;
  estimated_fields?: readonly string[];
};

export function formatCacheHitRate(usage: CacheUsage | undefined, locale: string) {
  const hit = usage?.prompt_cache_hit_tokens;
  const miss = usage?.prompt_cache_miss_tokens;
  if (hit == null || miss == null || hit < 0 || miss < 0 || hit + miss === 0) return "—";
  const estimated = usage?.estimated_fields?.some(field =>
    field === "prompt_cache_hit_tokens" || field === "prompt_cache_miss_tokens");
  const rate = (hit / (hit + miss)).toLocaleString(locale, { style: "percent", maximumFractionDigits: 2 });
  return estimated ? `≈${rate}` : rate;
}

export function formatCostAmount(summary: UsageCostSummary | undefined) {
  if (summary?.cost_amount === null || summary?.cost_amount === undefined) {
    return "--";
  }
  return `${formatCurrencyPrefix(summary.cost_currency)}${formatCostValue(summary.cost_amount)}`;
}

function formatScaledNumber(value: number) {
  const absValue = Math.abs(value);
  const digits = absValue < 10 ? 1 : 0;
  return value.toFixed(digits).replace(/\.0$/, "");
}

function formatCurrencyPrefix(currency: string | null | undefined) {
  const normalizedCurrency = currency?.trim().toUpperCase();
  if (normalizedCurrency === "CNY") return "¥";
  if (normalizedCurrency === "USD") return "$";
  return normalizedCurrency ? `${normalizedCurrency} ` : "";
}

function formatCostValue(value: number) {
  if (value === 0) return "0";
  if (Math.abs(value) < 0.000001) {
    return value.toExponential(2);
  }
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

export type UsageCostSummary = {
  cost_amount?: number | null;
  cost_currency?: string | null;
};

export function formatTokenCount(value: number | null | undefined) {
  const tokenCount = value ?? 0;
  const absValue = Math.abs(tokenCount);
  if (absValue > 999_000) {
    return `${formatScaledNumber(tokenCount / 1_000_000)}M`;
  }
  if (absValue > 999) {
    return `${formatScaledNumber(tokenCount / 1_000)}k`;
  }
  return String(tokenCount);
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

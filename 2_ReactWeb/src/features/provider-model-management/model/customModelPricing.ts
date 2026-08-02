export const DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY = "CNY";

export type CustomModelPricingSummaryLabels = {
  cacheHit: string;
  currency: Record<string, string>;
  input: string;
  output: string;
  perMillionTokens: string;
  separator: string;
};

export const CUSTOM_MODEL_PRICE_CURRENCY_OPTIONS: ReadonlyArray<{
  label: string;
  value: string;
}> = [
  {
    label: "CNY",
    value: "CNY",
  },
  {
    label: "USD",
    value: "USD",
  },
];

const CUSTOM_MODEL_PRICE_INPUT_PATTERN = /^\d*(?:\.\d*)?$/;

export function parseCustomModelPriceInput(
  input: string,
  invalidMessage: string,
): number | null {
  const normalizedInput = input.trim();
  if (!normalizedInput) {
    return null;
  }

  if (
    !CUSTOM_MODEL_PRICE_INPUT_PATTERN.test(normalizedInput) ||
    normalizedInput === "."
  ) {
    throw new Error(invalidMessage);
  }

  const parsedValue = Number(normalizedInput);
  if (!Number.isFinite(parsedValue) || parsedValue < 0) {
    throw new Error(invalidMessage);
  }

  return parsedValue;
}

export function formatCustomModelPriceInput(value: number | null): string {
  return value === null ? "" : String(value);
}

export function formatCustomModelPricingSummary(
  priceCurrency: string,
  inputPricePerMillion: number | null,
  cacheHitPricePerMillion: number | null,
  outputPricePerMillion: number | null,
  labels: CustomModelPricingSummaryLabels,
): string | null {
  const segments: string[] = [];
  if (inputPricePerMillion !== null) {
    segments.push(`${labels.input} ${formatCustomModelPriceInput(inputPricePerMillion)}`);
  }
  if (cacheHitPricePerMillion !== null) {
    segments.push(`${labels.cacheHit} ${formatCustomModelPriceInput(cacheHitPricePerMillion)}`);
  }
  if (outputPricePerMillion !== null) {
    segments.push(`${labels.output} ${formatCustomModelPriceInput(outputPricePerMillion)}`);
  }

  if (segments.length === 0) {
    return null;
  }

  return `${getCustomModelPriceCurrencyLabel(priceCurrency, labels)} / ${labels.perMillionTokens} ${segments.join(labels.separator)}`;
}

function getCustomModelPriceCurrencyLabel(
  priceCurrency: string,
  labels: CustomModelPricingSummaryLabels,
): string {
  const normalizedCurrency = priceCurrency.trim().toUpperCase();
  if (!normalizedCurrency) {
    return labels.currency[DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY] ?? DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY;
  }

  return labels.currency[normalizedCurrency] ?? normalizedCurrency;
}

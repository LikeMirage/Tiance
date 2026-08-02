import type { TranslationKey } from "../../../shared/i18n";
import { getModelCapabilityLabel } from "../../../shared/i18n/modelCapabilityLabels";
import type { CustomModelPricingSummaryLabels } from "../model/customModelPricing";
import type { ProviderUsageMetricKey } from "../model/providerUsageFormat";
import type { CustomModelCapabilityTag } from "../model/useProviderModelManagement";

type TranslationParams = Record<string, string | number>;
type Translate = (key: TranslationKey, params?: TranslationParams) => string;

export function getCustomModelCapabilityLabel(
  tag: CustomModelCapabilityTag,
  t: Translate,
) {
  return getModelCapabilityLabel(tag, t);
}

export function getProviderUsageMetricLabels(t: Translate): Record<ProviderUsageMetricKey, string> {
  return {
    cacheHit: t("providerCanvas.usage.metrics.cacheHit"),
    cost: t("providerCanvas.usage.metrics.cost"),
    input: t("providerCanvas.usage.metrics.input"),
    output: t("providerCanvas.usage.metrics.output"),
    total: t("providerCanvas.usage.metrics.total"),
  };
}

export function getCustomModelPriceCurrencyOptions(t: Translate) {
  return [
    {
      label: t("providerCanvas.modelManagement.currency.cny"),
      value: "CNY",
    },
    {
      label: t("providerCanvas.modelManagement.currency.usd"),
      value: "USD",
    },
  ];
}

export function getCustomModelPricingSummaryLabels(
  t: Translate,
): CustomModelPricingSummaryLabels {
  return {
    cacheHit: t("providerCanvas.usage.metrics.cacheHit"),
    currency: {
      CNY: t("providerCanvas.modelManagement.currency.cny"),
      USD: t("providerCanvas.modelManagement.currency.usd"),
    },
    input: t("providerCanvas.usage.metrics.input"),
    output: t("providerCanvas.usage.metrics.output"),
    perMillionTokens: t("providerCanvas.modelManagement.pricing.perMillionTokens"),
    separator: t("providerCanvas.modelManagement.pricing.separator"),
  };
}

import { useCallback, useEffect, useRef, useState } from "react";

import type { ProviderUsageSummary } from "../../../entities/llm-usage/model/providerModelUsage";
import { subscribeLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { getProviderModelUsageSummary } from "../../../services/llm/getProviderModelUsageSummary";

export function useProviderUsageSummary(
  selectedProviderId: string | null,
  {
    isActive = true,
  }: {
    isActive?: boolean;
  } = {},
) {
  const selectedProviderIdRef = useRef(selectedProviderId);
  const [providerUsageSummary, setProviderUsageSummary] =
    useState<ProviderUsageSummary | null>(null);

  useEffect(() => {
    selectedProviderIdRef.current = selectedProviderId;
  }, [selectedProviderId]);

  const reloadProviderUsageSummary = useCallback(async (providerId: string) => {
    const response = await getProviderModelUsageSummary(providerId);
    if (selectedProviderIdRef.current !== providerId) {
      return;
    }
    setProviderUsageSummary(
      response.providers.find((provider) => provider.provider_id === providerId) ?? null,
    );
  }, []);

  useEffect(() => {
    if (!selectedProviderId) {
      setProviderUsageSummary(null);
      return;
    }
    if (!isActive) {
      return;
    }

    const providerId = selectedProviderId;
    setProviderUsageSummary(null);
    void reloadProviderUsageSummary(providerId).catch(() => {
      if (selectedProviderIdRef.current === providerId) {
        setProviderUsageSummary(null);
      }
    });
  }, [isActive, reloadProviderUsageSummary, selectedProviderId]);

  useEffect(() => {
    if (!selectedProviderId || !isActive) {
      return;
    }

    const providerId = selectedProviderId;
    const refreshUsageSummary = () => {
      void reloadProviderUsageSummary(providerId).catch(() => undefined);
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        refreshUsageSummary();
      }
    };

    const unsubscribeUsageChanged = subscribeLlmUsageChanged((detail) => {
      if (!detail.providerId || detail.providerId === providerId) {
        refreshUsageSummary();
      }
    });
    window.addEventListener("focus", refreshUsageSummary);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      unsubscribeUsageChanged();
      window.removeEventListener("focus", refreshUsageSummary);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [isActive, reloadProviderUsageSummary, selectedProviderId]);

  return {
    providerUsageSummary,
    reloadProviderUsageSummary,
  };
}

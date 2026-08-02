import { useMemo, useRef, useState } from "react";

import type { DiscoveredModelEntry } from "../../../entities/llm-provider/model/discoveredModel";
import { getProviderCloudModels } from "../../../services/llm/getProviderCloudModels";
import { refreshProviderCloudModels } from "../../../services/llm/refreshProviderCloudModels";

type DiscoveryState = "idle" | "loading" | "ready" | "error" | "needs_api_key";

type ProviderDiscoveryBucket = {
  cacheDiscoveredAt: string | null;
  error: string | null;
  items: DiscoveredModelEntry[];
  state: DiscoveryState;
  visible: boolean;
};

type DiscoverSelectedModelsInput = {
  providerId: string;
};

export interface UseProviderModelDiscoveryResult {
  cacheDiscoveredAt: string | null;
  error: string | null;
  loadSelectedModels: (input: DiscoverSelectedModelsInput) => Promise<void>;
  refreshSelectedModels: () => Promise<void>;
  items: DiscoveredModelEntry[];
  state: DiscoveryState;
  visible: boolean;
}

const EMPTY_BUCKET: ProviderDiscoveryBucket = {
  cacheDiscoveredAt: null,
  error: null,
  items: [],
  state: "idle",
  visible: false,
};

export function useProviderModelDiscovery(
  selectedProviderId: string | null,
): UseProviderModelDiscoveryResult {
  const [buckets, setBuckets] = useState<Record<string, ProviderDiscoveryBucket>>({});
  const requestVersionsRef = useRef<Record<string, number>>({});

  const selectedBucket = useMemo(() => {
    if (!selectedProviderId) {
      return EMPTY_BUCKET;
    }

    return buckets[selectedProviderId] ?? EMPTY_BUCKET;
  }, [buckets, selectedProviderId]);

  const loadSelectedModels = async (input: DiscoverSelectedModelsInput) => {
    const requestVersion = nextRequestVersion(requestVersionsRef.current, input.providerId);
    setLoadingBucket(input.providerId);

    try {
      const cachedResponse = await getProviderCloudModels(input.providerId);
      if (!isLatestRequest(requestVersionsRef.current, input.providerId, requestVersion)) {
        return;
      }

      if (cachedResponse.has_cache) {
        setReadyBucket(input.providerId, {
          cacheDiscoveredAt: cachedResponse.discovered_at,
          items: cachedResponse.items,
        });
        return;
      }

      const refreshedResponse = await refreshProviderCloudModels(input.providerId);
      if (!isLatestRequest(requestVersionsRef.current, input.providerId, requestVersion)) {
        return;
      }

      setReadyBucket(input.providerId, {
        cacheDiscoveredAt: refreshedResponse.discovered_at,
        items: refreshedResponse.items,
      });
    } catch (error) {
      if (!isLatestRequest(requestVersionsRef.current, input.providerId, requestVersion)) {
        return;
      }

      setErrorBucket(input.providerId, error);
    }
  };

  const refreshSelectedModels = async () => {
    if (!selectedProviderId) {
      return;
    }

    const requestVersion = nextRequestVersion(requestVersionsRef.current, selectedProviderId);
    setLoadingBucket(selectedProviderId);

    try {
      const response = await refreshProviderCloudModels(selectedProviderId);
      if (!isLatestRequest(requestVersionsRef.current, selectedProviderId, requestVersion)) {
        return;
      }

      setReadyBucket(selectedProviderId, {
        cacheDiscoveredAt: response.discovered_at,
        items: response.items,
      });
    } catch (error) {
      if (!isLatestRequest(requestVersionsRef.current, selectedProviderId, requestVersion)) {
        return;
      }

      setErrorBucket(selectedProviderId, error);
    }
  };

  const setLoadingBucket = (providerId: string) => {
    setBuckets((current) => ({
      ...current,
      [providerId]: {
        cacheDiscoveredAt: current[providerId]?.cacheDiscoveredAt ?? null,
        error: null,
        items: current[providerId]?.items ?? [],
        state: "loading",
        visible: true,
      },
    }));
  };

  const setReadyBucket = (
    providerId: string,
    payload: {
      cacheDiscoveredAt: string | null;
      items: DiscoveredModelEntry[];
    },
  ) => {
    setBuckets((current) => ({
      ...current,
      [providerId]: {
        cacheDiscoveredAt: payload.cacheDiscoveredAt,
        error: null,
        items: payload.items,
        state: "ready",
        visible: true,
      },
    }));
  };

  const setErrorBucket = (providerId: string, error: unknown) => {
    const message = error instanceof Error ? error.message : "模型拉取失败。";
    setBuckets((current) => ({
      ...current,
      [providerId]: {
        cacheDiscoveredAt: current[providerId]?.cacheDiscoveredAt ?? null,
        error: message,
        items: current[providerId]?.items ?? [],
        state: isApiKeyMissingError(message) ? "needs_api_key" : "error",
        visible: true,
      },
    }));
  };

  return {
    cacheDiscoveredAt: selectedBucket.cacheDiscoveredAt,
    error: selectedBucket.error,
    items: selectedBucket.items,
    loadSelectedModels,
    refreshSelectedModels,
    state: selectedBucket.state,
    visible: selectedBucket.visible,
  };
}

function nextRequestVersion(
  requestVersions: Record<string, number>,
  providerId: string,
) {
  const nextVersion = (requestVersions[providerId] ?? 0) + 1;
  requestVersions[providerId] = nextVersion;
  return nextVersion;
}

function isLatestRequest(
  requestVersions: Record<string, number>,
  providerId: string,
  requestVersion: number,
) {
  return requestVersions[providerId] === requestVersion;
}

function isApiKeyMissingError(message: string) {
  const normalizedMessage = message.toLowerCase();
  return normalizedMessage.includes("api key") || normalizedMessage.includes("api_key");
}

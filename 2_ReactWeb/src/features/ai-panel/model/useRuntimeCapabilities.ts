import { useEffect, useState } from "react";

import type { DsLlmRuntimeCapabilities } from "../../../entities/llm-runtime/model/runtimeCapabilities";
import { getRuntimeCapabilities } from "../../../services/llm/getRuntimeCapabilities";
import type { ChatModelOption } from "./chatModelOption";

type RuntimeCapabilitiesState = {
  capabilities: DsLlmRuntimeCapabilities;
  modelKey: string;
};

export function useRuntimeCapabilities(
  activeModel: ChatModelOption | null,
  activeModelKey: string | null,
) {
  const [runtimeCapabilitiesState, setRuntimeCapabilitiesState] =
    useState<RuntimeCapabilitiesState | null>(null);

  useEffect(() => {
    if (!activeModel || !activeModelKey) {
      setRuntimeCapabilitiesState(null);
      return undefined;
    }

    let disposed = false;
    void getRuntimeCapabilities(activeModel.providerId, activeModel.modelId)
      .then((capabilities) => {
        if (!disposed) {
          setRuntimeCapabilitiesState({ modelKey: activeModelKey, capabilities });
        }
      })
      .catch(() => {
        if (!disposed) {
          setRuntimeCapabilitiesState(null);
        }
      });

    return () => {
      disposed = true;
    };
  }, [activeModel, activeModelKey]);

  return runtimeCapabilitiesState?.modelKey === activeModelKey
    ? runtimeCapabilitiesState.capabilities
    : null;
}

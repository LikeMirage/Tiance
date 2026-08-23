import { useEffect, useState } from "react";

import type { ModelManagementMode } from "./modelManagementTypes";

export function useModelManagementMode(selectedProviderId: string | null) {
  const [activeMode, setActiveMode] = useState<ModelManagementMode>("added");

  useEffect(() => {
    setActiveMode("added");
  }, [selectedProviderId]);

  const selectMode = (nextMode: ModelManagementMode) => {
    if (activeMode === nextMode) return;
    setActiveMode(nextMode);
  };

  return {
    activeMode,
    selectAddedMode: () => selectMode("added"),
    selectCloudMode: () => selectMode("cloud"),
    selectCustomMode: () => selectMode("custom"),
  };
}

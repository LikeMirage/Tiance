import { useEffect, useState } from "react";

import { resolveTransitionDirection } from "./modelManagementRules";
import type {
  ModelManagementMode,
  ModelManagementTransitionDirection,
} from "./modelManagementTypes";

export function useModelManagementMode(selectedProviderId: string | null) {
  const [activeMode, setActiveMode] = useState<ModelManagementMode>("added");
  const [transitionDirection, setTransitionDirection] =
    useState<ModelManagementTransitionDirection>("none");

  useEffect(() => {
    setActiveMode("added");
    setTransitionDirection("none");
  }, [selectedProviderId]);

  const selectMode = (nextMode: ModelManagementMode) => {
    if (activeMode === nextMode) {
      setTransitionDirection("none");
      return;
    }

    setTransitionDirection(resolveTransitionDirection(activeMode, nextMode));
    setActiveMode(nextMode);
  };

  return {
    activeMode,
    selectAddedMode: () => selectMode("added"),
    selectCloudMode: () => selectMode("cloud"),
    selectCustomMode: () => selectMode("custom"),
    transitionDirection,
  };
}

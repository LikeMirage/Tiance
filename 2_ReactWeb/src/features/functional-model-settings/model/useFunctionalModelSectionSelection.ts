import { useCallback, useMemo, useState } from "react";

import { usePersistentNestedMenuSelection } from "../../../shared/model/nested-menu/usePersistentNestedMenuSelection";
import {
  functionalModelSettingsNestedMenuConfig,
  type FunctionalModelSettingsSectionId,
} from "./functionalModelSections";

const FUNCTIONAL_MODEL_GROUP_EXPANDED_STORAGE_KEY =
  "tiance.settings.functional-model-group-expanded";

export function useFunctionalModelSectionSelection(isParentActive: boolean) {
  const selection = usePersistentNestedMenuSelection({
    ...functionalModelSettingsNestedMenuConfig,
    isParentActive,
  });
  const { activeItemId, selectItemId } = selection;
  const [isSectionGroupExpanded, setIsSectionGroupExpandedState] = useState(
    readStoredSectionGroupExpanded,
  );

  const setSectionGroupExpanded = useCallback((isExpanded: boolean) => {
    setIsSectionGroupExpandedState(isExpanded);
    writeStoredSectionGroupExpanded(isExpanded);
  }, []);

  const toggleSectionGroup = useCallback(() => {
    setIsSectionGroupExpandedState((current) => {
      const next = !current;
      writeStoredSectionGroupExpanded(next);
      return next;
    });
  }, []);

  const selectSection = useCallback((sectionId: FunctionalModelSettingsSectionId) => {
    setSectionGroupExpanded(true);
    selectItemId(sectionId);
  }, [selectItemId, setSectionGroupExpanded]);

  return useMemo(() => ({
    activeSectionId: activeItemId,
    isSectionGroupOpen: isParentActive && isSectionGroupExpanded,
    selectSection,
    toggleSectionGroup,
  }), [
    activeItemId,
    isParentActive,
    isSectionGroupExpanded,
    selectSection,
    toggleSectionGroup,
  ]);
}

function readStoredSectionGroupExpanded() {
  if (typeof window === "undefined") return true;

  try {
    const stored = window.localStorage.getItem(FUNCTIONAL_MODEL_GROUP_EXPANDED_STORAGE_KEY);
    if (stored === "false") return false;
    if (stored === "true") return true;
    return true;
  } catch {
    return true;
  }
}

function writeStoredSectionGroupExpanded(isExpanded: boolean) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      FUNCTIONAL_MODEL_GROUP_EXPANDED_STORAGE_KEY,
      isExpanded ? "true" : "false",
    );
  } catch {
    // The menu still works for the current session when storage is unavailable.
  }
}

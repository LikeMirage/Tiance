import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { getProviderCustomModels } from "../../../services/llm/getProviderCustomModels";
import { useI18n } from "../../../shared/i18n";
import { toAddedCustomModelEntry } from "./modelManagementRules";
import type { AddedCustomModelEntry } from "./modelManagementTypes";

type UseAddedCustomModelsInput = {
  selectedProviderId: string | null;
  setCustomModelError: Dispatch<SetStateAction<string | null>>;
};

export function useAddedCustomModels({
  selectedProviderId,
  setCustomModelError,
}: UseAddedCustomModelsInput) {
  const { t } = useI18n();
  const [addedCustomModels, setAddedCustomModels] = useState<AddedCustomModelEntry[]>([]);
  const [isLoadingAddedCustomModels, setIsLoadingAddedCustomModels] = useState(false);

  useEffect(() => {
    if (!selectedProviderId) {
      setAddedCustomModels([]);
      setCustomModelError(null);
      setIsLoadingAddedCustomModels(false);
      return;
    }

    let isStale = false;

    setAddedCustomModels([]);
    setCustomModelError(null);
    setIsLoadingAddedCustomModels(true);

    getProviderCustomModels(selectedProviderId)
      .then((customModelsResponse) => {
        if (isStale) {
          return;
        }

        setAddedCustomModels(customModelsResponse.items.map(toAddedCustomModelEntry));
      })
      .catch((error: unknown) => {
        if (isStale) {
          return;
        }

        setCustomModelError(
          error instanceof Error
            ? error.message
            : t("providerCanvas.modelManagement.added.loadFailed"),
        );
      })
      .finally(() => {
        if (isStale) {
          return;
        }

        setIsLoadingAddedCustomModels(false);
      });

    return () => {
      isStale = true;
    };
  }, [selectedProviderId, setCustomModelError, t]);

  return {
    addedCustomModels,
    isLoadingAddedCustomModels,
    setAddedCustomModels,
  };
}

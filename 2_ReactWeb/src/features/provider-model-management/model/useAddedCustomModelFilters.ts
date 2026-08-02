import { useMemo, useState } from "react";

import { matchesAddedModelFilters } from "./modelManagementRules";
import type {
  AddedCustomModelEntry,
  AddedModelCategoryFilter,
} from "./modelManagementTypes";

type UseAddedCustomModelFiltersInput = {
  addedCustomModels: AddedCustomModelEntry[];
  selectedProviderId: string | null;
};

export function useAddedCustomModelFilters({
  addedCustomModels,
  selectedProviderId,
}: UseAddedCustomModelFiltersInput) {
  const [addedModelSearchQueries, setAddedModelSearchQueries] = useState<
    Record<string, string>
  >({});
  const [addedModelCategoryFilters, setAddedModelCategoryFilters] = useState<
    Record<string, AddedModelCategoryFilter>
  >({});

  const addedModelSearchQuery = selectedProviderId
    ? (addedModelSearchQueries[selectedProviderId] ?? "")
    : "";
  const addedModelCategoryFilter = selectedProviderId
    ? (addedModelCategoryFilters[selectedProviderId] ?? "all")
    : "all";
  const filteredAddedCustomModels = useMemo(
    () =>
      addedCustomModels.filter((model) =>
        matchesAddedModelFilters(model, {
          categoryFilter: addedModelCategoryFilter,
          searchQuery: addedModelSearchQuery,
        }),
      ),
    [addedCustomModels, addedModelCategoryFilter, addedModelSearchQuery],
  );

  const updateAddedModelSearchQuery = (value: string) => {
    if (!selectedProviderId) {
      return;
    }

    setAddedModelSearchQueries((current) => {
      if ((current[selectedProviderId] ?? "") === value) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: value,
      };
    });
  };

  const selectAddedModelCategoryFilter = (filter: AddedModelCategoryFilter) => {
    if (!selectedProviderId) {
      return;
    }

    setAddedModelCategoryFilters((current) => {
      if ((current[selectedProviderId] ?? "all") === filter) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: filter,
      };
    });
  };

  return {
    addedModelCategoryFilter,
    addedModelSearchQuery,
    filteredAddedCustomModels,
    selectAddedModelCategoryFilter,
    updateAddedModelSearchQuery,
  };
}

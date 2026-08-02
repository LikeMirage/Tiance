import type { LlmModelPickerOption } from "./llmModelPickerOption";

export type LlmModelProviderGroup<
  TModel extends LlmModelPickerOption = LlmModelPickerOption,
> = {
  models: TModel[];
  providerId: string;
  providerLabel: string;
};

export function groupLlmModelsByProvider<TModel extends LlmModelPickerOption>(
  models: readonly TModel[],
): LlmModelProviderGroup<TModel>[] {
  const groups = new Map<string, LlmModelProviderGroup<TModel>>();

  for (const model of models) {
    const existingGroup = groups.get(model.providerId);
    if (existingGroup) {
      existingGroup.models.push(model);
      continue;
    }

    groups.set(model.providerId, {
      models: [model],
      providerId: model.providerId,
      providerLabel: model.providerLabel,
    });
  }

  return Array.from(groups.values());
}

export function filterLlmModelProviderGroups<
  TModel extends LlmModelPickerOption,
>(
  groups: readonly LlmModelProviderGroup<TModel>[],
  searchQuery: string,
): LlmModelProviderGroup<TModel>[] {
  const normalizedQuery = normalizeLlmModelSearchText(searchQuery);
  if (!normalizedQuery) {
    return cloneProviderGroups(groups);
  }

  return groups.flatMap((group) => {
    const providerMatches = valueMatchesQuery(group.providerId, normalizedQuery)
      || valueMatchesQuery(group.providerLabel, normalizedQuery);
    const models = providerMatches
      ? group.models
      : group.models.filter((model) => modelMatchesNormalizedQuery(model, normalizedQuery));

    return models.length > 0
      ? [{ ...group, models: [...models] }]
      : [];
  });
}

export function modelMatchesLlmModelSearch(
  model: LlmModelPickerOption,
  searchQuery: string,
): boolean {
  const normalizedQuery = normalizeLlmModelSearchText(searchQuery);
  return !normalizedQuery || modelMatchesNormalizedQuery(model, normalizedQuery);
}

export function normalizeLlmModelSearchText(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function cloneProviderGroups<TModel extends LlmModelPickerOption>(
  groups: readonly LlmModelProviderGroup<TModel>[],
): LlmModelProviderGroup<TModel>[] {
  return groups.map((group) => ({ ...group, models: [...group.models] }));
}

function modelMatchesNormalizedQuery(
  model: LlmModelPickerOption,
  normalizedQuery: string,
): boolean {
  const searchableValues = [
    model.providerId,
    model.providerLabel,
    model.modelId,
    model.modelLabel,
    model.familyGroup,
    model.source,
    ...(model.capabilityTags ?? []),
  ].filter((value): value is string => Boolean(value));

  return valueMatchesQuery(searchableValues.join(" "), normalizedQuery);
}

function valueMatchesQuery(value: string, normalizedQuery: string): boolean {
  return normalizeLlmModelSearchText(value).includes(normalizedQuery);
}

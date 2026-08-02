export type LlmModelCatalogChangedEventDetail = {
  modelId?: string | null;
  providerId?: string | null;
};

const LLM_MODEL_CATALOG_CHANGED_EVENT = "tiance:llm-model-catalog-changed";

export function emitLlmModelCatalogChanged(
  detail: LlmModelCatalogChangedEventDetail = {},
) {
  window.dispatchEvent(
    new CustomEvent<LlmModelCatalogChangedEventDetail>(
      LLM_MODEL_CATALOG_CHANGED_EVENT,
      { detail },
    ),
  );
}

export function subscribeLlmModelCatalogChanged(
  listener: (detail: LlmModelCatalogChangedEventDetail) => void,
) {
  const handler = (event: Event) => {
    listener((event as CustomEvent<LlmModelCatalogChangedEventDetail>).detail ?? {});
  };

  window.addEventListener(LLM_MODEL_CATALOG_CHANGED_EVENT, handler);
  return () => window.removeEventListener(LLM_MODEL_CATALOG_CHANGED_EVENT, handler);
}

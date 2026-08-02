export type LlmUsageChangedEventDetail = {
  providerId?: string | null;
  modelId?: string | null;
};

const LLM_USAGE_CHANGED_EVENT = "tiance:llm-usage-changed";

export function emitLlmUsageChanged(detail: LlmUsageChangedEventDetail = {}) {
  window.dispatchEvent(
    new CustomEvent<LlmUsageChangedEventDetail>(LLM_USAGE_CHANGED_EVENT, {
      detail,
    }),
  );
}

export function subscribeLlmUsageChanged(
  listener: (detail: LlmUsageChangedEventDetail) => void,
) {
  const handler = (event: Event) => {
    listener((event as CustomEvent<LlmUsageChangedEventDetail>).detail ?? {});
  };

  window.addEventListener(LLM_USAGE_CHANGED_EVENT, handler);
  return () => window.removeEventListener(LLM_USAGE_CHANGED_EVENT, handler);
}

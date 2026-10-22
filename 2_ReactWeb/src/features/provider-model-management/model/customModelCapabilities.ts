export type CustomModelCapabilityTag =
  | "reasoning"
  | "vision"
  | "function_calling"
  | "embedding"
  | "rerank"
  | "speech_to_text"
  | "tts"
  | "image_generation"
  | "video_generation";

export const CUSTOM_MODEL_CAPABILITY_OPTIONS: Array<{
  value: CustomModelCapabilityTag;
}> = [
  { value: "reasoning" },
  { value: "vision" },
  { value: "function_calling" },
  { value: "embedding" },
  { value: "rerank" },
  { value: "speech_to_text" },
  { value: "tts" },
  { value: "image_generation" },
  { value: "video_generation" },
];

const SUPPORTED_CUSTOM_MODEL_CAPABILITIES = new Set<CustomModelCapabilityTag>(
  CUSTOM_MODEL_CAPABILITY_OPTIONS.map((option) => option.value),
);

export function normalizeCustomModelCapabilityTags(tags: readonly string[]) {
  const normalizedTags = tags.filter((tag): tag is CustomModelCapabilityTag =>
    SUPPORTED_CUSTOM_MODEL_CAPABILITIES.has(tag as CustomModelCapabilityTag),
  );
  return sortCustomModelCapabilities(normalizedTags);
}

export function sortCustomModelCapabilities(
  tags: CustomModelCapabilityTag[],
) {
  return tags
    .slice()
    .sort(
      (left, right) =>
        resolveCapabilityOrder(left) - resolveCapabilityOrder(right),
    );
}

function resolveCapabilityOrder(tag: CustomModelCapabilityTag) {
  const order = CUSTOM_MODEL_CAPABILITY_OPTIONS.findIndex(
    (option) => option.value === tag,
  );
  return order === -1 ? Number.MAX_SAFE_INTEGER : order;
}

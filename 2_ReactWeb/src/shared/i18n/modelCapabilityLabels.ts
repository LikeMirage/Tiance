import type { TranslationKey } from "./locales";

type TranslationParams = Record<string, string | number>;
type Translate = (key: TranslationKey, params?: TranslationParams) => string;

const MODEL_CAPABILITY_LABEL_KEYS: Readonly<Record<string, TranslationKey>> = {
  embedding: "providerCanvas.modelManagement.capabilities.embedding",
  function_calling: "providerCanvas.modelManagement.capabilities.functionCalling",
  image_generation: "providerCanvas.modelManagement.capabilities.imageGeneration",
  reasoning: "providerCanvas.modelManagement.capabilities.reasoning",
  rerank: "providerCanvas.modelManagement.capabilities.rerank",
  speech_to_text: "providerCanvas.modelManagement.capabilities.speechToText",
  tts: "providerCanvas.modelManagement.capabilities.tts",
  video_generation: "providerCanvas.modelManagement.capabilities.videoGeneration",
  vision: "providerCanvas.modelManagement.capabilities.vision",
};

export function getModelCapabilityLabel(tag: string, t: Translate) {
  const labelKey = MODEL_CAPABILITY_LABEL_KEYS[tag];
  return labelKey ? t(labelKey) : tag;
}

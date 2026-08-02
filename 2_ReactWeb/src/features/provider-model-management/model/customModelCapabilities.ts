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

export function deriveCustomModelCapabilities(
  modelId: string,
  displayName: string,
): CustomModelCapabilityTag[] {
  const searchableText = `${modelId} ${displayName}`.trim().toLowerCase();
  if (!searchableText) {
    return [];
  }

  const tags = new Set<CustomModelCapabilityTag>();
  const isRerankModel = RERANK_PATTERN.test(searchableText);
  const isEmbeddingModel =
    !isRerankModel && EMBEDDING_PATTERN.test(searchableText);
  const isImageGenerationModel =
    IMAGE_GENERATION_PATTERN.test(searchableText);
  const isVideoGenerationModel =
    !isImageGenerationModel && VIDEO_GENERATION_PATTERN.test(searchableText);
  const isSpeechToTextModel = SPEECH_TO_TEXT_PATTERN.test(searchableText);
  const isTtsModel = TTS_PATTERN.test(searchableText);
  const isSpecializedNonChatModel =
    isEmbeddingModel ||
    isImageGenerationModel ||
    isRerankModel ||
    isSpeechToTextModel ||
    isTtsModel ||
    isVideoGenerationModel;

  if (isRerankModel) {
    tags.add("rerank");
  } else if (isEmbeddingModel) {
    tags.add("embedding");
  }

  if (!isSpecializedNonChatModel && REASONING_PATTERN.test(searchableText)) {
    tags.add("reasoning");
  }

  if (isImageGenerationModel) {
    tags.add("image_generation");
  }

  if (isVideoGenerationModel) {
    tags.add("video_generation");
  }

  if (
    shouldTagVision(searchableText, {
      isEmbeddingModel,
      isImageGenerationModel,
      isRerankModel,
      isSpeechToTextModel,
      isTtsModel,
      isVideoGenerationModel,
    })
  ) {
    tags.add("vision");
  }

  if (
    shouldTagFunctionCalling(searchableText, {
      isEmbeddingModel,
      isImageGenerationModel,
      isRerankModel,
      isSpeechToTextModel,
      isTtsModel,
      isVideoGenerationModel,
    })
  ) {
    tags.add("function_calling");
  }

  if (isSpeechToTextModel) {
    tags.add("speech_to_text");
  }

  if (isTtsModel) {
    tags.add("tts");
  }

  return sortCustomModelCapabilities(Array.from(tags));
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

function shouldTagFunctionCalling(
  searchableText: string,
  flags: {
    isEmbeddingModel: boolean;
    isImageGenerationModel: boolean;
    isRerankModel: boolean;
    isSpeechToTextModel: boolean;
    isTtsModel: boolean;
    isVideoGenerationModel: boolean;
  },
) {
  if (
    isSpecializedNonChatModel(flags) ||
    FUNCTION_CALLING_EXCLUDED_PATTERN.test(searchableText)
  ) {
    return false;
  }

  return FUNCTION_CALLING_PATTERN.test(searchableText);
}

function shouldTagVision(
  searchableText: string,
  flags: {
    isEmbeddingModel: boolean;
    isImageGenerationModel: boolean;
    isRerankModel: boolean;
    isSpeechToTextModel: boolean;
    isTtsModel: boolean;
    isVideoGenerationModel: boolean;
  },
) {
  if (
    flags.isEmbeddingModel ||
    flags.isRerankModel ||
    flags.isSpeechToTextModel ||
    flags.isTtsModel ||
    VISION_EXCLUDED_PATTERN.test(searchableText)
  ) {
    return false;
  }

  if (flags.isImageGenerationModel || flags.isVideoGenerationModel) {
    return true;
  }

  return (
    VISION_PATTERN.test(searchableText) ||
    IMAGE_ENHANCEMENT_PATTERN.test(searchableText)
  );
}

function isSpecializedNonChatModel(flags: {
  isEmbeddingModel: boolean;
  isImageGenerationModel: boolean;
  isRerankModel: boolean;
  isSpeechToTextModel: boolean;
  isTtsModel: boolean;
  isVideoGenerationModel: boolean;
}) {
  return (
    flags.isEmbeddingModel ||
    flags.isImageGenerationModel ||
    flags.isRerankModel ||
    flags.isSpeechToTextModel ||
    flags.isTtsModel ||
    flags.isVideoGenerationModel
  );
}

const EMBEDDING_PATTERN =
  /(?:^|[/:_\s.-])(?:text-|embed(?:ding)?|embeddings|bge-|bge|e5-|e5|llm2vec|retrieval|uae-|uae|gte-|gte|jina-clip|jina-embeddings?|voyage-|voyage|m3e)(?:$|[/:_\s.-])/i;
const RERANK_PATTERN =
  /(?:rerank|re-rank|re-ranker|re-ranking|reranker|retrieval|retriever)/i;
const REASONING_PATTERN =
  /^(?!.*-non-reasoning\b).*(?:\bo\d+(?:-[\w-]+)?\b|\breason(?:er|ing)?\b|\bthink(?:ing)?\b|-[rR]\d+\b|\bqwq(?:-[\w-]+)?\b|\bqvq(?:-[\w-]+)?\b|\bhunyuan-(?:t1|a13b)(?:-[\w-]+)?\b|\bglm-(?:zero-preview|z1|4\.[567]|5)(?:-[\w-]+)?\b|\bgrok-(?:3-mini|4|4-fast)(?:-[\w-]+)?\b|\bgpt-5(?:[\w.-]+)?\b|\bdeepseek-(?:r1|reasoner|v3(?:[.-]\d[\w.-]*)?|chat(?:-v3\.1)?|v3\.2-speciale)\b|\bclaude-(?:3[.-]7.*sonnet|(?:haiku|sonnet|opus)-4(?:[.-]\d+)?)(?:[@\-:][\w\-:]+)?\b|\bgemini-(?:2\.5|3(?:\.\d+)?|flash-latest|pro-latest|flash-lite-latest)(?:-[\w-]+)*\b|\bqwen(?:3(?:\.[5-9])?|3-max|max|plus|flash|turbo)(?:-[\w-]+)?\b|\bqwen3-\d[\w.-]*\b|\bperplexity.*reasoning\b|\bsonar-deep-research\b|\bstep-(?:3|r1-v-mini)\b|\bring-(?:1t|mini|flash)\b|\bminimax-m[12](?:\.1)?(?:-[\w-]+)?\b|\bmimo-v2-(?:flash|pro|omni)\b|\bbaichuan-m[23]\b|\bkimi-(?:k2-thinking(?:-turbo)?|k2\.5)(?:-\w+)?\b|\bmagistral\b|\bpangu-pro-moe\b|\bseed-oss\b|\bgemma-?4\b).*$/i;
const VISION_MODEL_PATTERNS = [
  "llava",
  "moondream",
  "minicpm",
  "gemini-1\\.5",
  "gemini-2\\.0",
  "gemini-2\\.5",
  "gemini-3(?:\\.\\d)?-(?:flash|pro)(?:-preview)?",
  "gemini-(?:flash|pro|flash-lite)-latest",
  "gemini-exp",
  "claude-3",
  "claude-haiku-4",
  "claude-sonnet-4",
  "claude-opus-4",
  "vision",
  "visual",
  "multimodal",
  "omni",
  "(?:^|[/:_\\s.-])vl(?:$|[/:_\\s.-])",
  "glm-4(?:\\.\\d+)?v(?:-[\\w-]+)?",
  "glm-5v-turbo",
  "qwen-vl",
  "qwen2-vl",
  "qwen2\\.5-vl",
  "qwen3-vl",
  "qwen3\\.[5-9](?:-[\\w-]+)?",
  "qwen2\\.5-omni",
  "qwen3-omni(?:-[\\w-]+)?",
  "qwen-omni(?:-[\\w-]+)?",
  "qvq",
  "internvl2",
  "grok-vision-beta",
  "grok-4(?:-[\\w-]+)?",
  "pixtral",
  "gpt-4(?:-[\\w-]+)",
  "gpt-4\\.1(?:-[\\w-]+)?",
  "gpt-4o(?:-[\\w-]+)?",
  "gpt-4\\.5(?:-[\\w-]+)",
  "gpt-5(?:-[\\w-]+)?",
  "chatgpt-4o(?:-[\\w-]+)?",
  "o1(?:-[\\w-]+)?",
  "o3(?:-[\\w-]+)?",
  "o4(?:-[\\w-]+)?",
  "deepseek-vl(?:[\\w-]+)?",
  "kimi-k2\\.5",
  "kimi-latest",
  "kimi-thinking-preview",
  "kimi-vl-a3b-thinking(?:-[\\w-]+)?",
  "gemma-?[3-4](?:[-.\\w]+)?",
  "gemma3(?:[-:\\w]+)?",
  "doubao-seed-1[.-][68](?:-[\\w-]+)?",
  "doubao-seed-2[.-]0(?:-[\\w-]+)?",
  "doubao-seed-code(?:-[\\w-]+)?",
  "llama-guard-4(?:-[\\w-]+)?",
  "llama-4(?:-[\\w-]+)?",
  "step-1o(?:.*vision)?",
  "step-1v(?:-[\\w-]+)?",
  "mistral-large-(?:2512|latest)",
  "mistral-medium-(?:2508|latest)",
  "mistral-small-(?:2506|latest)",
  "mimo-v2-omni(?:-[\\w-]+)?",
] as const;
const VISION_EXCLUDED_MODEL_PATTERNS = [
  "gpt-4-\\d+-preview",
  "gpt-4-turbo-preview",
  "gpt-4-32k",
  "gpt-4-\\d+",
  "o1-mini",
  "o3-mini",
  "o1-preview",
  "aidc-ai\\/marco-o1",
] as const;
const VISION_PATTERN = new RegExp(
  `\\b(?:${VISION_MODEL_PATTERNS.join("|")})\\b`,
  "i",
);
const VISION_EXCLUDED_PATTERN = new RegExp(
  `\\b(?:${VISION_EXCLUDED_MODEL_PATTERNS.join("|")})\\b`,
  "i",
);
const FUNCTION_CALLING_MODEL_PATTERNS = [
  "function[-_\\s]?calling",
  "tool[-_\\s]?calling",
  "tool[-_\\s]?calls?",
  "structured[-_\\s]?outputs?",
  "chatgpt-4o(?:-[\\w-]+)?",
  "gpt-4o(?:-[\\w-]+)?",
  "gpt-4(?:\\.[\\w-]+)?(?:-[\\w-]+)?",
  "gpt-5(?:-[\\w-]+)?",
  "gpt-oss(?:-[\\w-]+)?",
  "o[134](?:-[\\w-]+)?",
  "claude(?:-[\\w-]+)?",
  "qwen(?:\\d+(?:\\.\\d+)?)?(?:[-_.\\w]+)?",
  "hunyuan(?:[-_.\\w]+)?",
  "deepseek(?:[-_.\\w]+)?",
  "gemini(?:[-_.\\w]+)?",
  "gemma-?4(?:[-_.\\w]+)?",
  "glm-(?:4|4\\.5|4\\.7|5)(?:[-_.\\w]+)?",
  "glm-5v-turbo",
  "grok-(?:3|4)(?:[-_.\\w]+)?",
  "doubao-seed(?:[-_.\\w]+)?",
  "kimi-k2(?:[-_.\\w]+)?",
  "learnlm(?:-[\\w-]+)?",
  "ling-\\w+(?:-[\\w-]+)?",
  "ring-\\w+(?:-[\\w-]+)?",
  "moonshot(?:[-_.\\w]+)?",
  "mistral(?:[-_.\\w]+)?",
  "mixtral(?:[-_.\\w]+)?",
  "llama-?3(?:[-_.\\w]+)?",
  "command-r(?:[-_.\\w]+)?",
  "minimax(?:[-_.\\w]+)?",
  "ernie(?:[-_.\\w]+)?",
  "yi(?:[-_.\\w]+)?",
  "step(?:[-_.\\w]+)?",
] as const;
const FUNCTION_CALLING_EXCLUDED_MODEL_PATTERNS = [
  "aqa(?:-[\\w-]+)?",
  "imagen(?:-[\\w-]+)?",
  "o1-mini",
  "o1-preview",
  "aidc-ai\\/marco-o1",
  "gemini-1(?:\\.[\\w-]+)?",
  "qwen-mt(?:-[\\w-]+)?",
  "gpt-5-chat(?:-[\\w-]+)?",
  "glm-4\\.5v",
  "gemini-2\\.5-flash-image(?:-[\\w-]+)?",
  "gemini-2\\.0-flash-preview-image-generation",
  "gemini-3(?:\\.\\d+)?-pro-image(?:-[\\w-]+)?",
  "deepseek-v3\\.2-speciale",
] as const;
const FUNCTION_CALLING_PATTERN = new RegExp(
  `\\b(?:${FUNCTION_CALLING_MODEL_PATTERNS.join("|")})\\b`,
  "i",
);
const FUNCTION_CALLING_EXCLUDED_PATTERN = new RegExp(
  `\\b(?:${FUNCTION_CALLING_EXCLUDED_MODEL_PATTERNS.join("|")})\\b`,
  "i",
);
const SPEECH_TO_TEXT_PATTERN =
  /(?:speech[-_\s]?to[-_\s]?text|asr|transcri(?:be|ption)|whisper|paraformer)/i;
const TTS_PATTERN =
  /(?:tts|text[-_\s]?to[-_\s]?speech|speech[-_\s]?synthesis|cosyvoice|kokoro|fish[-_\s]?speech)/i;
const IMAGE_ENHANCEMENT_PATTERN =
  /(?:grok-2-image(?:-[\w-]+)?|qwen-image-edit|gpt-image-1|gemini-2\.5-flash-image(?:-[\w-]+)?|gemini-2\.0-flash-preview-image-generation|gemini-3(?:\.\d+)?-(?:flash|pro)-image(?:-[\w-]+)?)/i;
const IMAGE_GENERATION_PATTERN =
  /(?:image[-_\s]?generation|text[-_\s]?to[-_\s]?image|gemini-2\.0-flash-exp(?:-[\w-]+)?|gemini-2\.5-flash-image(?:-[\w-]+)?|gemini-2\.0-flash-preview-image-generation|gemini-3(?:\.\d+)?-(?:flash|pro)-image(?:-[\w-]+)?|gpt[-_\s]?image|dall[-_\s]?e|grok-2-image|imagen|seedream|cogview|flux|stable[-_\s]?diffusion|stabilityai|(?:^|[/:_\s.-])sd-[\w-]+|sdxl|qwen-image|janus|midjourney|(?:^|[/:_\s.-])mj-[\w-]+|z-image|longcat-image|hunyuanimage|kandinsky|kolors)/i;
const VIDEO_GENERATION_PATTERN =
  /(?:video[-_\s]?generation|text[-_\s]?to[-_\s]?video|image[-_\s]?to[-_\s]?video|sora|veo|seedance|wan(?:$|[/:_\s.-])|hailuo|kling|runway|pika)/i;

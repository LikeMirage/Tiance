"""Name-only fallback shared by manual model entry and provider discovery."""

import re

from app.domain.llm.model_capability_tags import ordered_capability_tags

EMBEDDING_PATTERN = re.compile('(?:^|[/:_\\s.-])(?:text-|embed(?:ding)?|embeddings|bge-|bge|e5-|e5|llm2vec|retrieval|uae-|uae|gte-|gte|jina-clip|jina-embeddings?|voyage-|voyage|m3e)(?:$|[/:_\\s.-])', re.IGNORECASE)
RERANK_PATTERN = re.compile('(?:rerank|re-rank|re-ranker|re-ranking|reranker|retrieval|retriever)', re.IGNORECASE)
REASONING_PATTERN = re.compile('^(?!.*-non-reasoning\\b).*(?:\\bo\\d+(?:-[\\w-]+)?\\b|\\breason(?:er|ing)?\\b|\\bthink(?:ing)?\\b|-[rR]\\d+\\b|\\bqwq(?:-[\\w-]+)?\\b|\\bqvq(?:-[\\w-]+)?\\b|\\bhunyuan-(?:t1|a13b)(?:-[\\w-]+)?\\b|\\bglm-(?:zero-preview|z1|4\\.[567]|5)(?:-[\\w-]+)?\\b|\\bgrok-(?:3-mini|4|4-fast)(?:-[\\w-]+)?\\b|\\bgpt-5(?:[\\w.-]+)?\\b|\\bdeepseek-(?:flash|v4[.]1-flash|r1|reasoner|v3(?:[.-]\\d[\\w.-]*)?|chat(?:-v3\\.1)?|v3\\.2-speciale)\\b|\\bclaude-(?:3[.-]7.*sonnet|(?:haiku|sonnet|opus)-4(?:[.-]\\d+)?)(?:[@\\-:][\\w\\-:]+)?\\b|\\bgemini-(?:2\\.5|3(?:\\.\\d+)?|flash-latest|pro-latest|flash-lite-latest)(?:-[\\w-]+)*\\b|\\bqwen(?:3(?:\\.[5-9])?|3-max|max|plus|flash|turbo)(?:-[\\w-]+)?\\b|\\bqwen3-\\d[\\w.-]*\\b|\\bperplexity.*reasoning\\b|\\bsonar-deep-research\\b|\\bstep-(?:3|r1-v-mini)\\b|\\bring-(?:1t|mini|flash)\\b|\\bminimax-m[12](?:\\.1)?(?:-[\\w-]+)?\\b|\\bmimo-v2-(?:flash|pro|omni)\\b|\\bbaichuan-m[23]\\b|\\bkimi-(?:k2-thinking(?:-turbo)?|k2\\.5)(?:-\\w+)?\\b|\\bmagistral\\b|\\bpangu-pro-moe\\b|\\bseed-oss\\b|\\bgemma-?4\\b).*$', re.IGNORECASE)
SPEECH_TO_TEXT_PATTERN = re.compile('(?:speech[-_\\s]?to[-_\\s]?text|asr|transcri(?:be|ption)|whisper|paraformer)', re.IGNORECASE)
TTS_PATTERN = re.compile('(?:tts|text[-_\\s]?to[-_\\s]?speech|speech[-_\\s]?synthesis|cosyvoice|kokoro|fish[-_\\s]?speech)', re.IGNORECASE)
IMAGE_ENHANCEMENT_PATTERN = re.compile('(?:grok-2-image(?:-[\\w-]+)?|qwen-image-edit|gpt-image-1|gemini-2\\.5-flash-image(?:-[\\w-]+)?|gemini-2\\.0-flash-preview-image-generation|gemini-3(?:\\.\\d+)?-(?:flash|pro)-image(?:-[\\w-]+)?)', re.IGNORECASE)
IMAGE_GENERATION_PATTERN = re.compile('(?:image[-_\\s]?generation|text[-_\\s]?to[-_\\s]?image|gemini-2\\.0-flash-exp(?:-[\\w-]+)?|gemini-2\\.5-flash-image(?:-[\\w-]+)?|gemini-2\\.0-flash-preview-image-generation|gemini-3(?:\\.\\d+)?-(?:flash|pro)-image(?:-[\\w-]+)?|gpt[-_\\s]?image|dall[-_\\s]?e|grok-2-image|imagen|seedream|cogview|flux|stable[-_\\s]?diffusion|stabilityai|(?:^|[/:_\\s.-])sd-[\\w-]+|sdxl|qwen-image|janus|midjourney|(?:^|[/:_\\s.-])mj-[\\w-]+|z-image|longcat-image|hunyuanimage|kandinsky|kolors)', re.IGNORECASE)
VIDEO_GENERATION_PATTERN = re.compile('(?:video[-_\\s]?generation|text[-_\\s]?to[-_\\s]?video|image[-_\\s]?to[-_\\s]?video|sora|veo|seedance|wan(?:$|[/:_\\s.-])|hailuo|kling|runway|pika)', re.IGNORECASE)

VISION_PATTERN = re.compile(
    r"\b(?:" + "|".join((
        'llava',
        'moondream',
        'minicpm',
        'gemini-1\\.5',
        'gemini-2\\.0',
        'gemini-2\\.5',
        'gemini-3(?:\\.\\d)?-(?:flash|pro)(?:-preview)?',
        'gemini-(?:flash|pro|flash-lite)-latest',
        'gemini-exp',
        'claude-3',
        'claude-haiku-4',
        'claude-sonnet-4',
        'claude-opus-4',
        'vision',
        'visual',
        'multimodal',
        'omni',
        '(?:^|[/:_\\s.-])vl(?:$|[/:_\\s.-])',
        'glm-4(?:\\.\\d+)?v(?:-[\\w-]+)?',
        'glm-5v-turbo',
        'qwen-vl',
        'qwen2-vl',
        'qwen2\\.5-vl',
        'qwen3-vl',
        'qwen3\\.[5-9](?:-[\\w-]+)?',
        'qwen2\\.5-omni',
        'qwen3-omni(?:-[\\w-]+)?',
        'qwen-omni(?:-[\\w-]+)?',
        'qvq',
        'internvl2',
        'grok-vision-beta',
        'grok-4(?:-[\\w-]+)?',
        'pixtral',
        'gpt-4(?:-[\\w-]+)',
        'gpt-4\\.1(?:-[\\w-]+)?',
        'gpt-4o(?:-[\\w-]+)?',
        'gpt-4\\.5(?:-[\\w-]+)',
        'gpt-5(?:-[\\w-]+)?',
        'chatgpt-4o(?:-[\\w-]+)?',
        'o1(?:-[\\w-]+)?',
        'o3(?:-[\\w-]+)?',
        'o4(?:-[\\w-]+)?',
        'deepseek-vl(?:[\\w-]+)?',
        'kimi-k2\\.5',
        'kimi-latest',
        'kimi-thinking-preview',
        'kimi-vl-a3b-thinking(?:-[\\w-]+)?',
        'gemma-?[3-4](?:[-.\\w]+)?',
        'gemma3(?:[-:\\w]+)?',
        'doubao-seed-1[.-][68](?:-[\\w-]+)?',
        'doubao-seed-2[.-]0(?:-[\\w-]+)?',
        'doubao-seed-code(?:-[\\w-]+)?',
        'llama-guard-4(?:-[\\w-]+)?',
        'llama-4(?:-[\\w-]+)?',
        'step-1o(?:.*vision)?',
        'step-1v(?:-[\\w-]+)?',
        'mistral-large-(?:2512|latest)',
        'mistral-medium-(?:2508|latest)',
        'mistral-small-(?:2506|latest)',
        'mimo-v2-omni(?:-[\\w-]+)?',
        'deepseek-(?:flash|v4[.]1-flash)(?:$|[/:_\\s-])',
    )) + r")\b", re.IGNORECASE,
)

VISION_EXCLUDED_PATTERN = re.compile(
    r"\b(?:" + "|".join((
        'gpt-4-\\d+-preview',
        'gpt-4-turbo-preview',
        'gpt-4-32k',
        'gpt-4-\\d+',
        'o1-mini',
        'o3-mini',
        'o1-preview',
        'aidc-ai\\/marco-o1',
    )) + r")\b", re.IGNORECASE,
)

FUNCTION_CALLING_PATTERN = re.compile(
    r"\b(?:" + "|".join((
        'function[-_\\s]?calling',
        'tool[-_\\s]?calling',
        'tool[-_\\s]?calls?',
        'structured[-_\\s]?outputs?',
        'chatgpt-4o(?:-[\\w-]+)?',
        'gpt-4o(?:-[\\w-]+)?',
        'gpt-4(?:\\.[\\w-]+)?(?:-[\\w-]+)?',
        'gpt-5(?:-[\\w-]+)?',
        'gpt-oss(?:-[\\w-]+)?',
        'o[134](?:-[\\w-]+)?',
        'claude(?:-[\\w-]+)?',
        'qwen(?:\\d+(?:\\.\\d+)?)?(?:[-_.\\w]+)?',
        'hunyuan(?:[-_.\\w]+)?',
        'deepseek(?:[-_.\\w]+)?',
        'gemini(?:[-_.\\w]+)?',
        'gemma-?4(?:[-_.\\w]+)?',
        'glm-(?:4|4\\.5|4\\.7|5)(?:[-_.\\w]+)?',
        'glm-5v-turbo',
        'grok-(?:3|4)(?:[-_.\\w]+)?',
        'doubao-seed(?:[-_.\\w]+)?',
        'kimi-k2(?:[-_.\\w]+)?',
        'learnlm(?:-[\\w-]+)?',
        'ling-\\w+(?:-[\\w-]+)?',
        'ring-\\w+(?:-[\\w-]+)?',
        'moonshot(?:[-_.\\w]+)?',
        'mistral(?:[-_.\\w]+)?',
        'mixtral(?:[-_.\\w]+)?',
        'llama-?3(?:[-_.\\w]+)?',
        'command-r(?:[-_.\\w]+)?',
        'minimax(?:[-_.\\w]+)?',
        'ernie(?:[-_.\\w]+)?',
        'yi(?:[-_.\\w]+)?',
        'step(?:[-_.\\w]+)?',
    )) + r")\b", re.IGNORECASE,
)

FUNCTION_CALLING_EXCLUDED_PATTERN = re.compile(
    r"\b(?:" + "|".join((
        'aqa(?:-[\\w-]+)?',
        'imagen(?:-[\\w-]+)?',
        'o1-mini',
        'o1-preview',
        'aidc-ai\\/marco-o1',
        'gemini-1(?:\\.[\\w-]+)?',
        'qwen-mt(?:-[\\w-]+)?',
        'gpt-5-chat(?:-[\\w-]+)?',
        'glm-4\\.5v',
        'gemini-2\\.5-flash-image(?:-[\\w-]+)?',
        'gemini-2\\.0-flash-preview-image-generation',
        'gemini-3(?:\\.\\d+)?-pro-image(?:-[\\w-]+)?',
        'deepseek-v3\\.2-speciale',
    )) + r")\b", re.IGNORECASE,
)

def infer_name_capability_tags(model_id: str, display_name: str) -> tuple[str, ...]:
    text = f"{model_id} {display_name}".strip().lower()
    if not text:
        return ()
    tags = set()
    rerank = bool(RERANK_PATTERN.search(text))
    embedding = not rerank and bool(EMBEDDING_PATTERN.search(text))
    image_generation = bool(IMAGE_GENERATION_PATTERN.search(text))
    video_generation = not image_generation and bool(VIDEO_GENERATION_PATTERN.search(text))
    speech_to_text = bool(SPEECH_TO_TEXT_PATTERN.search(text))
    tts = bool(TTS_PATTERN.search(text))
    specialized = rerank or embedding or image_generation or video_generation or speech_to_text or tts
    for enabled, tag in ((rerank, "rerank"), (embedding, "embedding"),
                         (image_generation, "image_generation"), (video_generation, "video_generation"),
                         (speech_to_text, "speech_to_text"), (tts, "tts")):
        if enabled:
            tags.add(tag)
    if not specialized and REASONING_PATTERN.search(text):
        tags.add("reasoning")
    if not (embedding or rerank or speech_to_text or tts or VISION_EXCLUDED_PATTERN.search(text)):
        if image_generation or video_generation or VISION_PATTERN.search(text) or IMAGE_ENHANCEMENT_PATTERN.search(text):
            tags.add("vision")
    if not specialized and not FUNCTION_CALLING_EXCLUDED_PATTERN.search(text) and FUNCTION_CALLING_PATTERN.search(text):
        tags.add("function_calling")
    return ordered_capability_tags(tags)

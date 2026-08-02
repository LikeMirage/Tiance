import type {
  ProviderAuthScheme,
  ProviderModelDiscoveryStrategy,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";

export const PROVIDER_PROTOCOL_FAMILY_OPTIONS: readonly OptionSelectItem<ProviderProtocolFamily>[] = [
  { label: "OpenAI Chat Completions", value: "openai_compatible" },
  { label: "OpenAI Responses", value: "openai_responses" },
  { label: "Anthropic Messages", value: "anthropic_messages" },
  { label: "Gemini GenerateContent", value: "gemini_generate_content" },
];

export const PROVIDER_AUTH_SCHEME_OPTIONS: readonly OptionSelectItem<ProviderAuthScheme>[] = [
  { label: "Bearer Token", value: "bearer_token" },
  { label: "x-api-key", value: "x_api_key" },
  { label: "x-goog-api-key", value: "x_goog_api_key" },
  { label: "API Key Query", value: "api_key_query" },
];

export const PROVIDER_MODEL_DISCOVERY_STRATEGY_OPTIONS: readonly OptionSelectItem<ProviderModelDiscoveryStrategy>[] = [
  { label: "OpenAI Models", value: "openai_models" },
  { label: "Anthropic Models", value: "anthropic_models" },
  { label: "Gemini Models", value: "gemini_models" },
];

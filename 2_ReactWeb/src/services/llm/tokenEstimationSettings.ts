import { fetchJson } from "../http/httpClient";

export type TokenEstimationSettings = {
  ascii_chars_per_token: number;
  other_chars_per_token: number;
  message_overhead_tokens: number;
  image_placeholder_tokens: number;
};

export type TokenEstimationSettingsResponse = {
  settings: TokenEstimationSettings;
  default_settings: TokenEstimationSettings;
  updated_at: string | null;
};

export function getTokenEstimationSettings() {
  return fetchJson<TokenEstimationSettingsResponse>(
    "/api/llm/token-estimation-settings",
  );
}

export function saveTokenEstimationSettings(settings: TokenEstimationSettings) {
  return fetchJson<TokenEstimationSettingsResponse>(
    "/api/llm/token-estimation-settings",
    {
      body: JSON.stringify({ settings }),
      method: "PUT",
    },
  );
}

export function estimateJsonTokens(value: unknown) {
  return fetchJson<{ token_count: number }>(
    "/api/llm/token-estimation-settings/estimate-json",
    {
      body: JSON.stringify({ value }),
      method: "POST",
    },
  );
}

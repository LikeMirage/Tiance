import { fetchJson } from "../http/httpClient";

export type FunctionalModelProfileSettingsResponse = {
  default_settings?: unknown;
  has_settings: boolean;
  profile_key?: string | null;
  settings?: unknown;
  updated_at?: string | null;
  version?: number | null;
};

export function getFunctionalModelProfileSettings(profileKey: string) {
  return fetchJson<FunctionalModelProfileSettingsResponse>(
    `/api/llm/functional-model-settings/${encodeURIComponent(profileKey)}`,
  );
}

export function saveFunctionalModelProfileSettings(
  profileKey: string,
  input: {
    settings: unknown;
    version: number;
  },
) {
  return fetchJson<FunctionalModelProfileSettingsResponse>(
    `/api/llm/functional-model-settings/${encodeURIComponent(profileKey)}`,
    {
      body: JSON.stringify({
        settings: input.settings,
        version: input.version,
      }),
      method: "PUT",
    },
  );
}

import type {
  ProviderAuthScheme,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";

export type ProviderCreateFormDraft = {
  apiBaseUrl: string;
  authScheme: ProviderAuthScheme;
  displayName: string;
  protocolFamily: ProviderProtocolFamily;
};

export const EMPTY_PROVIDER_CREATE_FORM: ProviderCreateFormDraft = {
  apiBaseUrl: "",
  authScheme: "bearer_token",
  displayName: "",
  protocolFamily: "openai_compatible",
};

export function deriveProviderDisplayName(apiBaseUrl: string) {
  const normalizedUrl = apiBaseUrl.includes("://")
    ? apiBaseUrl
    : `https://${apiBaseUrl}`;

  try {
    const hostname = new URL(normalizedUrl).hostname.replace(/^www\./iu, "").trim();
    return hostname || "新供应商";
  } catch {
    return "新供应商";
  }
}

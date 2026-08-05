import type { ProviderProtocolFamily } from "../../../entities/llm-provider/model/providerCatalog";

export function completeProviderGenerationUrl(
  value: string,
  protocolFamily: ProviderProtocolFamily,
  presetUrl: string,
): string {
  const normalized = value.trim();
  if (!normalized) return normalized;

  const parsed = parseUrl(normalized);
  if (!parsed) return normalized;
  const currentSegments = pathSegments(parsed.pathname);
  if (hasGenerationEndpoint(currentSegments, protocolFamily)) {
    return normalized;
  }

  const preset = parseUrl(presetUrl);
  const presetSegments = preset ? pathSegments(preset.pathname) : [];
  const endpointIndex = findEndpointIndex(presetSegments, protocolFamily);
  const presetPrefix = endpointIndex >= 0 ? presetSegments.slice(0, endpointIndex) : [];
  const baseSegments = currentSegments.length === 0
    ? presetPrefix
    : currentSegments;
  const endpoint = endpointSegments(protocolFamily);
  const nextPath = `/${[...baseSegments, ...endpoint].join("/")}`;
  parsed.pathname = nextPath;
  return parsed.toString();
}

function parseUrl(value: string): URL | null {
  try {
    return new URL(value.includes("://") ? value : `https://${value}`);
  } catch {
    return null;
  }
}

function pathSegments(pathname: string): string[] {
  return pathname.split("/").filter(Boolean);
}

function endpointSegments(protocolFamily: ProviderProtocolFamily): string[] {
  switch (protocolFamily) {
    case "openai_compatible":
      return ["chat", "completions"];
    case "openai_responses":
      return ["responses"];
    case "anthropic_messages":
      return ["messages"];
    case "gemini_generate_content":
      return ["models", "{model}:{action}"];
  }
}

function hasGenerationEndpoint(
  segments: string[],
  protocolFamily: ProviderProtocolFamily,
): boolean {
  return findEndpointIndex(segments, protocolFamily) >= 0;
}

function findEndpointIndex(
  segments: string[],
  protocolFamily: ProviderProtocolFamily,
): number {
  if (protocolFamily === "openai_compatible") {
    return segments.length >= 2 && segments.slice(-2).join("/") === "chat/completions"
      ? segments.length - 2
      : -1;
  }
  if (protocolFamily === "gemini_generate_content") {
    return segments.length >= 2 && segments[segments.length - 2] === "models"
      && /^\{model\}:.+$/.test(segments[segments.length - 1])
      ? segments.length - 2
      : -1;
  }
  const endpoint = protocolFamily === "openai_responses" ? "responses" : "messages";
  return segments.at(-1) === endpoint ? segments.length - 1 : -1;
}

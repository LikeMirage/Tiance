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
  const baseSegments = stripGenerationEndpoint(currentSegments, protocolFamily);
  if (baseSegments === null) return normalized;

  const preset = parseUrl(presetUrl);
  const presetSegments = preset ? pathSegments(preset.pathname) : [];
  const endpointIndex = findEndpointIndex(presetSegments, protocolFamily);
  const presetPrefix = endpointIndex >= 0 ? presetSegments.slice(0, endpointIndex) : [];
  const selectedBaseSegments = baseSegments.length === 0
    ? presetPrefix
    : baseSegments;
  const endpoint = endpointSegments(protocolFamily);
  const nextPath = `/${[...selectedBaseSegments, ...endpoint].join("/")}`;
  parsed.pathname = nextPath;
  return parsed.toString();
}

export function completeProviderModelDiscoveryUrl(
  generationUrl: string,
  protocolFamily: ProviderProtocolFamily,
  presetModelUrl: string,
): string {
  const generation = parseUrl(generationUrl);
  if (!generation) return presetModelUrl.trim();

  const generationSegments = pathSegments(generation.pathname);
  const generationEndpointIndex = findEndpointIndex(generationSegments, protocolFamily);
  const generationBaseSegments = generationEndpointIndex >= 0
    ? generationSegments.slice(0, generationEndpointIndex)
    : generationSegments;

  const presetModel = parseUrl(presetModelUrl);
  const presetModelSegments = presetModel ? pathSegments(presetModel.pathname) : [];
  const modelEndpointIndex = presetModelSegments.lastIndexOf("models");
  const modelEndpoint = modelEndpointIndex >= 0
    ? presetModelSegments.slice(modelEndpointIndex)
    : ["models"];
  generation.pathname = `/${[
    ...generationBaseSegments,
    ...modelEndpoint,
  ].join("/")}`;
  generation.search = presetModel?.search ?? "";
  generation.hash = "";
  return generation.toString();
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

function stripGenerationEndpoint(
  segments: string[],
  protocolFamily: ProviderProtocolFamily,
): string[] | null {
  let base = segments;
  let endpointIndex = findEndpointIndex(base, protocolFamily);
  while (endpointIndex >= 0) {
    base = base.slice(0, endpointIndex);
    endpointIndex = findEndpointIndex(base, protocolFamily);
  }
  if (protocolFamily === "openai_compatible") {
    const suffixes = [
      ["chat", "completions"],
      ["chat", "completion"],
      ["completions"],
    ];
    for (const suffix of suffixes) {
      if (base.length >= suffix.length && base.slice(-suffix.length).join("/") === suffix.join("/")) {
        base = base.slice(0, -suffix.length);
      }
    }
  }
  return base;
}

function findEndpointIndex(
  segments: string[],
  protocolFamily: ProviderProtocolFamily,
): number {
  if (protocolFamily === "openai_compatible") {
    if (segments.length >= 2 && segments.slice(-2).join("/") === "chat/completions") return segments.length - 2;
    if (segments.length >= 2 && segments.slice(-2).join("/") === "chat/completion") return segments.length - 2;
    if (segments.at(-1) === "completions") return segments.length - 1;
    return -1;
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

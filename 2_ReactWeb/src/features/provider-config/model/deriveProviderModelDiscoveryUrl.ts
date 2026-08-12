import type { ProviderProtocolFamily } from "../../../entities/llm-provider/model/providerCatalog";

const API_VERSION_SEGMENT = /^v\d+(?:beta|alpha)?$/i;

export function deriveProviderModelDiscoveryUrl(
  generationUrl: string,
  protocolFamily: ProviderProtocolFamily,
  presetGenerationUrl = "",
  presetModelDiscoveryUrl = "",
): string {
  const generation = parseAbsoluteHttpUrl(generationUrl);
  if (!generation) return "";

  const presetGeneration = parseAbsoluteHttpUrl(presetGenerationUrl);
  const presetModel = parseAbsoluteHttpUrl(presetModelDiscoveryUrl);
  if (
    presetGeneration
    && presetModel
    && sameUrl(generation, presetGeneration)
  ) {
    return presetModelDiscoveryUrl.trim();
  }

  const generationSegments = pathSegments(generation.pathname);
  const generationBase = stripGenerationEndpoint(
    generationSegments,
    protocolFamily,
  );

  if (presetGeneration && presetModel) {
    const presetGenerationBase = stripGenerationEndpoint(
      pathSegments(presetGeneration.pathname),
      protocolFamily,
    );
    const presetModelSegments = pathSegments(presetModel.pathname);
    if (startsWithSegments(presetModelSegments, presetGenerationBase)) {
      const relativeModelPath = presetModelSegments.slice(presetGenerationBase.length);
      if (relativeModelPath.length > 0) {
        return withPath(
          generation,
          [...generationBase, ...relativeModelPath],
          presetModel.search,
        );
      }
    }
  }

  return withPath(
    generation,
    genericModelPath(generationSegments, generationBase, protocolFamily),
  );
}

export function isProviderModelDiscoveryUrlAuto(
  modelDiscoveryUrl: string,
  generationUrl: string,
  protocolFamily: ProviderProtocolFamily,
  presetGenerationUrl = "",
  presetModelDiscoveryUrl = "",
): boolean {
  if (modelDiscoveryUrl.trim().length === 0) {
    return generationUrl.trim().length === 0;
  }
  return modelDiscoveryUrl.trim() === deriveProviderModelDiscoveryUrl(
    generationUrl,
    protocolFamily,
    presetGenerationUrl,
    presetModelDiscoveryUrl,
  );
}

function parseAbsoluteHttpUrl(value: string): URL | null {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function pathSegments(pathname: string): string[] {
  return pathname
    .split("/")
    .filter(Boolean)
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    });
}

function stripGenerationEndpoint(
  segments: string[],
  protocolFamily: ProviderProtocolFamily,
): string[] {
  if (
    protocolFamily === "openai_compatible"
    && segments.length >= 2
    && ["chat/completions", "chat/completion"].includes(segments.slice(-2).join("/"))
  ) {
    return segments.slice(0, -2);
  }
  if (
    protocolFamily === "openai_compatible"
    && segments.at(-1) === "completions"
  ) {
    return segments.slice(0, -1);
  }
  if (
    protocolFamily === "gemini_generate_content"
    && segments.length >= 2
    && segments.at(-2) === "models"
    && /^\{model\}:.+$/.test(segments.at(-1) ?? "")
  ) {
    return segments.slice(0, -2);
  }
  if (
    (protocolFamily === "openai_responses" && segments.at(-1) === "responses")
    || (protocolFamily === "anthropic_messages" && segments.at(-1) === "messages")
  ) {
    return segments.slice(0, -1);
  }
  return segments;
}

function genericModelPath(
  generationSegments: string[],
  generationBase: string[],
  protocolFamily: ProviderProtocolFamily,
): string[] {
  if (generationBase.length !== generationSegments.length) {
    return [...generationBase, "models"];
  }
  if (generationSegments.length === 0) {
    return [
      protocolFamily === "gemini_generate_content" ? "v1beta" : "v1",
      "models",
    ];
  }
  if (generationSegments.at(-1) === "models") return generationSegments;
  if (API_VERSION_SEGMENT.test(generationSegments.at(-1) ?? "")) {
    return [...generationSegments, "models"];
  }
  return [...generationSegments.slice(0, -1), "models"];
}

function startsWithSegments(value: string[], prefix: string[]): boolean {
  return prefix.every((segment, index) => value[index] === segment);
}

function sameUrl(left: URL, right: URL): boolean {
  return left.href === right.href;
}

function withPath(url: URL, segments: string[], search = ""): string {
  const result = new URL(url.href);
  result.pathname = `/${segments.join("/")}`;
  result.search = search;
  result.hash = "";
  return result.toString();
}

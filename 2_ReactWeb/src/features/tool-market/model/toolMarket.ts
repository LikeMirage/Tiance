export type ToolMarketInstallationStatus =
  | "not-installed"
  | "installed"
  | "update-available"
  | "call-name-conflict";

export type ToolMarketTool = {
  author: string;
  callName: string;
  compatibility: { minTianceVersion: string; platforms: string[] };
  displayName: string;
  id: string;
  installationStatus: ToolMarketInstallationStatus;
  license: string;
  localCallName: string | null;
  localProjectId: string | null;
  localVersion: string | null;
  packageUrl: string;
  runtime: string;
  sha256: string;
  size: number;
  suggestedCallName: string | null;
  summary: string;
  version: string;
};

export type ToolMarketFilters = {
  authors: string[];
  platforms: string[];
  runtimes: string[];
  statuses: ToolMarketInstallationStatus[];
};

export type ToolMarketSettings = {
  filters: ToolMarketFilters;
  schemaVersion: 1;
  source: string;
};

export type ToolMarketIndex = {
  cached: boolean;
  kind: "tiance-tool-market";
  name: string;
  schemaVersion: 1;
  source: string;
  tools: readonly ToolMarketTool[];
  updatedAt: string;
};

export function filterToolMarketItems(
  tools: readonly ToolMarketTool[],
  filters: ToolMarketFilters,
  query: string,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return tools.filter((tool) => {
    if (filters.authors.length && !filters.authors.includes(tool.author)) return false;
    if (filters.runtimes.length && !filters.runtimes.includes(tool.runtime)) return false;
    if (
      filters.platforms.length
      && !filters.platforms.some((platform) => tool.compatibility.platforms.includes(platform))
    ) return false;
    if (filters.statuses.length && !filters.statuses.includes(tool.installationStatus)) return false;
    if (!normalizedQuery) return true;
    return [tool.displayName, tool.callName, tool.id, tool.author, tool.summary, tool.runtime]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function listToolMarketValues(
  tools: readonly ToolMarketTool[],
  key: "author" | "runtime",
) {
  return [...new Set(tools.map((tool) => tool[key]))]
    .sort((left, right) => left.localeCompare(right));
}

export function listToolMarketPlatforms(tools: readonly ToolMarketTool[]) {
  return [...new Set(tools.flatMap((tool) => tool.compatibility.platforms))]
    .sort((left, right) => left.localeCompare(right));
}

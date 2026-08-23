export type ProviderMarketInstallationStatus =
  | "not-installed"
  | "installed"
  | "update-available";

export type ProviderMarketProvider = {
  author: string;
  compatibility: { minTianceVersion: string };
  id: string;
  installationStatus: ProviderMarketInstallationStatus;
  license: string;
  localProjectId: string | null;
  localVersion: string | null;
  modelCount: number;
  name: string;
  packageUrl: string;
  protocol: string;
  sha256: string;
  size: number;
  summary: string;
  version: string;
};

export type ProviderMarketFilters = {
  authors: string[];
  protocols: string[];
  statuses: ProviderMarketInstallationStatus[];
};

export type ProviderMarketSettings = {
  filters: ProviderMarketFilters;
  schemaVersion: 1;
  source: string;
};

export type ProviderMarketIndex = {
  cached: boolean;
  kind: "tiance-provider-market";
  name: string;
  providers: readonly ProviderMarketProvider[];
  schemaVersion: 1;
  source: string;
  updatedAt: string;
};

export function filterProviderMarketItems(
  providers: readonly ProviderMarketProvider[],
  filters: ProviderMarketFilters,
  query: string,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return providers.filter((provider) => {
    if (filters.authors.length && !filters.authors.includes(provider.author)) return false;
    if (filters.protocols.length && !filters.protocols.includes(provider.protocol)) return false;
    if (filters.statuses.length && !filters.statuses.includes(provider.installationStatus)) {
      return false;
    }
    if (!normalizedQuery) return true;
    return [provider.name, provider.id, provider.author, provider.summary, provider.protocol]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function listProviderMarketValues(
  providers: readonly ProviderMarketProvider[],
  key: "author" | "protocol",
) {
  return [...new Set(providers.map((provider) => provider[key]))]
    .sort((left, right) => left.localeCompare(right));
}

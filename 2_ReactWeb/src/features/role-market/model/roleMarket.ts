export type RoleMarketInstallationStatus =
  | "not-installed"
  | "installed"
  | "update-available";

export type RoleMarketRole = {
  author: string;
  compatibility: {
    minTianceVersion: string;
  };
  id: string;
  installationStatus: RoleMarketInstallationStatus;
  license: string;
  localProjectId: string | null;
  localVersion: string | null;
  name: string;
  packageUrl: string;
  sha256: string;
  size: number;
  summary: string;
  version: string;
};

export type RoleMarketFilters = {
  authors: string[];
  statuses: RoleMarketInstallationStatus[];
};

export type RoleMarketSettings = {
  filters: RoleMarketFilters;
  schemaVersion: 1;
  source: string;
};

export type RoleMarketIndex = {
  cached: boolean;
  kind: "tiance-role-market";
  name: string;
  roles: readonly RoleMarketRole[];
  schemaVersion: 1;
  source: string;
  updatedAt: string;
};

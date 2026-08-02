export type ThemeMarketMode = "dark" | "light";

export type ThemeMarketTheme = {
  author: string;
  baseColors: string[];
  compatibility: {
    minTianceVersion: string;
    themeSchemaVersion: number;
  };
  id: string;
  installationStatus: ThemeMarketInstallationStatus;
  license: string;
  mode: ThemeMarketMode;
  localVersion: string | null;
  name: string;
  packageUrl: string;
  previewUrl: string;
  previewPath: string;
  sha256: string;
  size: number;
  summary: string;
  version: string;
};

export type ThemeMarketInstallationStatus =
  | "not-installed"
  | "installed"
  | "update-available";

export type ThemeMarketFilters = {
  authors: string[];
  baseColors: string[];
  modes: ThemeMarketMode[];
  statuses: ThemeMarketInstallationStatus[];
};

export type ThemeMarketSettings = {
  filters: ThemeMarketFilters;
  schemaVersion: 1;
  source: string;
};

export type ThemeMarketIndex = {
  kind: "tiance-theme-market";
  name: string;
  cached: boolean;
  schemaVersion: 1;
  themes: readonly ThemeMarketTheme[];
  updatedAt: string;
  source: string;
};

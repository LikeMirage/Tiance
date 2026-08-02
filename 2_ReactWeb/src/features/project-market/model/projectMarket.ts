export type ProjectMarketInstallationStatus = "not-installed" | "installed";
export type ProjectMarketScope = "project" | "knowledge" | "experience";
export type ProjectMarketNamespace = "projectMarket" | "knowledgeMarket" | "experienceMarket";
export type ProjectMarketInstallPhase =
  | "queued"
  | "downloading"
  | "extracting"
  | "importing"
  | "completed"
  | "failed";

export type ProjectMarketStats = {
  fileCount: number | null;
  conversationCount: number | null;
  branchCount: number | null;
};

export type ProjectMarketProject = {
  author: string;
  id: string;
  installationStatus: ProjectMarketInstallationStatus;
  localProjectId: string | null;
  name: string;
  previewPath: string | null;
  previewUrl: string | null;
  stats: ProjectMarketStats | null;
  summary: string;
  tags: string[];
  updatedAt: string;
  version: string;
};

export type ProjectMarketFilters = {
  authors: string[];
  statuses: ProjectMarketInstallationStatus[];
  tags: string[];
};

export type ProjectMarketSettings = {
  filters: ProjectMarketFilters;
  schemaVersion: 1;
  source: string;
};

export type ProjectMarketIndex = {
  cached: boolean;
  kind: "tiance-project-market" | "tiance-knowledge-market" | "tiance-experience-market";
  name: string;
  projects: readonly ProjectMarketProject[];
  schemaVersion: 1;
  source: string;
  updatedAt: string;
};

export type ProjectMarketInstallResult = {
  categoryId: string;
  marketProjectId: string;
  projectId: string;
  version: string;
};

export type ProjectMarketInstallOperation = {
  error: string | null;
  marketProjectId: string;
  operationId: string;
  phase: ProjectMarketInstallPhase;
  result: ProjectMarketInstallResult | null;
};

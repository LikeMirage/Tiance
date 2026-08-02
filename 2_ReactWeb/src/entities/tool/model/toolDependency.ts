export type ToolDependencyStatus = "installed" | "missing" | "version_mismatch" | "invalid";

export type ToolDependency = {
  line_number: number;
  requirement: string;
  name: string;
  specifier: string;
  installed_version: string | null;
  status: ToolDependencyStatus;
  message: string;
};

export type ToolDependencyListResponse = {
  category_id: string;
  project_id: string;
  requirements_path: string;
  target_path: string;
  index_url: string;
  pip_available: boolean;
  count: number;
  items: ToolDependency[];
};

export type ToolDependencyInstallRequest = {
  requirement?: string | null;
  index_url?: string | null;
};

export type ToolDependencyInstallResponse = {
  ok: boolean;
  message: string;
  installed: string[];
  report: ToolDependencyListResponse;
};

export type ToolDependencyInstallTaskStatus = "queued" | "running" | "done" | "error";

export type ToolDependencyInstallTaskResponse = {
  task_id: string;
  category_id: string;
  project_id: string;
  requirement: string | null;
  status: ToolDependencyInstallTaskStatus;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  installed: string[];
  report: ToolDependencyListResponse | null;
};

export type ToolDependencyUninstallRequest = {
  requirement: string;
};

export type ToolDependencyUninstallResponse = {
  ok: boolean;
  message: string;
  uninstalled: string[];
  report: ToolDependencyListResponse;
};

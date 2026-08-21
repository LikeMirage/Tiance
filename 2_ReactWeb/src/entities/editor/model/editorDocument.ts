// 编辑器领域类型

export type EditorTabId = string;

export type DocumentLanguage = "javascript" | "typescript" | "python" | "html" | "css" | "json" | "markdown" | "plaintext";

export type DocumentFileSource = {
  key: string;
  kind: "project" | "tool-dashboard" | "tool-folder" | "toolset";
  id: string;
  label?: string | null;
  projectId?: string | null;
};

export type DocumentTab = {
  id: EditorTabId;
  title: string;
  displayPath: string;
  kind: "text" | "image" | "video" | "pdf" | "office" | "database" | "unsupported";
  languageId: DocumentLanguage;
  content: string;
  savedContent: string;
  textContentAccessedAt: number | null;
  textContentLoaded: boolean;
  textContentUnavailable?: {
    reason: "too_large";
    sizeBytes: number;
    limitBytes: number;
  } | null;
  isDirty: boolean;
  isMissing: boolean;
  saveState: "idle" | "saving" | "saved" | "error";
  saveError: string | null;
  fileSource: DocumentFileSource | null;
  filePath: string | null;
  projectId: string | null;
  projectFilePath: string | null;
  assetVersion: number | null;
  mtimeMs: number | null;
  externalChange:
    | {
      kind: "conflict";
      detectedAt: number;
      filePath: string;
      mtimeMs: number | null;
    }
    | null;
  conversationDataView?: {
    fileName: string;
    sessionId: string | null;
    page: number;
    pageSize: number;
    totalCount: number;
    totalPages: number;
    hasPrevious: boolean;
    hasNext: boolean;
  } | null;
};

export type WorkspaceState = {
  project_id: string;
  expanded_paths: string[];
  open_file_paths: string[];
  active_file_path: string | null;
  active_dashboard: "conversation_overview" | "role_configuration" | "theme_configuration" | null;
};

export type WorkspaceStateSaveRequest = {
  expanded_paths: string[];
  open_file_paths: string[];
  active_file_path: string | null;
  active_dashboard: "conversation_overview" | "role_configuration" | "theme_configuration" | null;
};

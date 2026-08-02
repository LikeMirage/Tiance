import type {
  ConversationBranchNode,
  ConversationRuntimeStatus,
} from "../../llm-chat/model/conversation";
import type {
  FileWorkspaceCopyRequest,
  FileWorkspaceCreateRequest,
  FileWorkspaceEntryKind,
  FileWorkspaceMoveRequest,
  FileWorkspaceNode,
  FileWorkspaceOpenExternalRequest,
  FileWorkspaceOpenExternalResponse,
  FileWorkspaceRevealRequest,
  FileWorkspaceTreeResponse,
} from "../../file-workspace/model/fileWorkspace";

export type ProjectKind =
  | "project"
  | "knowledge"
  | "experience"
  | "role"
  | "theme"
  | "tool"
  | "provider";

export type Project = {
  project_id: string;
  name: string;
  root_path: string;
  category_id: string;
  project_kind: ProjectKind;
  is_default: boolean;
  is_managed: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ProjectListResponse = {
  count: number;
  items: Project[];
};

export type ProjectCategory = {
  category_id: string;
  name: string;
  category_kind: ProjectKind;
  is_default: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ProjectCategoryListResponse = {
  count: number;
  items: ProjectCategory[];
};

export type ProjectOverviewSession = {
  session_id: string;
  sequence_number: number;
  title: string;
  runtime_status: ConversationRuntimeStatus;
  provider_id: string | null;
  model_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
  pinned: boolean;
  usage: ProjectOverviewUsage;
};

export type ProjectOverviewUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  prompt_cache_hit_tokens: number;
  prompt_cache_miss_tokens: number;
  cost_amount: number | null;
  cost_currency: string | null;
  record_count: number;
  estimated_record_count?: number;
};

export type ProjectOverviewItem = {
  project: Project;
  active_session_id: string | null;
  active_count: number;
  idle_count: number;
  error_count: number;
  usage: ProjectOverviewUsage;
  sessions: ProjectOverviewSession[];
  session_relations: ConversationBranchNode[];
};

export type ProjectCategoryOverviewResponse = {
  category_id: string;
  category_name: string;
  project_count: number;
  session_count: number;
  active_session_count: number;
  idle_session_count: number;
  error_session_count: number;
  projects: ProjectOverviewItem[];
};

export type ProjectCreateRequest = {
  category_id?: string | null;
  name?: string | null;
  project_kind?: ProjectKind;
  root_path?: string | null;
};

export type RoleProjectCreateRequest = {
  category_id?: string | null;
  name?: string | null;
};

// ------------------------------------------------------------------
// 项目文件
// ------------------------------------------------------------------

export type ProjectFileKind = FileWorkspaceEntryKind;

export type ProjectFileNode = FileWorkspaceNode;

export type ProjectFileTreeResponse = FileWorkspaceTreeResponse & {
  project_id: string;
};

type ProjectFileMutationMeta = {
  sourceId?: string;
};

export type ProjectFileMutation =
  | ({
    action: "upsert";
    projectId: string;
    node: ProjectFileNode;
    version: number;
  } & ProjectFileMutationMeta)
  | ({
    action: "move";
    projectId: string;
    previousPath: string;
    node: ProjectFileNode;
    version: number;
  } & ProjectFileMutationMeta)
  | ({
    action: "delete";
    projectId: string;
    path: string;
    version: number;
  } & ProjectFileMutationMeta);

export type ProjectFileCreateRequest = FileWorkspaceCreateRequest;

export type ProjectFileMoveRequest = FileWorkspaceMoveRequest;

export type ProjectFileCopyRequest = FileWorkspaceCopyRequest;

export type ProjectFileRevealRequest = FileWorkspaceRevealRequest;

export type ProjectFileOpenExternalRequest = FileWorkspaceOpenExternalRequest;

export type ProjectFileOpenExternalResponse = FileWorkspaceOpenExternalResponse & {
  project_id: string;
};

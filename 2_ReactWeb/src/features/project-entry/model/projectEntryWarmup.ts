import type {
  ConversationMessageListResponse,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import type { FileWorkspaceContentResponse } from "../../../entities/file-workspace/model/fileWorkspace";
import { isTextFile } from "../../../entities/editor/model/languageMapping";
import type { ConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";
import { getProjectConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";
import { getProjectConversationMessages } from "../../../services/project/getProjectConversationMessages";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import {
  getProjectWorkspaceState,
  type WorkspaceStateResponse,
} from "../../../services/project/getProjectWorkspaceState";
import { createProjectFileWorkspaceApi } from "../../../services/project/projectFileWorkspaceApi";
import { getFileWorkspaceTreeWithTimeout } from "../../file-workspace/model/fileWorkspaceBrowserFileLoader";
import {
  findNode,
  mapFileWorkspaceNode,
  normalizeWorkspacePath,
  updateNodeChildren,
  type FileWorkspaceBrowserNode,
} from "../../file-workspace/model/fileWorkspaceBrowserTreeModel";

const WARMUP_CACHE_TTL_MS = 5_000;

export type ProjectEntryWarmupOptions = {
  refreshConversations?: boolean;
  sessionId?: string | null;
};

export type ProjectEntryWarmup = {
  conversations?: ConversationSessionListResponse;
  fileContents: Map<string, FileWorkspaceContentResponse>;
  loadedAt: number;
  projectId: string;
  rootTree?: FileWorkspaceBrowserNode[];
  sessionMessages: Record<string, ConversationMessageListResponse>;
  sessionUsageSummaries: Record<string, ConversationUsageSummary>;
  workspaceState?: WorkspaceStateResponse;
};

const warmupCache = new Map<string, ProjectEntryWarmup>();
const warmupRequests = new Map<string, Promise<ProjectEntryWarmup>>();

export function getCachedProjectEntryWarmup(projectId: string): ProjectEntryWarmup | null {
  const cached = warmupCache.get(projectId);
  if (!cached) return null;
  if (Date.now() - cached.loadedAt > WARMUP_CACHE_TTL_MS) {
    warmupCache.delete(projectId);
    return null;
  }
  return cached;
}

export function synchronizeCachedProjectWorkspaceState(
  projectId: string,
  workspaceState: WorkspaceStateResponse,
) {
  const cached = warmupCache.get(projectId);
  if (!cached) return;
  cached.workspaceState = workspaceState;
  cached.loadedAt = Date.now();
}

export async function preloadProjectEntry(
  projectId: string,
  options: ProjectEntryWarmupOptions = {},
): Promise<ProjectEntryWarmup> {
  const cached = getCachedProjectEntryWarmup(projectId);
  if (cached) {
    if (shouldRefreshConversations(cached, options)) {
      await refreshWarmupConversations(projectId, cached, options.sessionId);
    } else {
      await preloadRequestedSession(projectId, cached, options.sessionId);
    }
    return cached;
  }

  const existingRequest = warmupRequests.get(projectId);
  if (existingRequest) {
    const warmup = await existingRequest;
    if (shouldRefreshConversations(warmup, options)) {
      await refreshWarmupConversations(projectId, warmup, options.sessionId);
    } else {
      await preloadRequestedSession(projectId, warmup, options.sessionId);
    }
    return warmup;
  }

  const request = loadProjectEntryWarmup(projectId, options);
  warmupRequests.set(projectId, request);
  try {
    return await request;
  } finally {
    warmupRequests.delete(projectId);
  }
}

function createEmptyWarmup(projectId: string): ProjectEntryWarmup {
  return {
    fileContents: new Map(),
    loadedAt: Date.now(),
    projectId,
    sessionMessages: {},
    sessionUsageSummaries: {},
  };
}

async function loadProjectEntryWarmup(
  projectId: string,
  options: ProjectEntryWarmupOptions,
) {
  const api = createProjectFileWorkspaceApi(projectId);
  const warmup = createEmptyWarmup(projectId);

  const workspaceStatePromise = getProjectWorkspaceState(projectId).catch(() => null);
  const conversationsPromise = getProjectConversations(projectId).catch(() => null);
  const rootTreePromise = getFileWorkspaceTreeWithTimeout(api)
    .then((response) => response.items.map(mapFileWorkspaceNode))
    .catch(() => null);

  const [workspaceState, conversations, rootTree] = await Promise.all([
    workspaceStatePromise,
    conversationsPromise,
    rootTreePromise,
  ]);

  if (workspaceState) {
    warmup.workspaceState = workspaceState;
    await preloadActiveTextFile(projectId, workspaceState.active_file_path, warmup);
  }

  if (rootTree) {
    warmup.rootTree = workspaceState
      ? await preloadExpandedFolders(api, rootTree, workspaceState.expanded_paths)
      : rootTree;
  }

  if (conversations) {
    warmup.conversations = conversations;
    await preloadRequestedSession(
      projectId,
      warmup,
      options.sessionId ?? resolveActiveSessionId(conversations),
    );
  }

  warmup.loadedAt = Date.now();
  warmupCache.set(projectId, warmup);
  return warmup;
}

async function preloadActiveTextFile(
  projectId: string,
  activeFilePath: string | null,
  warmup: ProjectEntryWarmup,
) {
  const path = normalizeWorkspacePath(activeFilePath ?? "");
  if (!path || !isTextFile(path)) return;

  const api = createProjectFileWorkspaceApi(projectId);
  try {
    warmup.fileContents.set(path, await api.readTextFile(path));
  } catch {
    // 标签恢复流程会按现有错误处理重新读取活动文件。
  }
}

async function preloadExpandedFolders(
  api: ReturnType<typeof createProjectFileWorkspaceApi>,
  rootTree: FileWorkspaceBrowserNode[],
  expandedPaths: string[],
) {
  let tree = rootTree;
  const folderPaths = Array.from(
    new Set(expandedPaths.map(normalizeWorkspacePath).filter(Boolean)),
  ).sort((left, right) => getPathDepth(left) - getPathDepth(right));

  for (const folderPath of folderPaths) {
    const folderNode = findNode(tree, folderPath);
    if (!folderNode || folderNode.kind !== "folder" || folderNode.isChildrenLoaded) {
      continue;
    }

    try {
      const response = await getFileWorkspaceTreeWithTimeout(api, { parentPath: folderPath });
      tree = updateNodeChildren(
        tree,
        folderNode.id,
        response.items.map(mapFileWorkspaceNode),
        true,
      );
    } catch {
      return tree;
    }
  }

  return tree;
}

function shouldRefreshConversations(
  warmup: ProjectEntryWarmup,
  options: ProjectEntryWarmupOptions,
) {
  if (options.refreshConversations) {
    return true;
  }
  if (!options.sessionId) {
    return false;
  }
  const conversations = warmup.conversations;
  if (!conversations) {
    return true;
  }
  if (!conversations.items.some((session) => session.session_id === options.sessionId)) {
    return true;
  }
  return conversations.active_session_id !== options.sessionId;
}

async function refreshWarmupConversations(
  projectId: string,
  warmup: ProjectEntryWarmup,
  sessionId?: string | null,
) {
  const conversations = await getProjectConversations(projectId).catch(() => null);
  if (!conversations) {
    await preloadRequestedSession(projectId, warmup, sessionId);
    return;
  }

  warmup.conversations = conversations;
  await preloadRequestedSession(
    projectId,
    warmup,
    sessionId ?? resolveActiveSessionId(conversations),
  );
  warmup.loadedAt = Date.now();
  warmupCache.set(projectId, warmup);
}

async function preloadRequestedSession(
  projectId: string,
  warmup: ProjectEntryWarmup,
  sessionId?: string | null,
) {
  if (!sessionId) return;
  if (warmup.sessionMessages[sessionId] && warmup.sessionUsageSummaries[sessionId]) {
    return;
  }

  const [messagesResult, usageResult] = await Promise.allSettled([
    warmup.sessionMessages[sessionId]
      ? Promise.resolve(warmup.sessionMessages[sessionId])
      : getProjectConversationMessages(projectId, sessionId),
    warmup.sessionUsageSummaries[sessionId]
      ? Promise.resolve(warmup.sessionUsageSummaries[sessionId])
      : getProjectConversationUsageSummary(projectId, sessionId),
  ]);

  if (messagesResult.status === "fulfilled") {
    warmup.sessionMessages[sessionId] = messagesResult.value;
  }
  if (usageResult.status === "fulfilled") {
    warmup.sessionUsageSummaries[sessionId] = usageResult.value;
  }
  warmup.loadedAt = Date.now();
  warmupCache.set(projectId, warmup);
}

function resolveActiveSessionId(response: ConversationSessionListResponse) {
  const sessionIds = new Set(response.items.map((session) => session.session_id));
  if (response.active_session_id && sessionIds.has(response.active_session_id)) {
    return response.active_session_id;
  }
  return response.items[0]?.session_id ?? null;
}

function getPathDepth(path: string) {
  return path.split("/").filter(Boolean).length;
}

import type { DocumentTab, EditorTabId } from "../../../entities/editor/model/editorDocument";
import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";

type BuildVirtualHtmlPreviewTabOptions = {
  createdAt?: Date;
  projectId?: string | null;
};

type MemoryDashboardScope = "global" | "project";

type BuildVirtualMemoryDashboardTabOptions = {
  projectId?: string | null;
  scope: MemoryDashboardScope;
};

type BuildVirtualReferenceViewerTabOptions = {
  projectId?: string | null;
};

type BuildVirtualConversationBranchesTabOptions = {
  projectId: string;
};

type BuildVirtualConversationDataTabOptions = {
  content: string;
  fileName: string;
  projectId: string;
  revisionMs: number;
  sessionId: string | null;
  totalCount?: number | null;
  page?: number | null;
  pageSize?: number | null;
  totalPages?: number | null;
  hasPrevious?: boolean;
  hasNext?: boolean;
};

export const PROJECT_CONVERSATION_OVERVIEW_TAB_PREFIX =
  "project-conversation-overview:";
export const PROJECT_KNOWLEDGE_CONTENT_TAB_PREFIX =
  "project-knowledge-content:";
export const PROJECT_ROLE_CONFIGURATION_TAB_PREFIX =
  "project-role-configuration:";
export const PROJECT_THEME_CONFIGURATION_TAB_PREFIX =
  "project-theme-configuration:";

export function buildVirtualProjectConversationOverviewTab(
  projectId: string,
): DocumentTab {
  const content = JSON.stringify({ project_id: projectId }, null, 2);
  const now = Date.now();
  return {
    id: `${PROJECT_CONVERSATION_OVERVIEW_TAB_PREFIX}${projectId}`,
    title: "会话总览",
    displayPath: "项目 / 会话总览",
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualProjectKnowledgeContentTab(
  projectId: string,
): DocumentTab {
  const content = JSON.stringify({ project_id: projectId }, null, 2);
  const now = Date.now();
  return {
    id: `${PROJECT_KNOWLEDGE_CONTENT_TAB_PREFIX}${projectId}`,
    title: "知识内容",
    displayPath: "知识 / 内容看板",
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualProjectRoleConfigurationTab(
  projectId: string,
): DocumentTab {
  const content = JSON.stringify({ project_id: projectId }, null, 2);
  const now = Date.now();
  return {
    id: `${PROJECT_ROLE_CONFIGURATION_TAB_PREFIX}${projectId}`,
    title: "角色配置",
    displayPath: "角色 / 配置看板",
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualProjectThemeConfigurationTab(
  projectId: string,
): DocumentTab {
  const content = JSON.stringify({ project_id: projectId }, null, 2);
  const now = Date.now();
  return {
    id: `${PROJECT_THEME_CONFIGURATION_TAB_PREFIX}${projectId}`,
    title: "主题配置",
    displayPath: "主题 / 配置看板",
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualHtmlPreviewTab(
  html: string,
  options: BuildVirtualHtmlPreviewTabOptions = {},
): DocumentTab {
  const createdAt = options.createdAt ?? new Date();
  const tabId: EditorTabId = `preview:html:${createdAt.getTime()}`;
  const now = Date.now();
  return {
    id: tabId,
    title: makeHtmlPreviewTabTitle(createdAt),
    displayPath: "AI 生成 / HTML 预览",
    kind: "text",
    languageId: "html",
    content: html,
    savedContent: html,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId: options.projectId ?? null,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

function makeHtmlPreviewTabTitle(createdAt: Date) {
  return `HTML 预览 ${createdAt.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })}`;
}

export function buildVirtualMemoryDashboardTab({
  projectId = null,
  scope,
}: BuildVirtualMemoryDashboardTabOptions): DocumentTab {
  const fileName = scope === "global" ? "global_memory.jsonl" : "project_memory.jsonl";
  const title = scope === "global" ? "全局记忆" : "项目记忆";
  const content = JSON.stringify({
    data_source: fileName,
    scope,
    note: scope === "global"
      ? "全局记忆不属于当前项目目录，看板通过长期记忆接口读取同一份全局数据。"
      : "项目记忆属于当前项目，看板通过长期记忆接口读取同一份项目数据。",
  }, null, 2);
  const now = Date.now();
  return {
    id: `memory-dashboard:${scope}:${projectId ?? "none"}`,
    title: fileName,
    displayPath: `${title} / ${fileName}`,
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualConversationBranchesTab({
  projectId,
}: BuildVirtualConversationBranchesTabOptions): DocumentTab {
  const content = JSON.stringify({ project_id: projectId }, null, 2);
  const now = Date.now();
  return {
    id: `conversation-branches:${projectId}`,
    title: "会话分支",
    displayPath: "会话 / 分支图",
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

export function buildVirtualConversationDataTab({
  content,
  fileName,
  projectId,
  revisionMs,
  sessionId,
  totalCount = null,
  page = null,
  pageSize = null,
  totalPages = null,
  hasPrevious = false,
  hasNext = false,
}: BuildVirtualConversationDataTabOptions): DocumentTab {
  const logicalPath = sessionId
    ? `.Tiance/conversations/sessions/${sessionId}/${fileName}`
    : fileName === "project_memory.jsonl"
      ? ".Tiance/memory/project_memory.jsonl"
      : `.Tiance/conversations/${fileName}`;
  const now = Date.now();
  return {
    id: `conversation-data:${projectId}:${sessionId ?? "project"}:${fileName}`,
    title: fileName,
    displayPath: logicalPath,
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId,
    projectFilePath: null,
    assetVersion: revisionMs,
    mtimeMs: revisionMs,
    externalChange: null,
    conversationDataView: page !== null
      && pageSize !== null
      && totalCount !== null
      && totalPages !== null
      ? {
        fileName,
        sessionId,
        page,
        pageSize,
        totalCount,
        totalPages,
        hasPrevious,
        hasNext,
      }
      : null,
  };
}

export function buildVirtualReferenceViewerTab(
  payload: EditorReferenceViewerPayload,
  options: BuildVirtualReferenceViewerTabOptions = {},
): DocumentTab {
  const content = JSON.stringify(payload, null, 2);
  const title = makeReferenceViewerTitle(payload);
  const now = Date.now();
  return {
    id: `reference-viewer:${payload.kind}:${payload.reference.id}`,
    title,
    displayPath: `对话引用 / ${title}`,
    kind: "text",
    languageId: "json",
    content,
    savedContent: content,
    textContentAccessedAt: now,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath: null,
    projectId: options.projectId ?? payload.reference.projectId ?? null,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: null,
  };
}

function makeReferenceViewerTitle(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "image") {
    return `引用-${payload.reference.sourceFileName}`;
  }
  return `引用-${payload.reference.fileName}`;
}

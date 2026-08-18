import type {
  DocumentFileSource,
  DocumentTab,
  EditorTabId,
} from "../../../entities/editor/model/editorDocument";
import type { FileWorkspaceNode } from "../../../entities/file-workspace/model/fileWorkspace";
import { publishToolCatalogChange } from "../../../entities/tool/model/toolCatalogEvents";
import { parseToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";

import type { DocumentFileSourceRuntime } from "./documentFileSources";
import { normalizeWorkspacePath } from "./documentTabUtils";

export type ToolDashboardView = "basics" | "examples" | "dependencies" | "callRecords";

export const TOOL_MANIFEST_FILE = ".tool/tool.json";
const TOOL_INPUT_SCHEMA_FILE = ".tool/input.schema.json";
const TOOL_OUTPUT_SCHEMA_FILE = ".tool/output.schema.json";
const TOOL_EXAMPLES_FILE = ".tool/examples.json";

export function makeToolDashboardTabId(sourceKey: string, view: ToolDashboardView): EditorTabId {
  return `${sourceKey}:__tool_dashboard_${view}__`;
}

export function buildToolDashboardTab(
  source: DocumentFileSource,
  title: string,
  view: ToolDashboardView,
  existing?: DocumentTab,
): DocumentTab {
  const tabTitle = getToolDashboardTitle(view);
  const needsContent = doesToolDashboardViewNeedContent(view);
  const placeholderContent = formatDashboardJson(buildToolDashboardPlaceholder(title, view));
  const existingAccessedAt = existing?.textContentAccessedAt ?? null;
  const now = Date.now();
  return {
    id: makeToolDashboardTabId(source.key, view),
    title: tabTitle,
    displayPath: `${title} / ${tabTitle}`,
    kind: "text",
    languageId: "json",
    content: existing?.content ?? placeholderContent,
    savedContent: existing?.savedContent ?? placeholderContent,
    textContentAccessedAt: existingAccessedAt ?? now,
    textContentLoaded: existing?.textContentLoaded ?? true,
    isDirty: existing?.isDirty ?? false,
    isMissing: existing?.isMissing ?? false,
    saveState: existing?.saveState ?? (needsContent ? "saving" : "idle"),
    saveError: existing?.saveError ?? null,
    fileSource: {
      ...source,
      kind: "tool-dashboard",
    },
    filePath: null,
    projectId: source.projectId ?? null,
    projectFilePath: null,
    assetVersion: null,
    mtimeMs: null,
    externalChange: existing?.externalChange ?? null,
  };
}

function getToolDashboardTitle(view: ToolDashboardView) {
  if (view === "dependencies") return "工具依赖";
  if (view === "callRecords") return "调用记录";
  if (view === "examples") return "应用场景";
  return "基础设置";
}

export async function readToolDashboardContent(
  runtime: DocumentFileSourceRuntime,
  view: ToolDashboardView,
): Promise<string> {
  const api = runtime.getApi();
  if (view === "basics") {
    const [manifest, inputSchema] = await Promise.all([
      api.readTextFile(TOOL_MANIFEST_FILE),
      api.readTextFile(TOOL_INPUT_SCHEMA_FILE),
    ]);

    return formatDashboardJson({
      ...parseJsonObject(manifest.content, TOOL_MANIFEST_FILE),
      input_schema: parseJsonObject(inputSchema.content, TOOL_INPUT_SCHEMA_FILE),
    });
  }

  if (view === "examples") {
    const [manifest, examples] = await Promise.all([
      api.readTextFile(TOOL_MANIFEST_FILE),
      api.readTextFile(TOOL_EXAMPLES_FILE),
    ]);

    return formatDashboardJson({
      ...parseJsonObject(manifest.content, TOOL_MANIFEST_FILE),
      examples: parseJsonArray(examples.content, TOOL_EXAMPLES_FILE),
    });
  }

  return formatDashboardJson({});
}

export async function saveToolDashboardContent(
  runtime: DocumentFileSourceRuntime,
  content: string,
  view: ToolDashboardView,
): Promise<FileWorkspaceNode[]> {
  const api = runtime.getApi();
  const payload = parseJsonObject(content, "工具看板内容");
  const manifest: Record<string, unknown> = {
    ...payload,
    files: {
      input_schema: TOOL_INPUT_SCHEMA_FILE,
      output_schema: TOOL_OUTPUT_SCHEMA_FILE,
      examples: TOOL_EXAMPLES_FILE,
    },
  };
  delete manifest.input_schema;
  delete manifest.output_schema;
  delete manifest.examples;

  const savedNodes: FileWorkspaceNode[] = [];
  if (view === "basics") {
    const inputSchema = expectJsonObjectValue(payload.input_schema, TOOL_INPUT_SCHEMA_FILE);
    savedNodes.push(await api.saveTextFile(TOOL_INPUT_SCHEMA_FILE, formatDashboardJson(inputSchema)));
  }
  if (view === "examples") {
    const examples = expectJsonArrayValue(payload.examples, TOOL_EXAMPLES_FILE);
    savedNodes.push(await api.saveTextFile(TOOL_EXAMPLES_FILE, formatDashboardJson(examples)));
  }
  savedNodes.push(await api.saveTextFile(TOOL_MANIFEST_FILE, formatDashboardJson(manifest)));
  return savedNodes;
}

export function doesToolDashboardViewNeedContent(view: ToolDashboardView) {
  return view === "basics" || view === "examples";
}

export function getToolDashboardViewFromTab(tab: DocumentTab | null | undefined): ToolDashboardView {
  if (tab?.id.includes("__tool_dashboard_dependencies__")) {
    return "dependencies";
  }
  if (tab?.id.includes("__tool_dashboard_callRecords__")) {
    return "callRecords";
  }
  return tab?.id.includes("__tool_dashboard_examples__") ? "examples" : "basics";
}

export function invalidateLoadedToolDashboardTab(
  tab: DocumentTab,
  loadedTabIds: Set<EditorTabId>,
): DocumentTab {
  loadedTabIds.delete(tab.id);
  if (!doesToolDashboardViewNeedContent(getToolDashboardViewFromTab(tab))) {
    return tab;
  }
  return {
    ...tab,
    saveState: "idle",
    saveError: null,
    textContentLoaded: false,
    content: "",
    savedContent: "",
  };
}

export function isToolCatalogMetadataPath(path: string) {
  const normalizedPath = normalizeWorkspacePath(path);
  return (
    normalizedPath === TOOL_MANIFEST_FILE ||
    normalizedPath === TOOL_INPUT_SCHEMA_FILE ||
    normalizedPath === TOOL_OUTPUT_SCHEMA_FILE ||
    normalizedPath === TOOL_EXAMPLES_FILE
  );
}

export function publishToolCatalogMetadataChange(source: DocumentFileSource) {
  if (source.kind !== "tool-folder") return;
  const toolFolderKey = parseToolFolderWorkspaceKey(source.key);
  if (!toolFolderKey) return;
  publishToolCatalogChange({
    ...toolFolderKey,
    kind: "metadata",
  });
}

function buildToolDashboardPlaceholder(title: string, view: ToolDashboardView): Record<string, unknown> {
  if (view === "basics") {
    return {
      registration_name: title,
      input_schema: {
        properties: {},
        required: [],
        type: "object",
      },
    };
  }
  if (view === "examples") {
    return {
      registration_name: title,
      examples: [],
    };
  }
  return {};
}

function parseJsonObject(content: string, filename: string): Record<string, unknown> {
  try {
    const payload = JSON.parse(stripJsonBom(content)) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error(`${filename} 必须是 JSON 对象。`);
    }
    return payload as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error(`${filename} JSON 解析失败。`);
  }
}

function parseJsonArray(content: string, filename: string): unknown[] {
  try {
    const payload = JSON.parse(stripJsonBom(content)) as unknown;
    if (!Array.isArray(payload)) {
      throw new Error(`${filename} 必须是 JSON 数组。`);
    }
    return payload;
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error(`${filename} JSON 解析失败。`);
  }
}

function expectJsonObjectValue(value: unknown, filename: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${filename} 必须是 JSON 对象。`);
  }
  return value as Record<string, unknown>;
}

function expectJsonArrayValue(value: unknown, filename: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${filename} 必须是 JSON 数组。`);
  }
  return value;
}

function formatDashboardJson(value: unknown) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function stripJsonBom(content: string) {
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

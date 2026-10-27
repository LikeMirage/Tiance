import { getProjectFileContent } from "../../../services/project/getProjectFileContent";
import { isJsonRecord, readRequiredString } from "./conversationClientToolValues";

const INDEX_PATH = "assets/scaffold.json";
const MANIFEST_PATH = ".tool/tool.json";
const REQUIRED_FILES = [
  MANIFEST_PATH, ".tool/input.schema.json", ".tool/output.schema.json",
  ".tool/examples.json", ".tool/permissions.json", "program/main.py",
];

export type ScaffoldFile = Readonly<{ path: string; content: string }>;
export type ToolProjectScaffold = Readonly<{
  version: string;
  documentation: string;
  files: readonly ScaffoldFile[];
}>;

/** Templates belong to the executed tool package, never to the current UI project. */
export async function loadToolProjectScaffold(
  toolProjectId: string,
  signal: AbortSignal,
): Promise<ToolProjectScaffold> {
  const response = await getProjectFileContent(toolProjectId, INDEX_PATH, { signal });
  const index: unknown = JSON.parse(response.content);
  if (!isJsonRecord(index) || index.version !== 1 || !Array.isArray(index.files)) {
    throw new Error("工具模板索引格式无效：assets/scaffold.json。");
  }
  const version = readRequiredString(index, "template_version");
  const documentation = relativePath(readRequiredString(index, "documentation"));
  const destinations = new Set<string>();
  const entries = index.files.map((entry: unknown) => {
    if (!isJsonRecord(entry)) throw new Error("模板文件条目必须是对象。");
    const source = relativePath(readRequiredString(entry, "source"));
    const target = relativePath(readRequiredString(entry, "target"));
    if (!source.startsWith("assets/")) throw new Error("模板来源必须在工具自身的 assets/ 内。");
    if (!/^(?:\.tool\/|program\/|assets\/|docs\/|tests\/|README\.md$)/.test(target)) {
      throw new Error(`模板不能写入此位置：${target}`);
    }
    const key = target.toLowerCase();
    if (destinations.has(key)) throw new Error(`模板目标重复：${target}`);
    destinations.add(key);
    return { source, target };
  });
  for (const required of [...REQUIRED_FILES, documentation]) {
    if (!entries.some((entry) => entry.target === required)) {
      throw new Error(`模板缺少必要文件：${required}`);
    }
  }
  // Read and check the complete package before creating a project. Read failure has no side effects.
  const files: ScaffoldFile[] = [];
  for (const entry of entries) {
    signal.throwIfAborted();
    const file = await getProjectFileContent(toolProjectId, entry.source, { signal });
    files.push({ path: entry.target, content: file.content });
  }
  validateStandardFiles(files);
  return { version, documentation, files };
}

export function instantiateToolProjectScaffold(
  scaffold: ToolProjectScaffold,
  name: string,
  callName: string,
): readonly ScaffoldFile[] {
  const manifestFile = scaffold.files.find((file) => file.path === MANIFEST_PATH)!;
  const manifest = JSON.parse(manifestFile.content);
  manifest.name = callName;
  manifest.registration_name = name;
  // Creation is always disabled, even if the source template was accidentally edited to enabled.
  manifest.state = { enabled: false };
  return [
    ...scaffold.files.filter((file) => file.path !== MANIFEST_PATH),
    { path: MANIFEST_PATH, content: `${JSON.stringify(manifest, null, 2)}\n` },
  ];
}

function relativePath(value: string): string {
  if (value !== value.trim() || /[\\:\x00-\x1f]/.test(value)
    || value.split("/").some((part) => !part || part === "." || part === ".." || /[. ]$/.test(part))
    || value.split("/").some((part) => part.toLowerCase() === ".tiance")) {
    throw new Error(`模板路径必须是项目内的相对路径：${value}`);
  }
  return value;
}

function validateStandardFiles(files: readonly ScaffoldFile[]) {
  const values = new Map<string, unknown>();
  for (const file of files) {
    if (REQUIRED_FILES.includes(file.path) && file.path.endsWith(".json")) {
      const parsed: unknown = JSON.parse(file.content);
      if (file.path === ".tool/examples.json" ? !Array.isArray(parsed) : !isJsonRecord(parsed)) {
        throw new Error(`标准模板格式无效：${file.path}`);
      }
      values.set(file.path, parsed);
    }
  }
  const manifest = values.get(MANIFEST_PATH) as Record<string, unknown>;
  const runtime = manifest.runtime;
  if (!isJsonRecord(runtime) || runtime.type !== "python" || runtime.entry !== "program/main.py"
    || !Number.isSafeInteger(runtime.timeout_seconds) || Number(runtime.timeout_seconds) < 1) {
    throw new Error("空白模板必须声明 program/main.py 和正整数超时。");
  }
  if (!isJsonRecord(manifest.execution) || typeof manifest.execution.parallel !== "boolean"
    || !isJsonRecord(manifest.loading) || typeof manifest.loading.dynamic !== "boolean") {
    throw new Error("空白模板必须明确声明并发和动态加载开关。");
  }
  const input = values.get(".tool/input.schema.json") as Record<string, unknown>;
  if (input.type !== "object" || !isJsonRecord(input.properties)) {
    throw new Error("空白模板的输入 Schema 必须声明 object 和 properties。");
  }
}

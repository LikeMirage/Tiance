import type { FileWorkspaceBrowserNode } from "../../../features/file-workspace/model/fileWorkspaceBrowserTreeModel";

const TOOL_ENTRY_FILE_EXTENSIONS = new Set([
  ".bash",
  ".bat",
  ".c",
  ".cc",
  ".cjs",
  ".cmd",
  ".cpp",
  ".cs",
  ".cxx",
  ".dart",
  ".fish",
  ".fs",
  ".fsx",
  ".go",
  ".java",
  ".jl",
  ".js",
  ".jsx",
  ".kt",
  ".kts",
  ".lua",
  ".mjs",
  ".php",
  ".pl",
  ".ps1",
  ".py",
  ".pyw",
  ".r",
  ".rb",
  ".rs",
  ".scala",
  ".sh",
  ".swift",
  ".ts",
  ".tsx",
  ".zsh",
]);

export function collectToolEntryFilePaths(rootNodes: FileWorkspaceBrowserNode[]) {
  return flattenToolEntryFilePaths(rootNodes)
    .sort((left, right) => left.localeCompare(right));
}

function flattenToolEntryFilePaths(nodes: FileWorkspaceBrowserNode[]): string[] {
  const result: string[] = [];
  for (const node of nodes) {
    if (node.kind === "file" && isToolProgramFile(node)) {
      result.push(node.path);
      continue;
    }
    if (node.kind === "folder" && node.children.length > 0) {
      result.push(...flattenToolEntryFilePaths(node.children));
    }
  }
  return result;
}

function isToolProgramFile(node: FileWorkspaceBrowserNode) {
  const normalizedPath = node.path.replace(/\\/g, "/").replace(/^\/+/, "");
  if (normalizedPath.startsWith(".tool/") || normalizedPath.startsWith("assets/")) {
    return false;
  }

  const extensionStart = node.name.lastIndexOf(".");
  if (extensionStart <= 0) {
    return false;
  }
  return TOOL_ENTRY_FILE_EXTENSIONS.has(node.name.slice(extensionStart).toLowerCase());
}

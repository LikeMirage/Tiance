import type {
  FileWorkspaceEntryKind,
  FileWorkspaceNode,
} from "../../../entities/file-workspace/model/fileWorkspace";
import { createUuid } from "../../../shared/model/createUuid";

export type FileWorkspaceBrowserNode = {
  id: string;
  name: string;
  path: string;
  kind: FileWorkspaceEntryKind;
  hasChildren: boolean;
  children: FileWorkspaceBrowserNode[];
  isChildrenLoaded: boolean;
  mtimeMs?: number | null;
  isPendingCreate?: boolean;
  pendingParentPath?: string | null;
};

export function mapFileWorkspaceNode(node: FileWorkspaceNode): FileWorkspaceBrowserNode {
  const path = normalizeWorkspacePath(node.path);
  return {
    id: path,
    name: node.name,
    path,
    kind: node.kind,
    hasChildren: node.has_children,
    children: node.children.map(mapFileWorkspaceNode),
    isChildrenLoaded: node.kind === "file" || !node.has_children || node.children.length > 0,
    mtimeMs: node.mtime_ms ?? null,
  };
}

export function preserveLoadedChildren(
  nodes: FileWorkspaceBrowserNode[],
  previousNodes: FileWorkspaceBrowserNode[],
): FileWorkspaceBrowserNode[] {
  return nodes.map((node) => {
    if (node.kind !== "folder") return node;
    const previousNode = findNode(previousNodes, node.id);
    if (!previousNode || previousNode.kind !== "folder" || !previousNode.isChildrenLoaded) {
      return node;
    }
    return {
      ...node,
      children: previousNode.children,
      isChildrenLoaded: previousNode.isChildrenLoaded,
    };
  });
}

export function upsertNode(
  nodes: FileWorkspaceBrowserNode[],
  node: FileWorkspaceBrowserNode,
): FileWorkspaceBrowserNode[] {
  const parentPath = getParentWorkspacePath(node.path);
  if (!parentPath) {
    return upsertNodeInList(nodes, node);
  }

  const parentNode = findNode(nodes, parentPath);
  if (!parentNode || parentNode.kind !== "folder" || !parentNode.isChildrenLoaded) {
    return nodes;
  }

  return updateNodeChildren(
    nodes,
    parentNode.id,
    upsertNodeInList(parentNode.children, node),
    true,
  );
}

export function normalizeWorkspacePath(path: string): string {
  return path.trim().replace(/^\/+|\/+$/g, "");
}

export function getParentWorkspacePath(path: string): string | null {
  const normalizedPath = normalizeWorkspacePath(path);
  const slashIndex = normalizedPath.lastIndexOf("/");
  if (slashIndex <= 0) return null;
  return normalizedPath.slice(0, slashIndex);
}

export function getAncestorFolderPaths(path: string): string[] {
  const segments = normalizeWorkspacePath(path).split("/").filter(Boolean);
  const folderPaths: string[] = [];
  let currentPath = "";

  for (let index = 0; index < segments.length - 1; index += 1) {
    currentPath = currentPath ? `${currentPath}/${segments[index]}` : segments[index];
    folderPaths.push(currentPath);
  }

  return folderPaths;
}

export function findNode(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
): FileWorkspaceBrowserNode | null {
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const found = findNode(node.children, nodeId);
    if (found) return found;
  }
  return null;
}

export function updateNodeChildren(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
  children: FileWorkspaceBrowserNode[],
  isChildrenLoaded: boolean,
): FileWorkspaceBrowserNode[] {
  return nodes.map((node) => {
    if (node.id === nodeId) {
      return {
        ...node,
        children: preserveLoadedChildren(children, node.children),
        isChildrenLoaded,
      };
    }
    if (node.children.length > 0) {
      return {
        ...node,
        children: updateNodeChildren(node.children, nodeId, children, isChildrenLoaded),
      };
    }
    return node;
  });
}

export function removeNode(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
): FileWorkspaceBrowserNode[] {
  return nodes
    .filter((node) => node.id !== nodeId)
    .map((node) => ({
      ...node,
      children: node.children.length > 0 ? removeNode(node.children, nodeId) : node.children,
    }));
}

export function insertNode(
  nodes: FileWorkspaceBrowserNode[],
  parentNodeId: string | null,
  childNode: FileWorkspaceBrowserNode,
): FileWorkspaceBrowserNode[] {
  if (!parentNodeId) {
    const nextNodes = [...nodes, childNode];
    return childNode.isPendingCreate ? nextNodes : nextNodes.sort(compareNodes);
  }
  return nodes.map((node) => {
    if (node.id === parentNodeId) {
      const nextChildren = [...node.children, childNode];
      return {
        ...node,
        hasChildren: true,
        isChildrenLoaded: true,
        children: childNode.isPendingCreate ? nextChildren : nextChildren.sort(compareNodes),
      };
    }
    if (node.children.length > 0) {
      return {
        ...node,
        children: insertNode(node.children, parentNodeId, childNode),
      };
    }
    return node;
  });
}

export function replaceNode(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
  replacement: FileWorkspaceBrowserNode,
): FileWorkspaceBrowserNode[] {
  return nodes.map((node) => {
    if (node.id === nodeId) {
      if (node.kind === "folder" && replacement.kind === "folder" && node.isChildrenLoaded) {
        return {
          ...replacement,
          children: node.children,
          isChildrenLoaded: true,
        };
      }
      return replacement;
    }
    if (node.children.length > 0) {
      return {
        ...node,
        children: replaceNode(node.children, nodeId, replacement),
      };
    }
    return node;
  }).sort(compareNodes);
}

export function collectAllFolderIds(
  nodes: FileWorkspaceBrowserNode[],
  target: Set<string>,
): void {
  for (const node of nodes) {
    if (node.kind === "folder") {
      target.add(node.id);
      collectAllFolderIds(node.children, target);
    }
  }
}

export function validateSiblingEntryName(
  nodes: FileWorkspaceBrowserNode[],
  node: FileWorkspaceBrowserNode,
  name: string,
): string | null {
  if (!name) {
    return "文件名称不能为空。";
  }
  if (name.includes("/") || name.includes("\\")) {
    return "文件名称不能包含路径分隔符。";
  }
  if (name === "." || name === "..") {
    return "不允许使用 . 或 .. 作为名称。";
  }

  const siblingNodes = findSiblingNodes(nodes, node.id);
  const normalizedName = name.toLocaleLowerCase();
  const duplicated = siblingNodes.some((sibling) =>
    sibling.id !== node.id && sibling.name.toLocaleLowerCase() === normalizedName,
  );
  return duplicated ? "同层级已存在同名文件或文件夹。" : null;
}

export function defaultEntryName(kind: FileWorkspaceEntryKind): string {
  return kind === "folder" ? "新建文件夹" : "新建文件.txt";
}

export function nextDefaultEntryName(
  kind: FileWorkspaceEntryKind,
  siblingNodes: FileWorkspaceBrowserNode[],
): string {
  const baseName = defaultEntryName(kind);
  const existingNames = new Set(
    siblingNodes.map((node) => node.name.toLocaleLowerCase()),
  );
  if (!existingNames.has(baseName.toLocaleLowerCase())) {
    return baseName;
  }

  const nameParts = splitDefaultEntryName(kind);
  for (let index = 1; index < Number.MAX_SAFE_INTEGER; index += 1) {
    const candidateName = `${nameParts.stem}${index}${nameParts.extension}`;
    if (!existingNames.has(candidateName.toLocaleLowerCase())) {
      return candidateName;
    }
  }

  return `${nameParts.stem}${createUuid()}${nameParts.extension}`;
}

export function buildPendingNodeId(kind: FileWorkspaceEntryKind): string {
  return `__pending_${kind}_${createUuid()}`;
}

export function resolveCreateParent(
  nodes: FileWorkspaceBrowserNode[],
  selectedNodeId: string | null,
): string | undefined {
  if (!selectedNodeId) return undefined;
  const node = findNode(nodes, selectedNodeId);
  if (!node) return undefined;
  if (node.kind === "folder") return node.id;
  return findParentFolderId(nodes, node.id);
}

export function resolveTargetParentPath(node: FileWorkspaceBrowserNode | null): string | null {
  if (!node) return null;
  if (node.kind === "folder") return node.path;
  const lastSlashIndex = node.path.lastIndexOf("/");
  return lastSlashIndex === -1 ? null : node.path.slice(0, lastSlashIndex);
}

export function replaceNodeIdPrefix(
  nodeIds: Set<string>,
  oldPrefix: string,
  newPrefix: string,
): Set<string> {
  const next = new Set<string>();
  const oldChildPrefix = `${oldPrefix}/`;
  for (const nodeId of nodeIds) {
    if (nodeId === oldPrefix) {
      next.add(newPrefix);
      continue;
    }
    if (nodeId.startsWith(oldChildPrefix)) {
      next.add(`${newPrefix}/${nodeId.slice(oldChildPrefix.length)}`);
      continue;
    }
    next.add(nodeId);
  }
  return next;
}

function upsertNodeInList(
  nodes: FileWorkspaceBrowserNode[],
  node: FileWorkspaceBrowserNode,
): FileWorkspaceBrowserNode[] {
  const existingIndex = nodes.findIndex((item) => item.id === node.id);
  if (existingIndex === -1) {
    return [...nodes, node].sort(compareNodes);
  }

  const existingNode = nodes[existingIndex];
  const replacement =
    node.kind === "folder" && existingNode.kind === "folder" && existingNode.isChildrenLoaded
      ? { ...node, children: existingNode.children, isChildrenLoaded: true }
      : node;
  return nodes.map((item, index) => (index === existingIndex ? replacement : item)).sort(compareNodes);
}

function compareNodes(left: FileWorkspaceBrowserNode, right: FileWorkspaceBrowserNode): number {
  if (left.kind !== right.kind) {
    return left.kind === "folder" ? -1 : 1;
  }
  const leftName = left.name.toLowerCase();
  const rightName = right.name.toLowerCase();
  if (leftName < rightName) return -1;
  if (leftName > rightName) return 1;
  return 0;
}

function splitDefaultEntryName(kind: FileWorkspaceEntryKind) {
  if (kind === "folder") {
    return { stem: "新建文件夹", extension: "" };
  }

  return { stem: "新建文件", extension: ".txt" };
}

function findSiblingNodes(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
): FileWorkspaceBrowserNode[] {
  if (nodes.some((node) => node.id === nodeId)) {
    return nodes;
  }
  for (const node of nodes) {
    const found = findSiblingNodes(node.children, nodeId);
    if (found.length > 0) return found;
  }
  return [];
}

function findParentFolderId(
  nodes: FileWorkspaceBrowserNode[],
  nodeId: string,
): string | undefined {
  for (const node of nodes) {
    if (node.children.some((child) => child.id === nodeId)) return node.id;
    const found = findParentFolderId(node.children, nodeId);
    if (found) return found;
  }
  return undefined;
}

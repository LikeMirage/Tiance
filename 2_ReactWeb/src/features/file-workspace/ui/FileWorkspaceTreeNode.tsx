import { memo, useEffect, useRef } from "react";
import type { DragEvent, MouseEvent } from "react";

import type { FileWorkspaceBrowserNode } from "../model/fileWorkspaceBrowserTreeModel";
import type { UseFileWorkspaceBrowserResult } from "../model/fileWorkspaceBrowserTypes";
import type { FileWorkspaceNodeDragDataConfig } from "./FileWorkspaceTree";
import { FileWorkspaceInlineRenameInput } from "./FileWorkspaceInlineRenameInput";
import { FileWorkspaceNodeContextMenu } from "./FileWorkspaceContextMenus";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
} from "./FileWorkspaceTreeIcons";
import type {
  FileWorkspaceClipboardState,
  FileWorkspaceContextMenuState,
} from "./fileWorkspaceTreeUiTypes";
import { getFileWorkspaceTreeItemId } from "./fileWorkspaceTreeUiTypes";

type FileWorkspaceTreeNodeProps = {
  browser: UseFileWorkspaceBrowserResult;
  clipboard: FileWorkspaceClipboardState;
  contextMenu: FileWorkspaceContextMenuState;
  depth: number;
  node: FileWorkspaceBrowserNode;
  nodeDragData?: FileWorkspaceNodeDragDataConfig;
  onCreateFile: (parentId?: string) => void;
  onCreateFolder: (parentId?: string) => void;
  onNodeRenamed?: (previousNode: FileWorkspaceBrowserNode, renamedNode: FileWorkspaceBrowserNode) => void;
  onOpenFile?: (node: FileWorkspaceBrowserNode) => void;
  onCopyNodesToSystemClipboard?: (nodes: FileWorkspaceBrowserNode[]) => Promise<string[] | null>;
  onPasteFromSystemClipboard?: (
    clipboard: FileWorkspaceClipboardState,
  ) => Promise<"internal" | "handled">;
  onReferenceNode?: (node: FileWorkspaceBrowserNode) => void;
  onRenameStart: (nodeId: string) => void;
  setClipboard: (state: FileWorkspaceClipboardState) => void;
  setContextMenu: (state: FileWorkspaceContextMenuState) => void;
  setPendingDeleteNodeIds: (nodeIds: string[] | null) => void;
};

type FileWorkspaceNodeContextMenuState =
  Extract<FileWorkspaceContextMenuState, { mode: "node" }> | null;

export const FileWorkspaceTreeNode = memo(function FileWorkspaceTreeNode({
  browser,
  clipboard,
  contextMenu,
  depth,
  node,
  nodeDragData,
  onCreateFile,
  onCreateFolder,
  onNodeRenamed,
  onOpenFile,
  onCopyNodesToSystemClipboard,
  onPasteFromSystemClipboard,
  onReferenceNode,
  onRenameStart,
  setClipboard,
  setContextMenu,
  setPendingDeleteNodeIds,
}: FileWorkspaceTreeNodeProps) {
  const autoLoadRequestRef = useRef<string | null>(null);
  const isExpanded = browser.expandedNodeIds.has(node.id);
  const isSelected = browser.selectedNodeIds.has(node.id);
  const isLoadingChildren = browser.isLoadingNodeIds.has(node.id);
  const isEditing = browser.editingNodeId === node.id;
  const dragData = !isEditing ? nodeDragData?.getData(node) ?? null : null;
  const nodeContextMenu =
    contextMenu?.mode === "node" && contextMenu.nodeId === node.id
      ? contextMenu
      : null;
  const isContextMenuTarget = Boolean(nodeContextMenu && !isSelected);
  const rowClassName = [
    "fwt-row",
    isSelected ? "fwt-row--selected" : "",
    isContextMenuTarget ? "fwt-row--context-target" : "",
    isEditing ? "fwt-row--editing" : "",
  ].filter(Boolean).join(" ");

  useEffect(() => {
    if (node.kind !== "folder") return;
    if (!isExpanded || node.isChildrenLoaded) {
      autoLoadRequestRef.current = null;
      return;
    }
    if (!node.hasChildren || isLoadingChildren) return;
    if (autoLoadRequestRef.current === node.id) return;
    autoLoadRequestRef.current = node.id;
    void browser.loadFolderChildren(node.id);
  }, [
    browser.loadFolderChildren,
    isExpanded,
    isLoadingChildren,
    node.hasChildren,
    node.id,
    node.isChildrenLoaded,
    node.kind,
  ]);

  const handleContextMenu = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (browser.selectedNodeIds.has(node.id) && browser.selectedNodeIds.size > 1) {
      setContextMenu({
        mode: "selection",
        nodeIds: [...browser.selectedNodeIds],
        x: event.clientX,
        y: event.clientY,
      });
      return;
    }
    setContextMenu({
      mode: "node",
      nodeId: node.id,
      x: event.clientX,
      y: event.clientY,
    });
  };

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    if (!nodeDragData || !dragData) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(nodeDragData.mimeType, dragData);
    event.dataTransfer.setData("text/plain", node.path);
  };

  return (
    <div role="none">
      <div
        id={getFileWorkspaceTreeItemId(node.id)}
        role="treeitem"
        aria-expanded={node.kind === "folder" ? isExpanded : undefined}
        aria-level={depth + 1}
        aria-selected={isSelected}
        className={rowClassName}
        draggable={Boolean(dragData)}
        style={{ paddingLeft: depth * 14 + 6 }}
        onPointerDown={(event) => {
          event.currentTarget.closest<HTMLElement>(".fwt-tree")?.focus({
            preventScroll: true,
          });
        }}
        onClick={(event) => {
          if (event.ctrlKey || event.metaKey) {
            browser.selectNode(node.id, { toggle: true });
            return;
          }
          browser.selectNode(node.id);
          if (node.kind === "folder") {
            browser.toggleNode(node.id);
          } else {
            onOpenFile?.(node);
          }
        }}
        onContextMenu={handleContextMenu}
        onDragStart={handleDragStart}
      >
        {node.kind === "folder" ? (
          <span className="fwt-arrow">
            {isLoadingChildren ? (
              <span className="fwt-loading-dot" />
            ) : isExpanded ? (
              <ChevronDownIcon />
            ) : (
              <ChevronRightIcon />
            )}
          </span>
        ) : null}

        <span className="fwt-icon">
          {node.kind === "folder" ? (
            isExpanded ? (
              <FolderOpenIcon />
            ) : (
              <FolderIcon />
            )
          ) : (
            <FileIcon />
          )}
        </span>

        {isEditing ? (
          <FileWorkspaceInlineRenameInput
            initialName={node.name}
            onCancel={browser.cancelInlineEdit}
            onCommit={async (newName) => {
              try {
                const renamedNode = await browser.renameNode(node.id, newName);
                if (renamedNode) {
                  onNodeRenamed?.(node, renamedNode);
                }
              } catch {
                // 重命名失败时输入框保持编辑状态，由输入组件显示错误。
              }
            }}
          />
        ) : (
          <span className="fwt-name">{node.name}</span>
        )}
      </div>

      {isExpanded && node.children.length > 0 ? (
        <div role="group">
          {node.children.map((child) => (
            <FileWorkspaceTreeNode
              key={child.id}
              browser={browser}
              clipboard={clipboard}
              contextMenu={contextMenu}
              depth={depth + 1}
              node={child}
              nodeDragData={nodeDragData}
              onCreateFile={onCreateFile}
              onCreateFolder={onCreateFolder}
              onNodeRenamed={onNodeRenamed}
              onOpenFile={onOpenFile}
              onCopyNodesToSystemClipboard={onCopyNodesToSystemClipboard}
              onPasteFromSystemClipboard={onPasteFromSystemClipboard}
              onReferenceNode={onReferenceNode}
              onRenameStart={onRenameStart}
              setClipboard={setClipboard}
              setContextMenu={setContextMenu}
              setPendingDeleteNodeIds={setPendingDeleteNodeIds}
            />
          ))}
        </div>
      ) : null}

      {nodeContextMenu ? (
        <FileWorkspaceNodeContextMenu
          browser={browser}
          clipboard={clipboard}
          contextMenu={nodeContextMenu}
          isExpanded={isExpanded}
          node={node}
          onCreateFile={onCreateFile}
          onCreateFolder={onCreateFolder}
          onOpenFile={onOpenFile}
          copyNodesToSystemClipboard={onCopyNodesToSystemClipboard}
          resolveSystemClipboardPaste={onPasteFromSystemClipboard}
          onReferenceNode={onReferenceNode}
          onRenameStart={onRenameStart}
          setClipboard={setClipboard}
          setContextMenu={setContextMenu}
          setPendingDeleteNodeIds={setPendingDeleteNodeIds}
        />
      ) : null}
    </div>
  );
}, areFileWorkspaceTreeNodePropsEqual);

function areFileWorkspaceTreeNodePropsEqual(
  previous: FileWorkspaceTreeNodeProps,
  next: FileWorkspaceTreeNodeProps,
) {
  const previousNodeMenu = getNodeContextMenuInSubtree(previous.contextMenu, previous.node);
  const nextNodeMenu = getNodeContextMenuInSubtree(next.contextMenu, next.node);
  const shouldCompareClipboard = previousNodeMenu !== null || nextNodeMenu !== null;

  return (
    previous.node === next.node &&
    previous.depth === next.depth &&
    (!shouldCompareClipboard || areClipboardStatesEqual(previous.clipboard, next.clipboard)) &&
    previous.onCreateFile === next.onCreateFile &&
    previous.onCreateFolder === next.onCreateFolder &&
    previous.nodeDragData === next.nodeDragData &&
    previous.onNodeRenamed === next.onNodeRenamed &&
    previous.onOpenFile === next.onOpenFile &&
    previous.onCopyNodesToSystemClipboard === next.onCopyNodesToSystemClipboard &&
    previous.onPasteFromSystemClipboard === next.onPasteFromSystemClipboard &&
    previous.onReferenceNode === next.onReferenceNode &&
    previous.onRenameStart === next.onRenameStart &&
    previous.setClipboard === next.setClipboard &&
    previous.setContextMenu === next.setContextMenu &&
    previous.setPendingDeleteNodeIds === next.setPendingDeleteNodeIds &&
    previous.browser.cancelInlineEdit === next.browser.cancelInlineEdit &&
    previous.browser.renameNode === next.browser.renameNode &&
    previous.browser.selectNode === next.browser.selectNode &&
    previous.browser.toggleNode === next.browser.toggleNode &&
    previous.browser.selectedNodeIds.has(previous.node.id) ===
      next.browser.selectedNodeIds.has(next.node.id) &&
    previous.browser.expandedNodeIds.has(previous.node.id) ===
      next.browser.expandedNodeIds.has(next.node.id) &&
    previous.browser.isLoadingNodeIds.has(previous.node.id) ===
      next.browser.isLoadingNodeIds.has(next.node.id) &&
    previous.browser.loadFolderChildren === next.browser.loadFolderChildren &&
    (previous.browser.editingNodeId === previous.node.id) ===
      (next.browser.editingNodeId === next.node.id) &&
    areNodeContextMenusEqual(previousNodeMenu, nextNodeMenu)
  );
}

function areClipboardStatesEqual(
  previous: FileWorkspaceClipboardState,
  next: FileWorkspaceClipboardState,
) {
  if (previous === next) return true;
  if (!previous || !next) return false;
  return previous.mode === next.mode
    && areStringArraysEqual(previous.nodeIds, next.nodeIds)
    && areStringArraysEqual(previous.systemSourcePaths ?? [], next.systemSourcePaths ?? []);
}

function areNodeContextMenusEqual(
  previous: FileWorkspaceNodeContextMenuState,
  next: FileWorkspaceNodeContextMenuState,
) {
  if (previous === next) return true;
  if (!previous || !next) return false;
  return (
    previous.mode === next.mode &&
    previous.nodeId === next.nodeId &&
    previous.x === next.x &&
    previous.y === next.y
  );
}

function areStringArraysEqual(previous: string[], next: string[]) {
  if (previous === next) return true;
  if (previous.length !== next.length) return false;
  return previous.every((item, index) => item === next[index]);
}

function getNodeContextMenu(
  contextMenu: FileWorkspaceContextMenuState,
  nodeId: string,
) {
  return contextMenu?.mode === "node" && contextMenu.nodeId === nodeId
    ? contextMenu
    : null;
}

function getNodeContextMenuInSubtree(
  contextMenu: FileWorkspaceContextMenuState,
  node: FileWorkspaceBrowserNode,
): FileWorkspaceNodeContextMenuState {
  const nodeContextMenu = getNodeContextMenu(contextMenu, node.id);
  if (nodeContextMenu || node.kind !== "folder") {
    return nodeContextMenu;
  }

  for (const child of node.children) {
    const childContextMenu = getNodeContextMenuInSubtree(contextMenu, child);
    if (childContextMenu) {
      return childContextMenu;
    }
  }

  return null;
}

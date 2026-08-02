import { useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";

import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import {
  findNode,
  type FileWorkspaceBrowserNode,
} from "../model/fileWorkspaceBrowserTreeModel";
import type { UseFileWorkspaceBrowserResult } from "../model/fileWorkspaceBrowserTypes";
import {
  copyToClipboard,
  deleteNodes,
  getActionNodeIds,
  pasteClipboard,
} from "./fileWorkspaceTreeActions";
import {
  FileWorkspaceRootContextMenu,
  FileWorkspaceSelectionContextMenu,
} from "./FileWorkspaceContextMenus";
import { FileWorkspaceTreeNode } from "./FileWorkspaceTreeNode";
import type {
  FileWorkspaceClipboardState,
  FileWorkspaceContextMenuState,
} from "./fileWorkspaceTreeUiTypes";
import { getFileWorkspaceTreeItemId } from "./fileWorkspaceTreeUiTypes";
import "./file-workspace-tree.css";

export type FileWorkspaceTreeProps = {
  emptyMessage?: string;
  browser: UseFileWorkspaceBrowserResult;
  initialLoadingMessage?: string | null;
  nodeDragData?: FileWorkspaceNodeDragDataConfig;
  rootAriaLabel?: string;
  treeAriaLabel?: string;
  onCreateFile: (parentId?: string) => void;
  onCreateFolder: (parentId?: string) => void;
  onDeleteNode: (nodeId: string) => Promise<void> | void;
  onNodeRenamed?: (previousNode: FileWorkspaceBrowserNode, renamedNode: FileWorkspaceBrowserNode) => void;
  onOpenFile?: (node: FileWorkspaceBrowserNode) => void;
  onCopyNodesToSystemClipboard?: (nodes: FileWorkspaceBrowserNode[]) => Promise<string[] | null>;
  onPasteFromSystemClipboard?: (
    clipboard: FileWorkspaceClipboardState,
  ) => Promise<"internal" | "handled">;
  onReferenceNode?: (node: FileWorkspaceBrowserNode) => void;
  onRenameStart: (nodeId: string) => void;
};

export type FileWorkspaceNodeDragDataConfig = {
  mimeType: string;
  getData: (node: FileWorkspaceBrowserNode) => string | null;
};

export function FileWorkspaceTree({
  browser,
  emptyMessage,
  initialLoadingMessage,
  nodeDragData,
  onCreateFile,
  onCreateFolder,
  onDeleteNode,
  onNodeRenamed,
  onOpenFile,
  onCopyNodesToSystemClipboard,
  onPasteFromSystemClipboard,
  onReferenceNode,
  onRenameStart,
  rootAriaLabel,
  treeAriaLabel,
}: FileWorkspaceTreeProps) {
  const { t } = useI18n();
  const resolvedEmptyMessage = emptyMessage ?? t("fileWorkspace.empty");
  const resolvedInitialLoadingMessage =
    initialLoadingMessage === undefined ? t("fileWorkspace.loading") : initialLoadingMessage;
  const resolvedRootAriaLabel = rootAriaLabel ?? t("fileWorkspace.root");
  const resolvedTreeAriaLabel = treeAriaLabel ?? t("fileWorkspace.files");
  const [contextMenu, setContextMenu] =
    useState<FileWorkspaceContextMenuState>(null);
  const [clipboard, setClipboard] =
    useState<FileWorkspaceClipboardState>(null);
  const [pendingDeleteNodeIds, setPendingDeleteNodeIds] =
    useState<string[] | null>(null);
  const [deleteFailures, setDeleteFailures] =
    useState<DeleteFailureNotice[] | null>(null);

  const hasTreeData = browser.treeData.length > 0;
  const rootContextMenu = contextMenu?.mode === "root" ? contextMenu : null;
  const selectionContextMenu =
    contextMenu?.mode === "selection" ? contextMenu : null;

  const handleTreeBackgroundClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!isTreeBackgroundEvent(event)) {
      return;
    }
    browser.selectRoot();
    setContextMenu(null);
  };

  const handleTreeBackgroundContextMenu = (event: MouseEvent<HTMLDivElement>) => {
    if (!isTreeBackgroundEvent(event)) {
      return;
    }
    event.preventDefault();
    browser.selectRoot();
    setContextMenu({ mode: "root", x: event.clientX, y: event.clientY });
  };

  const handleConfirmedDelete = async (nodeIds: string[]) => {
    const pathsByNodeId = new Map(
      nodeIds.map((nodeId) => [
        nodeId,
        findNode(browser.treeData, nodeId)?.path ?? nodeId,
      ]),
    );
    setDeleteFailures(null);
    const failures = await deleteNodes(nodeIds, onDeleteNode);
    if (failures.length === 0) {
      return;
    }

    browser.refreshTree();
    setDeleteFailures(
      failures.map(({ error, nodeId }) => ({
        message: getDeleteFailureMessage(
          error,
          t("fileWorkspace.delete.failedFallback"),
        ),
        path: pathsByNodeId.get(nodeId) ?? nodeId,
      })),
    );
  };

  const handleTreeKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isEditableKeyboardTarget(event.target) || event.altKey) {
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "c") {
      const nodeIds = browser.selectedNodeId && browser.selectedNodeIds.has(browser.selectedNodeId)
        ? getActionNodeIds(browser, [...browser.selectedNodeIds])
        : [];
      if (nodeIds.length === 0) return;
      event.preventDefault();
      copyToClipboard(browser, nodeIds, setClipboard, onCopyNodesToSystemClipboard);
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "v") {
      event.preventDefault();
      void pasteClipboard(
        browser,
        clipboard,
        null,
        setClipboard,
        onPasteFromSystemClipboard,
      ).catch(() => undefined);
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      return;
    }

    const visibleNodes = collectVisibleNodes(browser.treeData, browser.expandedNodeIds);
    if (visibleNodes.length === 0) {
      return;
    }

    const currentIndex = browser.selectedNodeId
      ? visibleNodes.findIndex((item) => item.node.id === browser.selectedNodeId)
      : -1;
    const currentItem = currentIndex >= 0 ? visibleNodes[currentIndex] : null;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextIndex = currentIndex < 0 ? 0 : Math.min(currentIndex + 1, visibleNodes.length - 1);
      browser.selectNode(visibleNodes[nextIndex].node.id);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      const nextIndex = currentIndex < 0 ? 0 : Math.max(currentIndex - 1, 0);
      browser.selectNode(visibleNodes[nextIndex].node.id);
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      browser.selectNode(visibleNodes[0].node.id);
      return;
    }

    if (event.key === "End") {
      event.preventDefault();
      browser.selectNode(visibleNodes[visibleNodes.length - 1].node.id);
      return;
    }

    if (!currentItem) {
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      if (currentItem.node.kind !== "folder") {
        return;
      }
      if (!browser.expandedNodeIds.has(currentItem.node.id)) {
        browser.toggleNode(currentItem.node.id);
        return;
      }
      const firstChild = visibleNodes[currentIndex + 1];
      if (firstChild?.parentId === currentItem.node.id) {
        browser.selectNode(firstChild.node.id);
      }
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (currentItem.node.kind === "folder" && browser.expandedNodeIds.has(currentItem.node.id)) {
        browser.toggleNode(currentItem.node.id);
        return;
      }
      if (currentItem.parentId) {
        browser.selectNode(currentItem.parentId);
      }
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      if (currentItem.node.kind === "folder") {
        browser.toggleNode(currentItem.node.id);
      } else {
        onOpenFile?.(currentItem.node);
      }
      return;
    }

    if (event.key === "F2") {
      event.preventDefault();
      onRenameStart(currentItem.node.id);
      return;
    }

    if (event.key === "Delete") {
      event.preventDefault();
      const nodeIds = browser.selectedNodeIds.has(currentItem.node.id) && browser.selectedNodeIds.size > 1
        ? getActionNodeIds(browser, [...browser.selectedNodeIds])
        : getActionNodeIds(browser, [currentItem.node.id]);
      if (nodeIds.length === 0) {
        return;
      }
      setPendingDeleteNodeIds(nodeIds);
    }
  };

  if (browser.isLoading && !hasTreeData) {
    if (resolvedInitialLoadingMessage !== null) {
      return <div className="fwt-status">{resolvedInitialLoadingMessage}</div>;
    }
  }

  if (browser.errorMessage && !hasTreeData) {
    return (
      <div className="fwt-status fwt-status--error">
        <span>{browser.errorMessage}</span>
        <button
          className="fwt-status-action"
          type="button"
          onClick={browser.refreshTree}
        >
          {t("common.actions.retry")}
        </button>
      </div>
    );
  }

  if (!hasTreeData) {
    return (
      <div
        className="fwt-shell"
        onClick={handleTreeBackgroundClick}
        onContextMenu={handleTreeBackgroundContextMenu}
      >
        <div
          className="fwt-tree"
          role="tree"
          aria-label={resolvedRootAriaLabel}
          tabIndex={0}
        >
          {!browser.isLoading ? <div className="fwt-status">{resolvedEmptyMessage}</div> : null}
          <div className="fwt-root-hit-area" aria-hidden="true" />
        </div>
        {rootContextMenu ? (
          <FileWorkspaceRootContextMenu
            browser={browser}
            clipboard={clipboard}
            contextMenu={rootContextMenu}
            onCreateFile={onCreateFile}
            onCreateFolder={onCreateFolder}
            setClipboard={setClipboard}
            setContextMenu={setContextMenu}
            resolveSystemClipboardPaste={onPasteFromSystemClipboard}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="fwt-shell"
      onClick={handleTreeBackgroundClick}
      onContextMenu={handleTreeBackgroundContextMenu}
    >
      {browser.errorMessage ? (
        <div className="fwt-inline-status fwt-inline-status--error">
          <span>{browser.errorMessage}</span>
          <button
            className="fwt-inline-status-action"
            type="button"
            onClick={browser.refreshTree}
          >
            {t("common.actions.retry")}
          </button>
        </div>
      ) : null}
      <div
        className="fwt-tree"
        role="tree"
        aria-label={resolvedTreeAriaLabel}
        aria-activedescendant={
          browser.selectedNodeId ? getFileWorkspaceTreeItemId(browser.selectedNodeId) : undefined
        }
        tabIndex={0}
        onKeyDown={handleTreeKeyDown}
      >
        {browser.treeData.map((node) => (
          <FileWorkspaceTreeNode
            key={node.id}
            browser={browser}
            clipboard={clipboard}
            contextMenu={contextMenu}
            depth={0}
            node={node}
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
        <div className="fwt-root-hit-area" aria-hidden="true" />
        {rootContextMenu ? (
          <FileWorkspaceRootContextMenu
            browser={browser}
            clipboard={clipboard}
            contextMenu={rootContextMenu}
            onCreateFile={onCreateFile}
            onCreateFolder={onCreateFolder}
            setClipboard={setClipboard}
            setContextMenu={setContextMenu}
            resolveSystemClipboardPaste={onPasteFromSystemClipboard}
          />
        ) : null}
        {selectionContextMenu ? (
          <FileWorkspaceSelectionContextMenu
            browser={browser}
            contextMenu={selectionContextMenu}
            setClipboard={setClipboard}
            setContextMenu={setContextMenu}
            setPendingDeleteNodeIds={setPendingDeleteNodeIds}
            copyNodesToSystemClipboard={onCopyNodesToSystemClipboard}
          />
        ) : null}
      </div>

      {pendingDeleteNodeIds ? (
        <ConfirmModal
          danger
          title={t("fileWorkspace.delete.title")}
          message={
            pendingDeleteNodeIds.length > 1
              ? t("fileWorkspace.delete.multiple", { count: pendingDeleteNodeIds.length })
              : t("fileWorkspace.delete.single")
          }
          onCancel={() => setPendingDeleteNodeIds(null)}
          onConfirm={() => {
            const nodeIds = pendingDeleteNodeIds;
            setPendingDeleteNodeIds(null);
            void handleConfirmedDelete(nodeIds);
          }}
        />
      ) : null}

      {deleteFailures ? (
        <ConfirmModal
          confirmLabel={t("common.actions.close")}
          message={t("fileWorkspace.delete.failedMessage", {
            count: deleteFailures.length,
          })}
          onCancel={() => setDeleteFailures(null)}
          onConfirm={() => setDeleteFailures(null)}
          showCancel={false}
          title={t("fileWorkspace.delete.failedTitle")}
        >
          <ul className="fwt-delete-failure-list">
            {deleteFailures.map((failure, index) => (
              <li className="fwt-delete-failure-item" key={`${failure.path}-${index}`}>
                <span className="fwt-delete-failure-path">{failure.path}</span>
                <span className="fwt-delete-failure-reason">{failure.message}</span>
              </li>
            ))}
          </ul>
        </ConfirmModal>
      ) : null}
    </div>
  );
}

type DeleteFailureNotice = {
  message: string;
  path: string;
};

function getDeleteFailureMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  return fallback;
}

function isTreeBackgroundEvent(event: MouseEvent<HTMLElement>) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return target === event.currentTarget;
  }

  return !target.closest(".fwt-row") && !target.closest(".ds-context-menu");
}

type VisibleTreeNode = {
  node: FileWorkspaceBrowserNode;
  parentId: string | null;
};

function collectVisibleNodes(
  nodes: FileWorkspaceBrowserNode[],
  expandedNodeIds: Set<string>,
  parentId: string | null = null,
  output: VisibleTreeNode[] = [],
) {
  for (const node of nodes) {
    output.push({ node, parentId });
    if (node.kind === "folder" && expandedNodeIds.has(node.id)) {
      collectVisibleNodes(node.children, expandedNodeIds, node.id, output);
    }
  }

  return output;
}

function isEditableKeyboardTarget(target: EventTarget) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return Boolean(
    target.closest("input, textarea, select, button, [contenteditable='true']"),
  );
}

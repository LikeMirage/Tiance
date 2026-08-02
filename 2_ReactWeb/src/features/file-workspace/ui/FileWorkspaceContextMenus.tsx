import { flushSync } from "react-dom";

import type { FileWorkspaceBrowserNode } from "../model/fileWorkspaceBrowserTreeModel";
import { getParentWorkspacePath } from "../model/fileWorkspaceBrowserTreeModel";
import type { UseFileWorkspaceBrowserResult } from "../model/fileWorkspaceBrowserTypes";
import { useI18n } from "../../../shared/i18n";
import { ContextMenu, ContextMenuItem, ContextMenuSeparator } from "../../../shared/ui/context-menu";
import {
  copyToClipboard,
  getActionNodeIds,
  pasteClipboard,
} from "./fileWorkspaceTreeActions";
import type {
  FileWorkspaceClipboardState,
  FileWorkspaceContextMenuState,
} from "./fileWorkspaceTreeUiTypes";

type ContextMenuSetter = (state: FileWorkspaceContextMenuState) => void;
type ClipboardSetter = (state: FileWorkspaceClipboardState) => void;
type CopyNodesToSystemClipboard = (nodes: FileWorkspaceBrowserNode[]) => Promise<string[] | null>;
type ResolveSystemClipboardPaste = (
  clipboard: FileWorkspaceClipboardState,
) => Promise<"internal" | "handled">;

function closeContextMenuNow(setContextMenu: ContextMenuSetter) {
  flushSync(() => {
    setContextMenu(null);
  });
}

function runContextMenuAction(
  setContextMenu: ContextMenuSetter,
  action: () => void,
) {
  closeContextMenuNow(setContextMenu);
  action();
}

export function FileWorkspaceRootContextMenu({
  browser,
  clipboard,
  contextMenu,
  onCreateFile,
  onCreateFolder,
  setClipboard,
  setContextMenu,
  resolveSystemClipboardPaste,
}: {
  browser: UseFileWorkspaceBrowserResult;
  clipboard: FileWorkspaceClipboardState;
  contextMenu: Extract<FileWorkspaceContextMenuState, { mode: "root" }>;
  onCreateFile: (parentId?: string) => void;
  onCreateFolder: (parentId?: string) => void;
  setClipboard: ClipboardSetter;
  setContextMenu: ContextMenuSetter;
  resolveSystemClipboardPaste?: ResolveSystemClipboardPaste;
}) {
  const { t } = useI18n();
  const closeMenu = () => closeContextMenuNow(setContextMenu);

  return (
    <ContextMenu onClose={closeMenu} position={{ x: contextMenu.x, y: contextMenu.y }}>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          onCreateFile(undefined);
        })}
      >
        {t("fileWorkspace.context.createFile")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          onCreateFolder(undefined);
        })}
      >
        {t("fileWorkspace.context.createFolder")}
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem
        disabled={!clipboard && !resolveSystemClipboardPaste}
        onSelect={() => {
          if (!clipboard && !resolveSystemClipboardPaste) {
            return;
          }
          runContextMenuAction(setContextMenu, () => {
            void pasteClipboard(browser, clipboard, null, setClipboard, resolveSystemClipboardPaste).catch(
              () => undefined,
            );
          });
        }}
      >
        {t("fileWorkspace.context.paste")}
      </ContextMenuItem>
      {clipboard ? (
        <ContextMenuItem
          onSelect={() => runContextMenuAction(setContextMenu, () => {
            setClipboard(null);
          })}
        >
          {t("fileWorkspace.context.clearClipboard")}
        </ContextMenuItem>
      ) : null}
      <ContextMenuSeparator />
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          browser.refreshTree();
        })}
      >
        {t("common.actions.refresh")}
      </ContextMenuItem>
    </ContextMenu>
  );
}

export function FileWorkspaceSelectionContextMenu({
  browser,
  contextMenu,
  setClipboard,
  setContextMenu,
  setPendingDeleteNodeIds,
  copyNodesToSystemClipboard,
}: {
  browser: UseFileWorkspaceBrowserResult;
  contextMenu: Extract<FileWorkspaceContextMenuState, { mode: "selection" }>;
  setClipboard: ClipboardSetter;
  setContextMenu: ContextMenuSetter;
  setPendingDeleteNodeIds: (nodeIds: string[] | null) => void;
  copyNodesToSystemClipboard?: CopyNodesToSystemClipboard;
}) {
  const { t } = useI18n();
  const closeMenu = () => closeContextMenuNow(setContextMenu);
  const nodeIds = getActionNodeIds(browser, contextMenu.nodeIds);
  const selectedCount = nodeIds.length;

  return (
    <ContextMenu onClose={closeMenu} position={{ x: contextMenu.x, y: contextMenu.y }}>
      <ContextMenuItem
        disabled={selectedCount === 0}
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          copyToClipboard(browser, nodeIds, setClipboard, copyNodesToSystemClipboard);
        })}
      >
        {t("fileWorkspace.context.copyItems", { count: selectedCount })}
      </ContextMenuItem>
      <ContextMenuItem
        disabled={selectedCount === 0}
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          setClipboard({ mode: "cut", nodeIds });
        })}
      >
        {t("fileWorkspace.context.cutItems", { count: selectedCount })}
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          browser.refreshTree();
        })}
      >
        {t("common.actions.refresh")}
      </ContextMenuItem>
      <ContextMenuItem
        danger
        disabled={selectedCount === 0}
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          setPendingDeleteNodeIds(nodeIds);
        })}
      >
        {t("fileWorkspace.context.deleteItems", { count: selectedCount })}
      </ContextMenuItem>
    </ContextMenu>
  );
}

export function FileWorkspaceNodeContextMenu({
  browser,
  clipboard,
  contextMenu,
  isExpanded,
  node,
  onCreateFile,
  onCreateFolder,
  onOpenFile,
  onReferenceNode,
  onRenameStart,
  setClipboard,
  setContextMenu,
  setPendingDeleteNodeIds,
  copyNodesToSystemClipboard,
  resolveSystemClipboardPaste,
}: {
  browser: UseFileWorkspaceBrowserResult;
  clipboard: FileWorkspaceClipboardState;
  contextMenu: Extract<FileWorkspaceContextMenuState, { mode: "node" }>;
  isExpanded: boolean;
  node: FileWorkspaceBrowserNode;
  onCreateFile: (parentId?: string) => void;
  onCreateFolder: (parentId?: string) => void;
  onOpenFile?: (node: FileWorkspaceBrowserNode) => void;
  onReferenceNode?: (node: FileWorkspaceBrowserNode) => void;
  onRenameStart: (nodeId: string) => void;
  setClipboard: ClipboardSetter;
  setContextMenu: ContextMenuSetter;
  setPendingDeleteNodeIds: (nodeIds: string[] | null) => void;
  copyNodesToSystemClipboard?: CopyNodesToSystemClipboard;
  resolveSystemClipboardPaste?: ResolveSystemClipboardPaste;
}) {
  const { t } = useI18n();
  const closeMenu = () => closeContextMenuNow(setContextMenu);
  const targetParentNodeId = resolveNodeContextTargetParentId(node);

  return (
    <ContextMenu onClose={closeMenu} position={{ x: contextMenu.x, y: contextMenu.y }}>
      {node.kind === "file" ? (
        <ContextMenuItem
          onSelect={() => runContextMenuAction(setContextMenu, () => {
            onOpenFile?.(node);
          })}
        >
          {t("fileWorkspace.context.open")}
        </ContextMenuItem>
      ) : null}
      {onReferenceNode ? (
        <ContextMenuItem
          onSelect={() => runContextMenuAction(setContextMenu, () => {
            onReferenceNode(node);
          })}
        >
          {t("fileWorkspace.context.referenceToChat")}
        </ContextMenuItem>
      ) : null}
      {node.kind === "folder" ? (
        <ContextMenuItem
          onSelect={() => runContextMenuAction(setContextMenu, () => {
            browser.toggleNode(node.id);
          })}
        >
          {isExpanded ? t("fileWorkspace.context.collapse") : t("fileWorkspace.context.expand")}
        </ContextMenuItem>
      ) : null}
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          onCreateFile(targetParentNodeId ?? undefined);
        })}
      >
        {t("fileWorkspace.context.createFile")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          onCreateFolder(targetParentNodeId ?? undefined);
        })}
      >
        {t("fileWorkspace.context.createFolder")}
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          void browser.revealNode(node.id).catch(() => undefined);
        })}
      >
        {t("fileWorkspace.context.reveal")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          copyToClipboard(browser, [node.id], setClipboard, copyNodesToSystemClipboard);
        })}
      >
        {t("fileWorkspace.context.copy")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          setClipboard({ mode: "cut", nodeIds: [node.id] });
        })}
      >
        {t("fileWorkspace.context.cut")}
      </ContextMenuItem>
      <ContextMenuItem
        disabled={!clipboard && !resolveSystemClipboardPaste}
        onSelect={() => {
          if (!clipboard && !resolveSystemClipboardPaste) {
            return;
          }
          runContextMenuAction(setContextMenu, () => {
            void pasteClipboard(
              browser,
              clipboard,
              targetParentNodeId,
              setClipboard,
              resolveSystemClipboardPaste,
            ).catch(
              () => undefined,
            );
          });
        }}
      >
        {t("fileWorkspace.context.paste")}
      </ContextMenuItem>
      {clipboard ? (
        <ContextMenuItem
          onSelect={() => runContextMenuAction(setContextMenu, () => {
            setClipboard(null);
          })}
        >
          {t("fileWorkspace.context.clearClipboard")}
        </ContextMenuItem>
      ) : null}
      <ContextMenuSeparator />
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          onRenameStart(node.id);
        })}
      >
        {t("common.actions.rename")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          browser.refreshTree();
        })}
      >
        {t("common.actions.refresh")}
      </ContextMenuItem>
      <ContextMenuItem
        danger
        onSelect={() => runContextMenuAction(setContextMenu, () => {
          setPendingDeleteNodeIds([node.id]);
        })}
      >
        {t("common.actions.delete")}
      </ContextMenuItem>
    </ContextMenu>
  );
}

function resolveNodeContextTargetParentId(node: FileWorkspaceBrowserNode) {
  if (node.kind === "folder") {
    return node.id;
  }
  return getParentWorkspacePath(node.path);
}

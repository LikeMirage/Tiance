import { memo, startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import {
  ArrowClockwise,
  CaretLeft,
  Check,
  FilePlus,
  FolderPlus,
  Plus,
  ArrowSquareIn,
} from "@phosphor-icons/react";

import type { ToolFolder, Toolset } from "../../../entities/tool/model/toolset";
import type { useDocumentTabs } from "../../document-tabs/model/useDocumentTabs";
import { createToolFolderDocumentSource } from "../../document-tabs/model/documentFileSources";
import { ExternalFileWorkspaceTree } from "../../file-workspace/ui";
import type { UseToolFolderBrowserResult } from "../../tool-browser/model/toolBrowserTypes";
import { getToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";
import { SlidingViewStage } from "../../../shared/ui/sliding-view-stage/SlidingViewStage";
import type { UseToolCatalogResult } from "../model/useToolCatalog";
import type { UseToolFoldersResult } from "../model/useToolFolders";
import { ToolFolderContextMenu } from "./ToolFolderContextMenu";
import { ToolFolderDeleteConfirmModal } from "./ToolFolderDeleteConfirmModal";
import type {
  PendingToolFolderDelete,
  ToolFolderContextMenuState,
} from "./toolFolderContextMenuTypes";
import "../../../shared/ui/catalog-list-entry/catalog-list-entry.css";
import "./tool-catalog-panel.css";

type ToolCatalogPanelProps = {
  browser: UseToolFolderBrowserResult;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  toolCatalog: ToolCatalogPanelToolCatalog;
  toolFolders: UseToolFoldersResult;
};

const TOOLBAR_ACTION_THROTTLE_MS = 300;

export type ToolCatalogPanelToolCatalog = Pick<
  UseToolCatalogResult,
  | "error"
  | "items"
  | "reload"
  | "selectedToolset"
  | "state"
>;

export const ToolCatalogPanel = memo(function ToolCatalogPanel({
  browser,
  documentTabs,
  toolCatalog,
  toolFolders,
}: ToolCatalogPanelProps) {
  const selectedToolset = toolCatalog.selectedToolset;
  const displayedToolset = toolFolders.displayedToolsetId
    ? toolCatalog.items.find((item) => item.category_id === toolFolders.displayedToolsetId) ?? null
    : selectedToolset;
  const canEditDisplayedToolset =
    !!displayedToolset &&
    displayedToolset.category_id === selectedToolset?.category_id &&
    toolFolders.state !== "loading" &&
    !toolFolders.readonly;
  const [searchKeyword, setSearchKeyword] = useState("");
  const lastCreateAtRef = useRef(0);
  const lastRefreshAtRef = useRef(0);
  const isDetailView = Boolean(toolFolders.expandedFolder);
  const headerTitle = isDetailView
    ? toolFolders.expandedFolder?.name ?? "工具"
    : displayedToolset?.name ?? "工具集";
  const activeSearchKeyword = isDetailView ? browser.searchKeyword : searchKeyword;
  const normalizedKeyword = searchKeyword.trim().toLowerCase();
  const filteredFolders = useMemo(
    () =>
      normalizedKeyword.length === 0
        ? toolFolders.items
        : toolFolders.items.filter((folder) =>
            folder.name.toLowerCase().includes(normalizedKeyword),
          ),
    [normalizedKeyword, toolFolders.items],
  );

  const createToolFolder = useCallback(() => {
    setSearchKeyword("");
    void toolFolders.createToolFolder().catch(() => undefined);
  }, [toolFolders]);
  const createToolEntry = useCallback((kind: "file" | "folder") => {
    const now = Date.now();
    if (now - lastCreateAtRef.current < TOOLBAR_ACTION_THROTTLE_MS) {
      return;
    }
    lastCreateAtRef.current = now;

    if (kind === "file") {
      void browser.createFile();
      return;
    }
    void browser.createFolder();
  }, [browser]);
  const refreshToolTree = useCallback(() => {
    const now = Date.now();
    if (now - lastRefreshAtRef.current < TOOLBAR_ACTION_THROTTLE_MS) {
      return;
    }
    lastRefreshAtRef.current = now;
    browser.refreshTree();
  }, [browser]);

  return (
    <aside className="tool-catalog-panel" aria-label="工具集面板">
      <header className="tool-catalog-panel__header">
        <h2 className="tool-catalog-panel__title">{headerTitle}</h2>
        <button
          className="tool-catalog-panel__add"
          type="button"
          aria-label={isDetailView ? "新建文件" : "新增工具"}
          disabled={!isDetailView && (!canEditDisplayedToolset || toolFolders.isCreatingToolFolder)}
          title={
            isDetailView
              ? "新建文件"
              : canEditDisplayedToolset
                ? "新增工具"
                : "工具分类载入中"
          }
          onClick={isDetailView ? () => createToolEntry("file") : createToolFolder}
        >
          {isDetailView ? <FilePlus size={14} weight="bold" /> : <Plus size={13} weight="bold" />}
        </button>
        {isDetailView ? (
          <>
            <button
              className="tool-catalog-panel__add"
              type="button"
              aria-label="新建文件夹"
              title="新建文件夹"
              onClick={() => createToolEntry("folder")}
            >
              <FolderPlus size={14} weight="bold" />
            </button>
            <button
              className="tool-catalog-panel__add"
              type="button"
              aria-label="刷新文件列表"
              title="刷新"
              onClick={refreshToolTree}
            >
              <ArrowClockwise size={14} weight="bold" />
            </button>
            <button
              className="tool-catalog-panel__add"
              type="button"
              aria-label="返回工具列表"
              title="返回"
              onClick={toolFolders.collapseFolder}
            >
              <CaretLeft size={14} weight="bold" />
            </button>
          </>
        ) : null}
      </header>

      <label className="tool-catalog-panel__search">
        <span className="tool-catalog-panel__search-label">搜索工具</span>
        <input
          className="tool-catalog-panel__search-input"
          type="search"
          value={activeSearchKeyword}
          placeholder={isDetailView ? "搜索文件" : "搜索工具"}
          onChange={(event) => {
            if (isDetailView) {
              browser.setSearchKeyword(event.target.value);
              return;
            }
            setSearchKeyword(event.target.value);
          }}
        />
      </label>

      <ToolCatalogBody
        browser={browser}
        documentTabs={documentTabs}
        displayedToolset={displayedToolset}
        filteredFolders={filteredFolders}
        isSearching={normalizedKeyword.length > 0}
        isReadonly={!canEditDisplayedToolset}
        toolCatalog={toolCatalog}
        toolFolders={toolFolders}
      />

      {(toolCatalog.error && toolCatalog.state === "ready") || toolFolders.error ? (
        <div className="tool-catalog-panel__footer-error" role="status">
          {toolFolders.error ?? toolCatalog.error}
        </div>
      ) : null}
    </aside>
  );
});

function ToolCatalogBody({
  displayedToolset,
  filteredFolders,
  browser,
  documentTabs,
  isSearching,
  isReadonly,
  toolCatalog,
  toolFolders,
}: {
  browser: UseToolFolderBrowserResult;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  displayedToolset: Toolset | null;
  filteredFolders: ToolFolder[];
  isSearching: boolean;
  isReadonly: boolean;
  toolCatalog: ToolCatalogPanelToolCatalog;
  toolFolders: UseToolFoldersResult;
}) {
  const [renamingFolderId, setRenamingFolderId] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const clearPendingRenameFolder = toolFolders.clearPendingRenameFolder;
  const pendingRenameFolderId = toolFolders.pendingRenameFolderId;
  const [contextMenu, setContextMenu] = useState<ToolFolderContextMenuState>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingToolFolderDelete>(null);
  const [deletingFolderId, setDeletingFolderId] = useState<string | null>(null);
  const expandedFolder = toolFolders.expandedFolder;
  const displayedToolsetId = toolFolders.displayedToolsetId;
  const activeWorkspaceKey = displayedToolsetId && expandedFolder
    ? getToolFolderWorkspaceKey(displayedToolsetId, expandedFolder.project_id)
    : null;
  const activeToolFilePath = documentTabs.activeTab?.fileSource?.key === activeWorkspaceKey
    ? documentTabs.activeTab.filePath
    : null;

  useEffect(() => {
    if (!pendingRenameFolderId) return;
    setRenamingFolderId(pendingRenameFolderId);
    clearPendingRenameFolder();
  }, [clearPendingRenameFolder, pendingRenameFolderId]);

  useEffect(() => {
    if (!renamingFolderId) return;
    setTimeout(() => {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }, 0);
  }, [renamingFolderId]);

  useEffect(() => {
    setContextMenu(null);
  }, [displayedToolsetId, expandedFolder?.project_id, isReadonly]);

  useEffect(() => {
    if (!activeWorkspaceKey || !activeToolFilePath) return;
    void browser.revealPath(activeToolFilePath);
  }, [activeToolFilePath, activeWorkspaceKey, browser.revealPath]);

  if (toolCatalog.state === "loading") {
    return <div className="tool-catalog-panel__status">正在载入工具集……</div>;
  }

  if (toolCatalog.state === "error") {
    return (
      <div className="tool-catalog-panel__status tool-catalog-panel__status--error">
        <span>{toolCatalog.error ?? "工具集载入失败。"}</span>
        <button
          className="tool-catalog-panel__status-action"
          type="button"
          onClick={toolCatalog.reload}
        >
          重试
        </button>
      </div>
    );
  }

  if (toolCatalog.items.length === 0) {
    return <div className="tool-catalog-panel__status">当前没有工具分类。</div>;
  }

  if (!displayedToolset) {
    return null;
  }

  if (toolFolders.state === "loading" && toolFolders.displayedToolsetId === null) {
    return <div className="tool-catalog-panel__status">正在载入工具……</div>;
  }

  const activeView = expandedFolder && displayedToolsetId ? "detail" : "list";
  const detailContent = expandedFolder && displayedToolsetId ? (
    <div aria-label={`${expandedFolder.name} 文件`}>
        <div className="tool-catalog-panel__detail">
          <ExternalFileWorkspaceTree
            allowExternalImport={!isReadonly}
            browser={browser}
            emptyMessage="此工具暂无文件。"
            initialLoadingMessage={null}
            rootAriaLabel="工具根目录"
            treeAriaLabel="工具文件"
            onCreateFile={(parentId) => void browser.createFile(parentId)}
            onCreateFolder={(parentId) => void browser.createFolder(parentId)}
            onDeleteNode={(nodeId) => browser.deleteNode(nodeId)}
            onOpenFile={(node) => {
              void documentTabs.openNode(
                { id: node.id, name: node.name, path: node.path, kind: "file" },
                {
                  filePath: node.path,
                  fileSource: createToolFolderDocumentSource(
                    displayedToolsetId,
                    expandedFolder.project_id,
                    expandedFolder.name,
                    expandedFolder.project_id,
                  ),
                },
              );
            }}
            onRenameStart={browser.startInlineEdit}
            surfaceAriaLabel={`${expandedFolder.name} 文件`}
            workspaceKey={getToolFolderWorkspaceKey(
              displayedToolsetId,
              expandedFolder.project_id,
            )}
            workspaceRoot={expandedFolder.root_path}
          />
        </div>
      </div>
  ) : null;
  const listContent = (
    <div aria-label={`${displayedToolset.name} 工具`}>
      <nav className="tool-catalog-panel__list" aria-label="工具列表">
        {filteredFolders.length === 0 ? (
          <div className="tool-catalog-panel__empty">
            {isSearching ? "没有匹配的工具。" : "暂无工具。"}
          </div>
        ) : (
          filteredFolders.map((folder) => (
            <ToolFolderItem
              folder={folder}
              isSelected={toolFolders.selectedFolderId === folder.project_id}
              isReadonly={isReadonly}
              isRenaming={renamingFolderId === folder.project_id && !isReadonly}
              key={folder.project_id}
              onRenameEnd={() => setRenamingFolderId(null)}
              onOpen={() => toolFolders.expandFolder(folder.project_id)}
              onSelect={() => toolFolders.selectFolder(folder.project_id)}
              onOpenContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setContextMenu({
                  folderId: folder.project_id,
                  x: event.clientX,
                  y: event.clientY,
                });
              }}
              renameInputRef={renameInputRef}
              toolFolders={toolFolders}
            />
          ))
        )}
      </nav>
      {contextMenu ? (
        <ToolFolderContextMenu
          contextMenu={contextMenu}
          folders={toolFolders.items}
          isReadonly={isReadonly}
          onClose={() => setContextMenu(null)}
          onMoveToToolset={(folderId, targetToolsetId) => {
            void toolFolders.moveToolFolderToToolset(folderId, targetToolsetId).catch(() => undefined);
          }}
          onOpenInExplorer={(folderId) => {
            void toolFolders.revealToolFolder(folderId).catch(() => undefined);
          }}
          onRequestDelete={setPendingDelete}
          onStartRename={setRenamingFolderId}
          toolsets={toolCatalog.items}
        />
      ) : null}
      {pendingDelete ? (
        <ToolFolderDeleteConfirmModal
          deletingFolderId={deletingFolderId}
          onCancel={() => setPendingDelete(null)}
          onConfirm={(pending) => {
            const folderId = pending.folderId;
            setDeletingFolderId(folderId);
            void toolFolders.deleteToolFolder(folderId)
              .then(() => {
                setPendingDelete(null);
              })
              .catch(() => undefined)
              .finally(() => {
                setDeletingFolderId((current) => current === folderId ? null : current);
              });
          }}
          pendingDelete={pendingDelete}
        />
      ) : null}
    </div>
  );

  return (
    <SlidingViewStage
      className="tool-catalog-panel__content"
      direction={activeView === "detail" ? "forward" : "back"}
      keepLeavingView={false}
      viewKey={activeView}
    >
      {activeView === "detail" ? detailContent : listContent}
    </SlidingViewStage>
  );
}

function ToolFolderItem({
  folder,
  isReadonly,
  isSelected,
  isRenaming,
  onRenameEnd,
  onOpen,
  onSelect,
  onOpenContextMenu,
  renameInputRef,
  toolFolders,
}: {
  folder: ToolFolder;
  isReadonly: boolean;
  isSelected: boolean;
  isRenaming: boolean;
  onRenameEnd: () => void;
  onOpen: () => void;
  onSelect: () => void;
  onOpenContextMenu: (event: MouseEvent<HTMLElement>) => void;
  renameInputRef: RefObject<HTMLInputElement | null>;
  toolFolders: UseToolFoldersResult;
}) {
  const isCommittingRef = useRef(false);
  const commitRename = async (name: string) => {
    if (isCommittingRef.current) return;
    const normalizedName = name.trim();
    if (!normalizedName || normalizedName === folder.name) {
      onRenameEnd();
      return;
    }
    isCommittingRef.current = true;
    try {
      await toolFolders.renameToolFolder(folder.project_id, normalizedName);
      onRenameEnd();
    } catch {
      window.setTimeout(() => {
        renameInputRef.current?.focus();
        renameInputRef.current?.select();
      }, 0);
    } finally {
      isCommittingRef.current = false;
    }
  };

  return (
    <article
      className={
        isSelected
          ? "catalog-list-entry tool-catalog-panel__item tool-catalog-panel__item--selected"
          : "catalog-list-entry tool-catalog-panel__item"
      }
      onContextMenu={onOpenContextMenu}
      onDoubleClick={() => startTransition(onOpen)}
    >
      {isRenaming ? (
        <div className="catalog-list-entry__main tool-catalog-panel__item-main">
          <span className="tool-catalog-panel__rename-field">
            <input
              ref={renameInputRef}
              className="tool-catalog-panel__rename-input"
              defaultValue={folder.name}
              onBlur={(event) => { void commitRename(event.target.value); }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void commitRename(event.currentTarget.value);
                } else if (event.key === "Escape") {
                  if (!isCommittingRef.current) {
                    onRenameEnd();
                  }
                }
              }}
            />
            <button
              className="tool-catalog-panel__rename-save"
              type="button"
              aria-label="保存工具名称"
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.stopPropagation();
                void commitRename(renameInputRef.current?.value ?? folder.name);
              }}
            >
              <Check className="tool-catalog-panel__rename-save-glyph" weight="bold" />
            </button>
          </span>
        </div>
      ) : (
        <button
          className={
            isReadonly
              ? "catalog-list-entry__main tool-catalog-panel__item-main tool-catalog-panel__item-main--readonly"
              : "catalog-list-entry__main tool-catalog-panel__item-main"
          }
          type="button"
          onClick={() => {
            startTransition(onSelect);
          }}
        >
          <span className="catalog-list-entry__copy">
            <span className="catalog-list-entry__name">{folder.name}</span>
            <span className="catalog-list-entry__meta">
              {formatToolFolderCreatedAt(folder.created_at)}
            </span>
          </span>
        </button>
      )}
      {!isRenaming ? (
        <button
          className="catalog-list-entry__enter tool-catalog-panel__item-enter"
          type="button"
          aria-label={`进入 ${folder.name}`}
          title="进入工具工作区"
          onClick={(event) => {
            event.stopPropagation();
            startTransition(onOpen);
          }}
        >
          <ArrowSquareIn size={14} aria-hidden="true" />
        </button>
      ) : null}
    </article>
  );
}

function formatToolFolderCreatedAt(createdAt: string) {
  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ToolFolder } from "../../../entities/tool/model/toolset";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  publishToolCatalogChange,
  subscribeToolCatalogChanges,
} from "../../../entities/tool/model/toolCatalogEvents";
import { createToolFolder as createToolFolderRequest } from "../../../services/tools/createToolFolder";
import { deleteToolFolder as deleteToolFolderRequest } from "../../../services/tools/deleteToolFolder";
import { getToolFolders } from "../../../services/tools/getToolFolders";
import { moveToolFolderToToolset as moveToolFolderToToolsetRequest } from "../../../services/tools/moveToolFolderToToolset";
import { revealToolFolder as revealToolFolderRequest } from "../../../services/tools/revealToolFolder";
import { renameToolFolder as renameToolFolderRequest } from "../../../services/tools/renameToolFolder";

type LoadState = "idle" | "loading" | "ready" | "error";

type ToolFolderCacheEntry = {
  items: ToolFolder[];
  readonly: boolean;
};

export type UseToolFoldersResult = {
  clearPendingRenameFolder: () => void;
  collapseFolder: () => void;
  createToolFolder: () => Promise<ToolFolder>;
  deleteToolFolder: (folderId: string) => Promise<void>;
  displayedToolsetId: string | null;
  error: string | null;
  expandedFolder: ToolFolder | null;
  expandedFolderId: string | null;
  expandFolder: (folderId: string) => void;
  selectedFolder: ToolFolder | null;
  selectedFolderId: string | null;
  selectFolder: (folderId: string) => void;
  isCreatingToolFolder: boolean;
  items: ToolFolder[];
  pendingRenameFolderId: string | null;
  reload: () => void;
  moveToolFolderToToolset: (folderId: string, targetToolsetId: string) => Promise<ToolFolder>;
  renameToolFolder: (folderId: string, name: string) => Promise<void>;
  revealToolFolder: (folderId: string) => Promise<void>;
  readonly: boolean;
  state: LoadState;
};

export function useToolFolders(
  toolsetId: string | null,
  options: {
    readonly: boolean;
  },
): UseToolFoldersResult {
  const sourceIdRef = useRef(`tool-folders:${Math.random().toString(36).slice(2)}`);
  const readonly = options.readonly;
  const [items, setItems] = useState<ToolFolder[]>([]);
  const [state, setState] = useState<LoadState>(toolsetId ? "loading" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const [isCreatingToolFolder, setIsCreatingToolFolder] = useState(false);
  const [pendingRenameFolderId, setPendingRenameFolderId] = useState<string | null>(null);
  const [expandedFolderId, setExpandedFolderId] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [displayedToolsetId, setDisplayedToolsetId] = useState<string | null>(null);
  const [displayedReadonly, setDisplayedReadonly] = useState(true);
  const displayedToolsetIdRef = useRef<string | null>(null);
  const folderCacheRef = useRef(new Map<string, ToolFolderCacheEntry>());

  useEffect(() => {
    let cancelled = false;
    const hasDisplayedContent = displayedToolsetIdRef.current !== null;
    const previousDisplayedToolsetId = displayedToolsetIdRef.current;

    if (!toolsetId) {
      setItems([]);
      setState("idle");
      setError(null);
      displayedToolsetIdRef.current = null;
      setDisplayedToolsetId(null);
      setDisplayedReadonly(true);
      setExpandedFolderId(null);
      setSelectedFolderId(null);
      return () => { cancelled = true; };
    }

    const cached = folderCacheRef.current.get(toolsetId);
    if (cached) {
      setItems(cached.items);
      setExpandedFolderId((current) =>
        current && cached.items.some((folder) => folder.project_id === current)
          ? current
          : null,
      );
      setSelectedFolderId((current) =>
        current && cached.items.some((folder) => folder.project_id === current)
          ? current
          : cached.items[0]?.project_id ?? null,
      );
      displayedToolsetIdRef.current = toolsetId;
      setDisplayedToolsetId(toolsetId);
      setDisplayedReadonly(cached.readonly);
      setState("ready");
      setError(null);
    }

    const load = async () => {
      if (!cached) {
        setState("loading");
        setError(null);
      }
      try {
        const response = await getToolFolders(toolsetId);
        if (cancelled) return;
        folderCacheRef.current.set(toolsetId, {
          items: response.items,
          readonly,
        });
        setItems(response.items);
        setExpandedFolderId((current) =>
          current && response.items.some((folder) => folder.project_id === current)
            ? current
            : null,
        );
        setSelectedFolderId((current) =>
          current && response.items.some((folder) => folder.project_id === current)
            ? current
            : response.items[0]?.project_id ?? null,
        );
        displayedToolsetIdRef.current = toolsetId;
        setDisplayedToolsetId(toolsetId);
        setDisplayedReadonly(readonly);
        setState("ready");
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "工具载入失败。");
        if (!hasDisplayedContent) {
          setItems([]);
          displayedToolsetIdRef.current = null;
          setDisplayedToolsetId(null);
          setDisplayedReadonly(true);
        } else {
          setDisplayedToolsetId(previousDisplayedToolsetId);
        }
        setState(hasDisplayedContent ? "ready" : "error");
      }
    };

    void load();
    return () => { cancelled = true; };
  }, [readonly, requestKey, toolsetId]);

  useEffect(() =>
    subscribeToolCatalogChanges((change) => {
      if (change.sourceId === sourceIdRef.current) return;
      if (change.kind !== "folders" && change.kind !== "metadata") return;
      if (change.toolsetId && change.toolsetId !== displayedToolsetIdRef.current) {
        folderCacheRef.current.delete(change.toolsetId);
        return;
      }
      if (change.toolsetId) {
        folderCacheRef.current.delete(change.toolsetId);
      } else {
        folderCacheRef.current.clear();
      }
      setRequestKey((current) => current + 1);
    }),
  []);

  const clearPendingRenameFolder = useCallback(() => setPendingRenameFolderId(null), []);
  const createToolFolder = useCallback(async () => {
    if (!displayedToolsetId || displayedReadonly) {
      const message = "当前工具分类不能新增工具。";
      setError(message);
      throw new Error(message);
    }
    setIsCreatingToolFolder(true);
    setError(null);
    try {
      const created = await createToolFolderRequest(displayedToolsetId);
      setItems((current) => {
        const nextItems = [...current, created];
        folderCacheRef.current.set(displayedToolsetId, {
          items: nextItems,
          readonly: displayedReadonly,
        });
        return nextItems;
      });
      setPendingRenameFolderId(created.project_id);
      setSelectedFolderId(created.project_id);
      publishToolCatalogChange({
        folderId: created.project_id,
        kind: "folders",
        sourceId: sourceIdRef.current,
        toolsetId: displayedToolsetId,
      });
      dispatchProjectCatalogChanged();
      return created;
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "工具创建失败。");
      throw createError;
    } finally {
      setIsCreatingToolFolder(false);
    }
  }, [displayedReadonly, displayedToolsetId]);

  const deleteToolFolder = useCallback(async (folderId: string) => {
    if (!displayedToolsetId) {
      const message = "请先选择工具分类。";
      setError(message);
      throw new Error(message);
    }
    if (displayedReadonly) {
      const message = "当前工具分类不能删除工具。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      await deleteToolFolderRequest(displayedToolsetId, folderId);
      setItems((current) => {
        const nextItems = current.filter((item) => item.project_id !== folderId);
        folderCacheRef.current.set(displayedToolsetId, {
          items: nextItems,
          readonly: displayedReadonly,
        });
        return nextItems;
      });
      setExpandedFolderId((current) => current === folderId ? null : current);
      setSelectedFolderId((current) =>
        current === folderId
          ? folderCacheRef.current.get(displayedToolsetId)?.items[0]?.project_id ?? null
          : current,
      );
      publishToolCatalogChange({
        folderId,
        kind: "folders",
        sourceId: sourceIdRef.current,
        toolsetId: displayedToolsetId,
      });
      dispatchProjectCatalogChanged();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "工具删除失败。");
      throw deleteError;
    }
  }, [displayedReadonly, displayedToolsetId]);

  const collapseFolder = useCallback(() => setExpandedFolderId(null), []);
  const expandFolder = useCallback((folderId: string) => {
    setSelectedFolderId(folderId);
    setExpandedFolderId((current) => current === folderId ? current : folderId);
  }, []);
  const selectFolder = useCallback((folderId: string) => {
    setSelectedFolderId((current) => current === folderId ? current : folderId);
  }, []);
  const reload = useCallback(() => setRequestKey((current) => current + 1), []);
  const moveToolFolderToToolset = useCallback(async (
    folderId: string,
    targetToolsetId: string,
  ) => {
    if (!displayedToolsetId) {
      const message = "请先选择工具分类。";
      setError(message);
      throw new Error(message);
    }
    if (displayedReadonly) {
      const message = "当前工具分类不能移动工具。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      const moved = await moveToolFolderToToolsetRequest(
        displayedToolsetId,
        folderId,
        targetToolsetId,
      );
      setItems((current) => {
        const nextItems = current.filter((item) => item.project_id !== folderId);
        folderCacheRef.current.set(displayedToolsetId, {
          items: nextItems,
          readonly: displayedReadonly,
        });
        const targetCache = folderCacheRef.current.get(targetToolsetId);
        if (targetCache) {
          folderCacheRef.current.set(targetToolsetId, {
            ...targetCache,
            items: [...targetCache.items, moved],
          });
        }
        return nextItems;
      });
      setExpandedFolderId((current) => current === folderId ? null : current);
      setSelectedFolderId((current) =>
        current === folderId
          ? folderCacheRef.current.get(displayedToolsetId)?.items[0]?.project_id ?? null
          : current,
      );
      publishToolCatalogChange({
        folderId,
        kind: "folders",
        sourceId: sourceIdRef.current,
        toolsetId: displayedToolsetId,
      });
      publishToolCatalogChange({
        folderId: moved.project_id,
        kind: "folders",
        sourceId: sourceIdRef.current,
        toolsetId: targetToolsetId,
      });
      dispatchProjectCatalogChanged();
      return moved;
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "工具移动失败。");
      throw moveError;
    }
  }, [displayedReadonly, displayedToolsetId]);

  const renameToolFolder = useCallback(async (folderId: string, name: string) => {
    if (!displayedToolsetId) {
      const message = "请先选择工具分类。";
      setError(message);
      throw new Error(message);
    }
    if (displayedReadonly) {
      const message = "当前工具分类不能重命名工具。";
      setError(message);
      throw new Error(message);
    }
    const normalizedName = name.trim();
    if (!normalizedName) {
      const message = "工具名称不能为空。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      const updated = await renameToolFolderRequest(displayedToolsetId, folderId, normalizedName);
      setItems((current) => {
        const nextItems = current.map((item) => (item.project_id === folderId ? updated : item));
        folderCacheRef.current.set(displayedToolsetId, {
          items: nextItems,
          readonly: displayedReadonly,
        });
        return nextItems;
      });
      publishToolCatalogChange({
        folderId,
        kind: "folders",
        sourceId: sourceIdRef.current,
        toolsetId: displayedToolsetId,
      });
      dispatchProjectCatalogChanged();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "工具重命名失败。");
      throw renameError;
    }
  }, [displayedReadonly, displayedToolsetId]);

  const revealToolFolder = useCallback(async (folderId: string) => {
    if (!displayedToolsetId) {
      const message = "请先选择工具分类。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      await revealToolFolderRequest(displayedToolsetId, folderId);
    } catch (revealError) {
      setError(revealError instanceof Error ? revealError.message : "工具打开失败。");
      throw revealError;
    }
  }, [displayedToolsetId]);

  const expandedFolder = useMemo(
    () => items.find((item) => item.project_id === expandedFolderId) ?? null,
    [expandedFolderId, items],
  );
  const selectedFolder = useMemo(
    () => items.find((item) => item.project_id === selectedFolderId) ?? null,
    [items, selectedFolderId],
  );

  return useMemo(() => ({
    clearPendingRenameFolder,
    collapseFolder,
    createToolFolder,
    deleteToolFolder,
    displayedToolsetId,
    error,
    expandedFolder,
    expandedFolderId,
    expandFolder,
    selectedFolder,
    selectedFolderId,
    selectFolder,
    isCreatingToolFolder,
    items,
    pendingRenameFolderId,
    reload,
    moveToolFolderToToolset,
    renameToolFolder,
    revealToolFolder,
    readonly: displayedReadonly,
    state,
  }), [
    clearPendingRenameFolder,
    collapseFolder,
    createToolFolder,
    deleteToolFolder,
    displayedReadonly,
    displayedToolsetId,
    error,
    expandedFolder,
    expandedFolderId,
    expandFolder,
    selectedFolder,
    selectedFolderId,
    selectFolder,
    isCreatingToolFolder,
    items,
    moveToolFolderToToolset,
    pendingRenameFolderId,
    reload,
    renameToolFolder,
    revealToolFolder,
    state,
  ]);
}

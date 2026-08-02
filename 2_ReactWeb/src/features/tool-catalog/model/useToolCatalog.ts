import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Toolset } from "../../../entities/tool/model/toolset";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  publishToolCatalogChange,
  subscribeToolCatalogChanges,
} from "../../../entities/tool/model/toolCatalogEvents";
import { createToolset as createToolsetRequest } from "../../../services/tools/createToolset";
import { deleteToolset as deleteToolsetRequest } from "../../../services/tools/deleteToolset";
import { getToolsets } from "../../../services/tools/getToolsets";
import { renameToolset as renameToolsetRequest } from "../../../services/tools/renameToolset";

type LoadState = "loading" | "ready" | "error";

const TOOLSET_SELECTION_KEY = "tiance.tool-catalog.selection";

export type UseToolCatalogResult = {
  clearPendingRenameToolset: () => void;
  createToolset: () => Promise<Toolset>;
  deleteToolset: (toolsetId: string) => Promise<void>;
  error: string | null;
  isCreatingToolset: boolean;
  items: Toolset[];
  pendingRenameToolsetId: string | null;
  reload: () => void;
  renameToolset: (toolsetId: string, name: string) => Promise<void>;
  selectedToolset: Toolset | null;
  selectedToolsetId: string | null;
  selectToolset: (toolsetId: string) => void;
  state: LoadState;
};

export function useToolCatalog(): UseToolCatalogResult {
  const sourceIdRef = useRef(`tool-catalog:${Math.random().toString(36).slice(2)}`);
  const itemsRef = useRef<Toolset[]>([]);
  const [items, setItems] = useState<Toolset[]>([]);
  const [selectedToolsetId, setSelectedToolsetId] = useState<string | null>(() =>
    readStoredToolsetId(),
  );
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const [isCreatingToolset, setIsCreatingToolset] = useState(false);
  const [pendingRenameToolsetId, setPendingRenameToolsetId] = useState<string | null>(null);
  const clearPendingRenameToolset = useCallback(() => {
    setPendingRenameToolsetId(null);
  }, []);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setState("loading");
      setError(null);

      try {
        const response = await getToolsets();
        if (cancelled) return;
        itemsRef.current = response.items;
        setItems(response.items);
        setSelectedToolsetId((current) => {
          const resolved = resolveSelectedToolsetId(response.items, current);
          writeStoredToolsetId(resolved);
          return resolved;
        });
        setState("ready");
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "工具集载入失败。");
        setState("error");
      }
    };

    void load();
    return () => { cancelled = true; };
  }, [requestKey]);

  useEffect(() =>
    subscribeToolCatalogChanges((change) => {
      if (change.sourceId === sourceIdRef.current) return;
      if (change.kind === "toolsets") {
        setRequestKey((current) => current + 1);
      }
    }),
  []);

  const selectToolset = useCallback((toolsetId: string) => {
    if (!itemsRef.current.some((item) => item.category_id === toolsetId)) {
      return;
    }
    setSelectedToolsetId(toolsetId);
    writeStoredToolsetId(toolsetId);
  }, []);

  const selectedToolset = useMemo(
    () => items.find((item) => item.category_id === selectedToolsetId) ?? null,
    [items, selectedToolsetId],
  );

  const createToolset = useCallback(async () => {
    setIsCreatingToolset(true);
    setError(null);
    try {
      const created = await createToolsetRequest();
      const nextItems = [...itemsRef.current, created];
      itemsRef.current = nextItems;
      setItems(nextItems);
      setSelectedToolsetId(created.category_id);
      writeStoredToolsetId(created.category_id);
      setPendingRenameToolsetId(created.category_id);
      publishToolCatalogChange({ kind: "toolsets", sourceId: sourceIdRef.current });
      dispatchProjectCatalogChanged();
      return created;
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "工具集创建失败。");
      throw createError;
    } finally {
      setIsCreatingToolset(false);
    }
  }, []);

  const deleteToolset = useCallback(async (toolsetId: string) => {
    const toolset = itemsRef.current.find((item) => item.category_id === toolsetId);
    if (!toolset) {
      const message = "工具集不存在。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      await deleteToolsetRequest(toolsetId);
      const nextItems = itemsRef.current.filter((item) => item.category_id !== toolsetId);
      itemsRef.current = nextItems;
      setItems(nextItems);
      setSelectedToolsetId((current) => {
        const resolved = current === toolsetId
          ? resolveSelectedToolsetId(nextItems, null)
          : current;
        writeStoredToolsetId(resolved);
        return resolved;
      });
      publishToolCatalogChange({ kind: "toolsets", sourceId: sourceIdRef.current });
      dispatchProjectCatalogChanged();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "工具集删除失败。");
      throw deleteError;
    }
  }, []);

  const reload = useCallback(() => setRequestKey((current) => current + 1), []);

  const renameToolset = useCallback(async (toolsetId: string, name: string) => {
    const normalizedName = name.trim();
    if (!normalizedName) {
      const message = "工具集名称不能为空。";
      setError(message);
      throw new Error(message);
    }
    setError(null);
    try {
      const updated = await renameToolsetRequest(toolsetId, normalizedName);
      const nextItems = itemsRef.current.map((item) =>
        item.category_id === toolsetId ? updated : item,
      );
      itemsRef.current = nextItems;
      setItems(nextItems);
      publishToolCatalogChange({ kind: "toolsets", sourceId: sourceIdRef.current });
      dispatchProjectCatalogChanged();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "工具集重命名失败。");
      throw renameError;
    }
  }, []);

  return useMemo(() => ({
    clearPendingRenameToolset,
    createToolset,
    error,
    deleteToolset,
    isCreatingToolset,
    items,
    pendingRenameToolsetId,
    reload,
    renameToolset,
    selectedToolset,
    selectedToolsetId,
    selectToolset,
    state,
  }), [
    clearPendingRenameToolset,
    createToolset,
    deleteToolset,
    error,
    isCreatingToolset,
    items,
    pendingRenameToolsetId,
    reload,
    renameToolset,
    selectedToolset,
    selectedToolsetId,
    selectToolset,
    state,
  ]);
}

function resolveSelectedToolsetId(
  items: readonly Toolset[],
  requestedToolsetId: string | null,
) {
  if (requestedToolsetId && items.some((item) => item.category_id === requestedToolsetId)) {
    return requestedToolsetId;
  }
  return (
    items[0]?.category_id ??
    null
  );
}

function readStoredToolsetId() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOOLSET_SELECTION_KEY);
  } catch {
    return null;
  }
}

function writeStoredToolsetId(toolsetId: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (toolsetId) {
      window.localStorage.setItem(TOOLSET_SELECTION_KEY, toolsetId);
    } else {
      window.localStorage.removeItem(TOOLSET_SELECTION_KEY);
    }
  } catch {
    // 当前会话仍可使用，持久化失败不阻断操作。
  }
}

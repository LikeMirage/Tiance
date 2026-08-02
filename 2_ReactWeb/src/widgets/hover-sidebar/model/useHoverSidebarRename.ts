import { useCallback, useEffect, useRef, useState } from "react";

import type { HoverSidebarSubItem } from "./sidebarItems";

type UseHoverSidebarRenameInput = {
  clearPendingRename: () => void;
  pendingRenameId: string | null;
  renameItem: (itemId: string, name: string) => Promise<void>;
};

export function useHoverSidebarRename({
  clearPendingRename,
  pendingRenameId,
  renameItem,
}: UseHoverSidebarRenameInput) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isCommittingRef = useRef(false);
  const focusTimerRef = useRef<number | null>(null);

  const focusInput = useCallback(() => {
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
    }
    focusTimerRef.current = window.setTimeout(() => {
      focusTimerRef.current = null;
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    return () => {
      if (focusTimerRef.current !== null) {
        window.clearTimeout(focusTimerRef.current);
        focusTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!pendingRenameId) return;
    setRenamingId(pendingRenameId);
    clearPendingRename();
  }, [clearPendingRename, pendingRenameId]);

  useEffect(() => {
    if (!renamingId) return;
    return focusInput();
  }, [focusInput, renamingId]);

  const commitRename = useCallback(async (
    subitem: HoverSidebarSubItem,
    name: string,
  ) => {
    if (isCommittingRef.current) return;
    const normalizedName = name.trim();
    if (!normalizedName || normalizedName === subitem.label) {
      setRenamingId(null);
      return;
    }
    isCommittingRef.current = true;
    try {
      await renameItem(subitem.id, normalizedName);
      setRenamingId(null);
    } catch {
      focusInput();
    } finally {
      isCommittingRef.current = false;
    }
  }, [focusInput, renameItem]);

  const cancelRename = useCallback(() => {
    if (!isCommittingRef.current) setRenamingId(null);
  }, []);

  return {
    cancelRename,
    commitRename,
    inputRef,
    renamingId,
    setRenamingId,
  };
}

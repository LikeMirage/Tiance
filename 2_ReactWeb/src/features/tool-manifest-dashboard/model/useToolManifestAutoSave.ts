import { useCallback, useEffect, useRef } from "react";

type ToolManifestAutoSaveState = "idle" | "saving" | "saved" | "error";

type ToolManifestAutoSaveOptions = {
  canSave: boolean;
  content: string;
  isDirty: boolean;
  onSave: (content: string) => Promise<boolean>;
  saveState: ToolManifestAutoSaveState;
};

const TOOL_MANIFEST_AUTO_SAVE_DELAY_MS = 300;

export function useToolManifestAutoSave({
  canSave,
  content,
  isDirty,
  onSave,
  saveState,
}: ToolManifestAutoSaveOptions) {
  const hasPendingAutoSaveRef = useRef(false);

  const markPendingAutoSave = useCallback(() => {
    hasPendingAutoSaveRef.current = true;
  }, []);

  useEffect(() => {
    if (!canSave || !isDirty || saveState === "saving" || !hasPendingAutoSaveRef.current) {
      return;
    }

    const contentSnapshot = content;
    const timer = window.setTimeout(() => {
      hasPendingAutoSaveRef.current = false;
      void onSave(contentSnapshot).catch(() => undefined);
    }, TOOL_MANIFEST_AUTO_SAVE_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [canSave, content, isDirty, onSave, saveState]);

  return markPendingAutoSave;
}

import { useCallback, useEffect, useRef, useState } from "react";

import type { DesktopFileDropEvent } from "../../desktop-shell/model/desktopFileDropBridge";
import type { ProjectFolderImportSummary } from "./useProjectCatalog";

export type ProjectFolderDropImportNotice =
  | "folders_only"
  | "import_failed"
  | "native_paths_unavailable";

type UseProjectFolderDropImportOptions = {
  categoryId: string | null;
  createProjectsFromFolders: (rootPaths: string[]) => Promise<ProjectFolderImportSummary>;
};

export function useProjectFolderDropImport({
  categoryId,
  createProjectsFromFolders,
}: UseProjectFolderDropImportOptions) {
  const [isImporting, setIsImporting] = useState(false);
  const [notice, setNotice] = useState<ProjectFolderDropImportNotice | null>(null);
  const activeOperationRef = useRef(0);
  const isImportingRef = useRef(false);

  useEffect(() => {
    activeOperationRef.current += 1;
    isImportingRef.current = false;
    setIsImporting(false);
    setNotice(null);
    return () => {
      activeOperationRef.current += 1;
      isImportingRef.current = false;
    };
  }, [categoryId]);

  const handleFileDrop = useCallback((event: DesktopFileDropEvent) => {
    if (event.kind === "unavailable") {
      setNotice("native_paths_unavailable");
      return;
    }

    const rootPaths = event.entries
      .filter((entry) => entry.kind === "folder")
      .map((entry) => entry.path);
    if (rootPaths.length === 0) {
      setNotice("folders_only");
      return;
    }
    if (isImportingRef.current) return;

    isImportingRef.current = true;
    setIsImporting(true);
    setNotice(null);
    const operationId = ++activeOperationRef.current;

    void createProjectsFromFolders(rootPaths)
      .catch(() => {
        if (operationId === activeOperationRef.current) {
          setNotice("import_failed");
        }
      })
      .finally(() => {
        if (operationId === activeOperationRef.current) {
          isImportingRef.current = false;
          setIsImporting(false);
        }
      });
  }, [createProjectsFromFolders]);

  return { handleFileDrop, isImporting, notice };
}

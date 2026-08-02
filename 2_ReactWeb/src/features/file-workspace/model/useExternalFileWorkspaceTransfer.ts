import { useCallback, useEffect, useRef, useState } from "react";

import type { DesktopPathEntry } from "../../../shared/types/desktopShell";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";
import type { FileWorkspaceClipboardState } from "../ui/fileWorkspaceTreeUiTypes";
import {
  readDesktopClipboardPathEntries,
  writeDesktopClipboardPathEntries,
} from "../../desktop-shell/model/desktopClipboard";
import {
  DesktopExternalFileImportUnavailableError,
  importDesktopPathEntriesToWorkspace,
} from "../../desktop-shell/model/desktopExternalFileTransfer";
import type { DesktopFileDropEvent } from "../../desktop-shell/model/desktopFileDropBridge";
import type { UseFileWorkspaceBrowserResult } from "./fileWorkspaceBrowserTypes";

export type ExternalFileWorkspaceTransferNotice =
  | { kind: "clipboard_empty" }
  | { kind: "import_failed" }
  | { kind: "import_partial"; failedCount: number; importedCount: number }
  | { kind: "native_paths_unavailable" }
  | { kind: "unavailable" };

type UseExternalFileWorkspaceTransferOptions = {
  allowImport?: boolean;
  browser: Pick<UseFileWorkspaceBrowserResult, "refreshTree">;
  workspaceKey: string | null;
  workspaceRoot: string | null;
};

export function useExternalFileWorkspaceTransfer({
  allowImport = true,
  browser,
  workspaceKey,
  workspaceRoot,
}: UseExternalFileWorkspaceTransferOptions) {
  const [isImporting, setIsImporting] = useState(false);
  const [notice, setNotice] = useState<ExternalFileWorkspaceTransferNotice | null>(null);
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
  }, [workspaceKey, workspaceRoot]);

  const importEntries = useCallback(async (entries: DesktopPathEntry[]) => {
    if (!allowImport || !workspaceKey || !workspaceRoot || isImportingRef.current) return;

    isImportingRef.current = true;
    setIsImporting(true);
    setNotice(null);
    const operationId = ++activeOperationRef.current;

    try {
      const result = await importDesktopPathEntriesToWorkspace(entries, workspaceRoot);
      if (operationId !== activeOperationRef.current) return;

      if (result.imported.length > 0) {
        browser.refreshTree();
      }

      if (result.failures.length === 0) {
        return;
      }
      if (result.imported.length > 0) {
        setNotice({
          kind: "import_partial",
          failedCount: result.failures.length,
          importedCount: result.imported.length,
        });
        return;
      }
      setNotice({ kind: "import_failed" });
    } catch (error) {
      if (operationId !== activeOperationRef.current) return;
      setNotice({
        kind: error instanceof DesktopExternalFileImportUnavailableError
          ? "unavailable"
          : "import_failed",
      });
    } finally {
      if (operationId === activeOperationRef.current) {
        isImportingRef.current = false;
        setIsImporting(false);
      }
    }
  }, [allowImport, browser, workspaceKey, workspaceRoot]);

  const handleFileDrop = useCallback((event: DesktopFileDropEvent) => {
    if (event.kind === "unavailable") {
      setNotice({ kind: "native_paths_unavailable" });
      return;
    }
    void importEntries(event.entries);
  }, [importEntries]);

  const copyNodesToSystemClipboard = useCallback(async (
    nodes: FileWorkspaceBrowserNode[],
  ): Promise<string[] | null> => {
    if (!workspaceRoot) return null;
    const paths = nodes
      .map((node) => resolveWorkspaceNodePath(workspaceRoot, node.path))
      .filter((path): path is string => path !== null);
    if (paths.length !== nodes.length || paths.length === 0) {
      setNotice({ kind: "unavailable" });
      return null;
    }
    try {
      const written = await writeDesktopClipboardPathEntries(paths);
      if (!written) {
        setNotice({ kind: "unavailable" });
        return null;
      }
      setNotice(null);
      return paths;
    } catch {
      setNotice({ kind: "unavailable" });
      return null;
    }
  }, [workspaceRoot]);

  const resolveSystemClipboardPaste = useCallback(async (
    clipboard: FileWorkspaceClipboardState,
  ): Promise<"internal" | "handled"> => {
    if (clipboard?.mode === "cut") return "internal";
    if (!allowImport) return clipboard ? "internal" : "handled";
    try {
      const entries = await readDesktopClipboardPathEntries();
      if (clipboard?.systemSourcePaths && samePaths(
        entries.map((entry) => entry.path),
        clipboard.systemSourcePaths,
      )) {
        return "internal";
      }
      if (entries.length === 0) {
        if (clipboard) return "internal";
        setNotice({ kind: "clipboard_empty" });
        return "handled";
      }
      await importEntries(entries);
      return "handled";
    } catch {
      setNotice({ kind: "unavailable" });
      return "handled";
    }
  }, [allowImport, importEntries]);

  return {
    copyNodesToSystemClipboard,
    handleFileDrop,
    isImporting,
    notice,
    resolveSystemClipboardPaste,
  };
}

function resolveWorkspaceNodePath(workspaceRoot: string, relativePath: string): string | null {
  const normalizedRoot = workspaceRoot.trim().replace(/[\\/]+$/, "");
  const normalizedPath = relativePath.trim().replace(/\\/g, "/").replace(/^\/+/, "");
  if (!normalizedRoot || !normalizedPath || normalizedPath.split("/").includes("..")) {
    return null;
  }
  return `${normalizedRoot}/${normalizedPath}`;
}

function samePaths(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const normalize = (path: string) => path.trim().replace(/\\/g, "/").toLocaleLowerCase();
  const leftPaths = left.map(normalize).sort();
  const rightPaths = right.map(normalize).sort();
  return leftPaths.every((path, index) => path === rightPaths[index]);
}

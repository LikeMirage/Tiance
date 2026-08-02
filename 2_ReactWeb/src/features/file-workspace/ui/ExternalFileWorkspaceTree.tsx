import type { KeyboardEvent } from "react";

import { useDesktopFileDropTarget } from "../../desktop-shell/model/useDesktopFileDropTarget";
import { useI18n } from "../../../shared/i18n";
import { useExternalFileWorkspaceTransfer } from "../model/useExternalFileWorkspaceTransfer";
import {
  FileWorkspaceTree,
  type FileWorkspaceTreeProps,
} from "./FileWorkspaceTree";
import "./external-file-workspace-tree.css";

type ExternalFileWorkspaceTreeProps = Omit<
  FileWorkspaceTreeProps,
  "onCopyNodesToSystemClipboard" | "onPasteFromSystemClipboard"
> & {
  allowExternalImport?: boolean;
  surfaceAriaLabel: string;
  workspaceKey: string | null;
  workspaceRoot: string | null;
};

export function ExternalFileWorkspaceTree({
  allowExternalImport = true,
  surfaceAriaLabel,
  workspaceKey,
  workspaceRoot,
  ...treeProps
}: ExternalFileWorkspaceTreeProps) {
  const { t } = useI18n();
  const transfer = useExternalFileWorkspaceTransfer({
    allowImport: allowExternalImport,
    browser: treeProps.browser,
    workspaceKey,
    workspaceRoot,
  });
  const { isFileDragOver, targetRef } = useDesktopFileDropTarget<HTMLDivElement>({
    enabled: allowExternalImport,
    onFileDrop: transfer.handleFileDrop,
    scopeKey: workspaceKey,
  });
  const notice = getTransferNotice(transfer.notice, t);

  return (
    <div
      ref={targetRef}
      className={
        isFileDragOver
          ? "external-file-workspace-tree external-file-workspace-tree--drag-over"
          : "external-file-workspace-tree"
      }
      role="region"
      aria-label={surfaceAriaLabel}
      onKeyDownCapture={(event) => {
        if (!allowExternalImport || !isExternalFilePasteShortcut(event)) return;
        if (event.target instanceof HTMLElement && event.target.closest(".fwt-tree")) return;
        event.preventDefault();
        void transfer.resolveSystemClipboardPaste(null);
      }}
    >
      {isFileDragOver ? (
        <div className="external-file-workspace-tree__notice" role="status">
          {t("fileWorkspace.external.dropHint")}
        </div>
      ) : transfer.isImporting ? (
        <div className="external-file-workspace-tree__notice" role="status">
          {t("fileWorkspace.external.importing")}
        </div>
      ) : notice ? (
        <div
          className="external-file-workspace-tree__notice external-file-workspace-tree__notice--error"
          role="status"
        >
          {notice}
        </div>
      ) : null}
      <FileWorkspaceTree
        {...treeProps}
        onCopyNodesToSystemClipboard={transfer.copyNodesToSystemClipboard}
        onPasteFromSystemClipboard={
          allowExternalImport ? transfer.resolveSystemClipboardPaste : undefined
        }
      />
    </div>
  );
}

function isExternalFilePasteShortcut(event: KeyboardEvent<HTMLElement>) {
  return (
    (event.ctrlKey || event.metaKey) &&
    !event.altKey &&
    !event.shiftKey &&
    event.key.toLocaleLowerCase() === "v"
  );
}

function getTransferNotice(
  notice: ReturnType<typeof useExternalFileWorkspaceTransfer>["notice"],
  t: ReturnType<typeof useI18n>["t"],
) {
  switch (notice?.kind) {
    case "clipboard_empty":
      return t("fileWorkspace.external.clipboardEmpty");
    case "import_failed":
      return t("fileWorkspace.external.importFailed");
    case "import_partial":
      return t("fileWorkspace.external.importPartial", {
        failedCount: notice.failedCount,
        importedCount: notice.importedCount,
      });
    case "native_paths_unavailable":
      return t("fileWorkspace.external.pathsUnavailable");
    case "unavailable":
      return t("fileWorkspace.external.unavailable");
    default:
      return null;
  }
}

import { useCallback, useEffect, useState, useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

import type { LocalFileNameAvailability, LocalFileReference } from "../../../entities/local-file/model/localFileReference";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
  type ContextMenuPosition,
} from "../../../shared/ui/context-menu";

export type MarkdownLocalFileActions = {
  fileNames?: LocalFileNameAvailability;
  onError?: (message: string | null) => void;
  onOpenDefault: (reference: LocalFileReference) => Promise<void> | void;
  onOpenInWorkspace: (reference: LocalFileReference) => Promise<void> | void;
  onReveal: (reference: LocalFileReference) => Promise<void> | void;
  onCopyPath: (reference: LocalFileReference) => Promise<void> | void;
};

const noFileNames: LocalFileNameAvailability = {
  getSnapshot: () => null,
  subscribe: () => () => undefined,
};

export function MarkdownLocalFileLink({
  actions,
  children,
  reference,
}: {
  actions: MarkdownLocalFileActions;
  children: ReactNode;
  reference: LocalFileReference;
}) {
  const [menuPosition, setMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const fileNames = reference.lookup === "name" ? actions.fileNames ?? noFileNames : noFileNames;
  const fileNameIndex = useSyncExternalStore(fileNames.subscribe, fileNames.getSnapshot, fileNames.getSnapshot);
  const resolved = reference.lookup === "name" ? fileNameIndex?.get(reference.name.toLowerCase()) : reference;
  const absolutePath = resolved?.absolutePath;
  useEffect(() => { setMenuPosition(null); }, [absolutePath]);

  const run = useCallback(async (action: () => Promise<void> | void) => {
    if (isRunning) return;
    setMenuPosition(null);
    setIsRunning(true);
    actions.onError?.(null);
    try {
      await action();
    } catch (error) {
      actions.onError?.(error instanceof Error ? error.message : "文件操作失败。");
    } finally {
      setIsRunning(false);
    }
  }, [actions, isRunning]);

  const openDefaultAction = reference.scope === "workspace"
    ? () => actions.onOpenInWorkspace(reference)
    : () => actions.onReveal(reference);

  const handleContextMenu = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setMenuPosition({ x: event.clientX, y: event.clientY });
  };

  // A name is just text until the current project's complete index proves a
  // unique file exists. Keep click-time lookup to recheck moves or deletions.
  if (!resolved) return <span>{children}</span>;

  return (
    <>
      <a
        aria-disabled={isRunning ? "true" : undefined}
        className="markdown-preview__local-file-link"
        href="#"
        title={absolutePath}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void run(openDefaultAction);
        }}
        onContextMenu={handleContextMenu}
      >
        {children}
      </a>
      {menuPosition ? (
        <ContextMenu
          minWidth={176}
          onClose={() => setMenuPosition(null)}
          position={menuPosition}
        >
          {reference.scope === "workspace" ? (
            <>
              <ContextMenuItem onSelect={() => void run(() => actions.onOpenInWorkspace(reference))}>
                在工作区中查看
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          ) : null}
          <ContextMenuItem onSelect={() => void run(() => actions.onReveal(reference))}>
            在资源管理器中查看
          </ContextMenuItem>
          <ContextMenuItem onSelect={() => void run(() => actions.onOpenDefault(reference))}>
            使用系统默认应用打开
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem onSelect={() => void run(() => actions.onCopyPath(reference))}>
            复制文件路径
          </ContextMenuItem>
        </ContextMenu>
      ) : null}
    </>
  );
}

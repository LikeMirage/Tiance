import { useCallback, useEffect, useMemo } from "react";

import {
  resolveLocalFileReference,
  type LocalFileReference,
} from "../../../entities/local-file/model/localFileReference";
import { openDesktopLocalPath, revealDesktopLocalPath } from "../../../services/desktop/localPathApi";
import type { MarkdownLocalFileActions } from "../../markdown-preview/ui/MarkdownLocalFileLink";
import { resolveChatLocalFileTarget } from "./chatLocalFileTarget";
import { createChatLocalFileNameAvailability } from "./chatLocalFileNameIndex";

type Options = {
  onError: (message: string | null) => void;
  onOpenProjectFile?: (path: string, line: number | null) => Promise<void> | void;
  projectId: string | null;
  projectRootPath: string;
};

export function useChatLocalFileLinks({
  onError,
  onOpenProjectFile,
  projectId,
  projectRootPath,
}: Options) {
  const requestScope = useMemo(() => ({ controller: null as AbortController | null }), [projectId, projectRootPath]);
  const fileNames = useMemo(() => createChatLocalFileNameAvailability({
    projectId, projectRootPath,
  }), [projectId, projectRootPath]);
  useEffect(() => {
    const controller = new AbortController();
    requestScope.controller = controller;
    return () => controller.abort();
  }, [requestScope]);
  const resolveReference = useCallback((href: string) => resolveLocalFileReference(href, {
    projectId,
    projectRootPath,
  }), [projectId, projectRootPath]);

  const actions = useMemo<MarkdownLocalFileActions>(() => {
    const target = async (reference: LocalFileReference) => {
      const signal = requestScope.controller?.signal;
      if (!signal) throw new DOMException("File view is not active", "AbortError");
      signal.throwIfAborted();
      const resolved = await resolveChatLocalFileTarget(reference, {
        projectId, projectRootPath,
      }, undefined, signal);
      signal.throwIfAborted();
      return resolved;
    };
    return {
      fileNames,
      onError: (message) => { if (requestScope.controller && !requestScope.controller.signal.aborted) onError(message); },
      onOpenDefault: async (reference) => {
        await openDesktopLocalPath((await target(reference)).absolutePath);
      },
      onOpenInWorkspace: async (reference) => {
        const resolved = await target(reference);
        assertWorkspaceReference(resolved, projectId, onOpenProjectFile);
        await onOpenProjectFile?.(resolved.projectPath, resolved.line);
      },
      onReveal: async (reference) => {
        await revealDesktopLocalPath((await target(reference)).absolutePath);
      },
      onCopyPath: async (reference) => {
        await navigator.clipboard.writeText((await target(reference)).absolutePath);
      },
    };
  }, [fileNames, onError, onOpenProjectFile, projectId, projectRootPath, requestScope]);

  return { actions, resolveReference };
}

function assertWorkspaceReference(
  reference: LocalFileReference,
  projectId: string | null,
  onOpenProjectFile: Options["onOpenProjectFile"],
): asserts reference is LocalFileReference & { projectPath: string } {
  if (reference.scope !== "workspace" || reference.projectPath === null || !projectId) {
    throw new Error("该路径不属于当前工作区。");
  }
  if (!onOpenProjectFile) {
    throw new Error("当前工作区没有配置文件查看能力。");
  }
}

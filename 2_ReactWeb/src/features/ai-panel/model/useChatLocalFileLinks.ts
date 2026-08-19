import { useCallback, useMemo } from "react";

import {
  resolveLocalFileReference,
  type LocalFileReference,
} from "../../../entities/local-file/model/localFileReference";
import { openDesktopLocalPath, revealDesktopLocalPath } from "../../../services/desktop/localPathApi";
import type { MarkdownLocalFileActions } from "../../markdown-preview/ui/MarkdownLocalFileLink";

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
  const resolveReference = useCallback((href: string) => resolveLocalFileReference(href, {
    projectId,
    projectRootPath,
  }), [projectId, projectRootPath]);

  const actions = useMemo<MarkdownLocalFileActions>(() => ({
    onError,
    onOpenDefault: async (reference) => {
      await openDesktopLocalPath(reference.absolutePath);
    },
    onOpenInWorkspace: async (reference) => {
      assertWorkspaceReference(reference, projectId, onOpenProjectFile);
      await onOpenProjectFile?.(reference.projectPath!, reference.line);
    },
    onReveal: async (reference) => {
      await revealDesktopLocalPath(reference.absolutePath);
    },
  }), [onError, onOpenProjectFile, projectId]);

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

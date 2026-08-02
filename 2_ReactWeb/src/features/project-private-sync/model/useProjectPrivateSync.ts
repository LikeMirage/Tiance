import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  getGithubProjectSyncBoard,
  type GithubProjectSyncBoard,
} from "../../../services/github/githubSyncApi";
import { useGithubSync } from "../../github-sync/model/useGithubSync";

export function useProjectPrivateSync(active: boolean) {
  const sync = useGithubSync("project", false);
  const requestRef = useRef<AbortController | null>(null);
  const [board, setBoard] = useState<GithubProjectSyncBoard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const next = await getGithubProjectSyncBoard(controller.signal);
      if (controller.signal.aborted) return null;
      setBoard(next);
      const changedPaths = new Set(
        next.projects.flatMap((project) => project.files)
          .filter((file) => file.status !== "same")
          .map((file) => file.path),
      );
      setSelectedPaths((current) => new Set(
        [...current].filter((path) => changedPaths.has(path)),
      ));
      return next;
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "无法读取私人项目仓库。")
      }
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (active) void refresh();
    else requestRef.current?.abort();
  }, [active, refresh]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const changedFiles = useMemo(
    () => board?.projects.flatMap((project) => project.files)
      .filter((file) => file.status !== "same") ?? [],
    [board],
  );

  const togglePaths = useCallback((paths: readonly string[]) => {
    setSelectedPaths((current) => {
      const next = new Set(current);
      const select = paths.some((path) => !next.has(path));
      for (const path of paths) {
        if (select) next.add(path);
        else next.delete(path);
      }
      return next;
    });
  }, []);

  const preview = useCallback(async (direction: "push" | "pull") => {
    if (!board || selectedPaths.size === 0) return false;
    const projectIds = new Set<string>();
    for (const project of board.projects) {
      if (project.files.some((file) => selectedPaths.has(file.path))) {
        projectIds.add(project.projectId);
      }
    }
    return Boolean(await sync.preview(direction, {
      paths: [...selectedPaths].sort(),
      projectIds: [...projectIds].sort(),
    }));
  }, [board, selectedPaths, sync.preview]);

  const apply = useCallback(async (commitMessage: string | null) => {
    if (!await sync.apply(commitMessage)) return false;
    setSelectedPaths(new Set());
    dispatchProjectCatalogChanged();
    await refresh();
    return true;
  }, [refresh, sync.apply]);

  return {
    apply,
    board,
    changedFiles,
    clearPlan: sync.clearPlan,
    error: error ?? sync.error,
    loading: loading || sync.loading,
    plan: sync.plan,
    preview,
    refresh,
    selectedPaths,
    togglePaths,
  };
}

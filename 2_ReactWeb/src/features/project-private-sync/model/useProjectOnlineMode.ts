import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getDefaultProjectMarketSource,
  getProjectMarketSettings,
  selectProjectOnlineSource,
} from "../../../services/project-market/projectMarketApi";
import {
  getGithubSyncOverview,
  saveGithubSyncBinding,
  type GithubSyncBinding,
} from "../../../services/github/githubSyncApi";
import { normalizeOnlineMarketSourceText } from "../../../shared/online-market/OnlineMarketBoardControls";
import { subscribeGithubSyncBindingChanged } from "../../github-sync/model/githubSyncBindingEvents";

type GithubRepositoryChoice = {
  defaultBranch: string;
  fullName: string;
};

export function useProjectOnlineMode(active: boolean) {
  const requestRef = useRef<AbortController | null>(null);
  const defaultSource = getDefaultProjectMarketSource("project");
  const [source, setSource] = useState(defaultSource);
  const [binding, setBinding] = useState<GithubSyncBinding | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setReady(false);
    setError(null);
    try {
      const [settings, overview] = await Promise.all([
        getProjectMarketSettings("project", controller.signal),
        getGithubSyncOverview("project", controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setSource(settings.source);
      setBinding(overview.binding);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(errorMessage(reason, "项目在线源读取失败。"));
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setReady(true);
      }
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (active) void load();
    else requestRef.current?.abort();
  }, [active, load]);
  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => subscribeGithubSyncBindingChanged((change) => {
    if (change.collection !== "project") return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    void (async () => {
      try {
        await selectProjectOnlineSource(
          change.binding?.repository ?? defaultSource,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        await load();
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(errorMessage(reason, "无法切换项目在线模式。"));
        }
      }
    })();
  }), [defaultSource, load]);

  const selectDefault = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const settings = await selectProjectOnlineSource(defaultSource, controller.signal);
      if (controller.signal.aborted) return;
      setSource(settings.source);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(errorMessage(reason, "无法切换到默认项目市场。"));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [defaultSource]);

  const selectPrivate = useCallback(async (repository: GithubRepositoryChoice) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const nextBinding = await saveGithubSyncBinding("project", {
        branch: repository.defaultBranch,
        remotePath: "",
        repository: repository.fullName,
      }, controller.signal);
      const settings = await selectProjectOnlineSource(nextBinding.repository, controller.signal);
      if (controller.signal.aborted) return;
      setBinding(nextBinding);
      setSource(settings.source);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(errorMessage(reason, "无法绑定私人项目仓库。"));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  const privateMode = Boolean(binding && (
    normalizeOnlineMarketSourceText(binding.repository)
      === normalizeOnlineMarketSourceText(source)
  ));
  const sourceLabel = useMemo(() => repositoryLabel(binding?.repository ?? source), [binding, source]);

  return {
    binding,
    defaultSource,
    error,
    load,
    loading,
    privateMode,
    ready,
    selectDefault,
    selectPrivate,
    source,
    sourceLabel,
  };
}

function repositoryLabel(source: string) {
  try {
    const url = new URL(source);
    return url.pathname.replace(/^\/+|\/+$/g, "").replace(/\.git$/i, "");
  } catch {
    return source;
  }
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}

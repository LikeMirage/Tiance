import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyGithubSyncPlan,
  createGithubSyncPlan,
  deleteGithubSyncBinding,
  getGithubSyncOverview,
  saveGithubSyncBinding,
  type GithubSyncCollection,
  type GithubSyncOverview,
  type GithubSyncPlan,
} from "../../../services/github/githubSyncApi";
import { HttpRequestError } from "../../../services/http/httpClient";
import { dispatchGithubSyncBindingChanged } from "./githubSyncBindingEvents";

export function useGithubSync(collection: GithubSyncCollection, active: boolean) {
  const requestRef = useRef<AbortController | null>(null);
  const [overview, setOverview] = useState<GithubSyncOverview | null>(null);
  const [plan, setPlan] = useState<GithubSyncPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<
    "bindingSaved" | "bindingRemoved" | "pushComplete" | "pullComplete" | null
  >(null);

  const run = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      return await operation(controller.signal);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(toGithubSyncError(reason));
      }
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    const value = await run((signal) => getGithubSyncOverview(collection, signal));
    if (value) setOverview(value);
    return value;
  }, [collection, run]);

  const bind = useCallback(async (repository: string, branch: string, remotePath: string) => {
    const binding = await run((signal) => saveGithubSyncBinding(
      collection,
      { repository, branch, remotePath },
      signal,
    ));
    if (!binding) return false;
    setOverview((current) => current ? { ...current, binding } : current);
    setPlan(null);
    setResult("bindingSaved");
    dispatchGithubSyncBindingChanged({ binding, collection });
    return true;
  }, [collection, run]);

  const unbind = useCallback(async () => {
    const response = await run((signal) => deleteGithubSyncBinding(collection, signal));
    if (!response) return false;
    setOverview((current) => current ? { ...current, binding: null } : current);
    setPlan(null);
    setResult("bindingRemoved");
    dispatchGithubSyncBindingChanged({ binding: null, collection });
    return true;
  }, [collection, run]);

  const preview = useCallback(async (
    direction: "push" | "pull",
    selection?: { paths: string[]; projectIds: string[] },
  ) => {
    const value = await run((signal) => createGithubSyncPlan(
      collection,
      direction,
      selection,
      signal,
    ));
    if (value) setPlan(value);
    return value;
  }, [collection, run]);

  const apply = useCallback(async (commitMessage: string | null) => {
    if (!plan) return false;
    const value = await run((signal) => applyGithubSyncPlan(plan.planId, commitMessage, signal));
    if (!value) return false;
    setResult(value.direction === "push" ? "pushComplete" : "pullComplete");
    setPlan(null);
    return true;
  }, [plan, run]);

  const clearPlan = useCallback(() => {
    setPlan(null);
    setError(null);
  }, []);

  useEffect(() => {
    if (active) void refresh();
    else requestRef.current?.abort();
  }, [active, refresh]);

  useEffect(() => () => requestRef.current?.abort(), []);

  return {
    apply,
    bind,
    clearPlan,
    error,
    loading,
    overview,
    plan,
    preview,
    refresh,
    result,
    unbind,
  };
}

function toGithubSyncError(reason: unknown) {
  if (reason instanceof HttpRequestError && reason.status === 404) {
    return "当前前端与后端版本不一致，或同步接口尚未启动。请完整重启天策后重试。";
  }
  return reason instanceof Error ? reason.message : "GitHub 同步操作失败。";
}

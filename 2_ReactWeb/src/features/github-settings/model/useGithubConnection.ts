import { useCallback, useEffect, useRef, useState } from "react";

import {
  getGithubConnection,
  logoutGithub,
  pollGithubDeviceFlow,
  startGithubDeviceFlow,
  type GithubConnectionStatus,
  type GithubDeviceFlow,
} from "../../../services/github/githubConnectionApi";

export function useGithubConnection() {
  const [connection, setConnection] = useState<GithubConnectionStatus | null>(null);
  const [flow, setFlow] = useState<GithubDeviceFlow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const loadAbortRef = useRef<AbortController | null>(null);

  const clearPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    pollAbortRef.current?.abort();
    pollAbortRef.current = null;
  }, []);

  const reload = useCallback(async () => {
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      setConnection(await getGithubConnection(controller.signal));
    } catch (loadError) {
      if (!controller.signal.aborted) setError(toErrorMessage(loadError));
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
      if (loadAbortRef.current === controller) loadAbortRef.current = null;
    }
  }, []);

  useEffect(() => {
    void reload();
    return () => {
      loadAbortRef.current?.abort();
      clearPolling();
    };
  }, [clearPolling, reload]);

  const schedulePoll = useCallback((activeFlow: GithubDeviceFlow, delaySeconds: number) => {
    clearPolling();
    pollTimerRef.current = window.setTimeout(async () => {
      const controller = new AbortController();
      pollAbortRef.current = controller;
      try {
        const result = await pollGithubDeviceFlow(activeFlow.flowId, controller.signal);
        if (result.status === "completed" && result.connection) {
          setConnection(result.connection);
          setFlow(null);
          setError(null);
          return;
        }
        schedulePoll(activeFlow, result.retryAfter ?? activeFlow.interval);
      } catch (pollError) {
        if (!controller.signal.aborted) {
          setError(toErrorMessage(pollError));
          setFlow(null);
        }
      } finally {
        if (pollAbortRef.current === controller) pollAbortRef.current = null;
      }
    }, Math.max(1, delaySeconds) * 1000);
  }, [clearPolling]);

  const startLogin = useCallback(async () => {
    clearPolling();
    setIsStarting(true);
    setError(null);
    try {
      const nextFlow = await startGithubDeviceFlow();
      setFlow(nextFlow);
      await openExternalUrl(nextFlow.verificationUri);
      schedulePoll(nextFlow, nextFlow.interval);
    } catch (startError) {
      setError(toErrorMessage(startError));
    } finally {
      setIsStarting(false);
    }
  }, [clearPolling, schedulePoll]);

  const cancelLogin = useCallback(() => {
    clearPolling();
    setFlow(null);
  }, [clearPolling]);

  const logout = useCallback(async () => {
    clearPolling();
    setIsLoggingOut(true);
    setError(null);
    try {
      await logoutGithub();
      setConnection((current) => current ? { ...current, connected: false, account: null, repositories: [] } : null);
      setFlow(null);
    } catch (logoutError) {
      setError(toErrorMessage(logoutError));
    } finally {
      setIsLoggingOut(false);
    }
  }, [clearPolling]);

  return {
    cancelLogin,
    connection,
    error,
    flow,
    isLoading,
    isLoggingOut,
    isStarting,
    logout,
    openExternalUrl,
    reload,
    startLogin,
  };
}

async function openExternalUrl(url: string) {
  if (!isAllowedGithubUrl(url)) {
    return;
  }
  const api = window.pywebview?.api;
  if (typeof api?.open_external_url === "function") {
    const opened = await api.open_external_url(url);
    if (opened) return;
  }
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.click();
}

function isAllowedGithubUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname.toLowerCase() === "github.com"
      && !url.username
      && !url.password;
  } catch {
    return false;
  }
}

function toErrorMessage(error: unknown) {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "GitHub 连接失败。";
}

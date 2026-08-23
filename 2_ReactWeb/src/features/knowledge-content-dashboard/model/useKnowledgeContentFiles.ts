import { useEffect, useState } from "react";

import {
  getProjectContentFiles,
  type ProjectContentFile,
} from "../../../services/project/getProjectContentFiles";
import { watchProjectFileEvents } from "../../../services/project/watchProjectFileEvents";

type LoadState = "idle" | "loading" | "ready" | "error";

export function useKnowledgeContentFiles(projectId: string | null) {
  const [items, setItems] = useState<ProjectContentFile[]>([]);
  const [unreadablePaths, setUnreadablePaths] = useState<string[]>([]);
  const [state, setState] = useState<LoadState>(projectId ? "loading" : "idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let activeRequest: AbortController | null = null;
    let refreshTimer: number | null = null;
    let hasLoaded = false;
    let watcherAvailable: boolean | null = null;

    if (!projectId) {
      setItems([]);
      setUnreadablePaths([]);
      setState("idle");
      setError(null);
      return undefined;
    }

    setItems([]);
    setUnreadablePaths([]);
    setState("loading");
    setError(null);

    const loadSnapshot = async () => {
      activeRequest?.abort();
      const request = new AbortController();
      activeRequest = request;
      try {
        const snapshot = await getProjectContentFiles(projectId, { signal: request.signal });
        if (disposed || request.signal.aborted) return;
        setItems(snapshot.items);
        setUnreadablePaths(snapshot.unreadable_paths);
        setState("ready");
        setError(null);
        hasLoaded = true;
      } catch (loadError) {
        if (disposed || request.signal.aborted) return;
        setError(formatLoadError(loadError));
        setState(hasLoaded ? "ready" : "error");
      }
    };

    const scheduleRefresh = () => {
      if (refreshTimer !== null) {
        window.clearTimeout(refreshTimer);
      }
      refreshTimer = window.setTimeout(() => {
        refreshTimer = null;
        void loadSnapshot();
      }, 250);
    };

    void loadSnapshot();
    const stopWatching = watchProjectFileEvents(projectId, {
      onChanged: scheduleRefresh,
      onOverflow: scheduleRefresh,
      onStatusChanged: (available) => {
        if (available && watcherAvailable === false) {
          scheduleRefresh();
        }
        watcherAvailable = available;
      },
    });

    return () => {
      disposed = true;
      activeRequest?.abort();
      stopWatching();
      if (refreshTimer !== null) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [projectId]);

  return { error, items, state, unreadablePaths };
}

function formatLoadError(error: unknown) {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Unable to load project files.";
}

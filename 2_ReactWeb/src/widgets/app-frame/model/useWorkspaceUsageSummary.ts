import { useCallback, useEffect, useRef, useState } from "react";
import { subscribeLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { getWorkspaceStatistics, type WorkspaceStatistics, type WorkspaceStatisticsKind } from "../../../services/workspace/getWorkspaceStatistics";

type State = { key: string; data: WorkspaceStatistics | null; error: boolean };

export function useWorkspaceUsageSummary(kind: WorkspaceStatisticsKind, month: string, enabled: boolean) {
  const key = `${kind}:${month}`;
  const [state, setState] = useState<State>({ key, data: null, error: false });
  const refreshRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let inFlight = false;
    let timer = 0;
    let serial = 0;
    let controller: AbortController | null = null;
    const load = async (force = false) => {
      if (cancelled || (inFlight && !force) || document.visibilityState === "hidden") return;
      controller?.abort();
      controller = new AbortController();
      const requestSerial = ++serial;
      inFlight = true;
      window.clearTimeout(timer);
      try {
        const data = await getWorkspaceStatistics(kind, month, controller.signal);
        if (!cancelled && serial === requestSerial) setState({ key, data, error: false });
      } catch {
        if (!cancelled && serial === requestSerial) setState(current => ({ key, data: current.key === key ? current.data : null, error: true }));
      } finally {
        if (serial === requestSerial) {
          inFlight = false;
          if (!cancelled) timer = window.setTimeout(() => void load(), 30_000);
        }
      }
    };
    const refresh = () => { void load(); };
    refreshRef.current = () => { void load(true); };
    const unsubscribe = subscribeLlmUsageChanged(refresh);
    document.addEventListener("visibilitychange", refresh);
    refresh();
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearTimeout(timer);
      unsubscribe();
      document.removeEventListener("visibilitychange", refresh);
      refreshRef.current = () => {};
    };
  }, [enabled, key, kind, month]);

  const setConversationTotal = useCallback((value: number) => {
    setState(current => current.data ? {
      ...current, data: { ...current.data, conversation_count: value },
    } : current);
    refreshRef.current();
  }, []);

  return {
    data: state.key === key ? state.data : null,
    error: state.key === key && state.error,
    refresh: () => refreshRef.current(),
    setConversationTotal,
  };
}

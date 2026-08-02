import { useCallback, useEffect, useState } from "react";

import type { ToolCallRecordTopTool } from "../../../entities/tool/model/toolCallRecord";
import { getProviderModelUsageSummary } from "../../../services/llm/getProviderModelUsageSummary";
import { getToolCallRecordOverview } from "../../../services/tools/toolCallRecords";
import { getWorkspaceActivitySummary } from "../../../services/workspace/getWorkspaceActivitySummary";

export type UsageMetricState =
  | { state: "loading" }
  | { state: "ready"; value: number }
  | { state: "error" };

export type TopToolsState =
  | { state: "loading" }
  | { state: "ready"; items: ToolCallRecordTopTool[] }
  | { state: "error" };

export type WorkspaceUsageSummary = {
  aiRuntimeTotal: UsageMetricState;
  conversationTotal: UsageMetricState;
  sentMessageTotal: UsageMetricState;
  tokenTotal: UsageMetricState;
  toolCallTotal: UsageMetricState;
  topTools: TopToolsState;
};

export type WorkspaceUsageSummaryModel = {
  setConversationTotal: (value: number) => void;
  summary: WorkspaceUsageSummary;
};

const LOADING_STATE = { state: "loading" } as const;

export function useWorkspaceUsageSummary(enabled: boolean): WorkspaceUsageSummaryModel {
  const [summary, setSummary] = useState<WorkspaceUsageSummary>({
    aiRuntimeTotal: LOADING_STATE,
    conversationTotal: LOADING_STATE,
    sentMessageTotal: LOADING_STATE,
    tokenTotal: LOADING_STATE,
    toolCallTotal: LOADING_STATE,
    topTools: LOADING_STATE,
  });

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setSummary({
      aiRuntimeTotal: LOADING_STATE,
      conversationTotal: LOADING_STATE,
      sentMessageTotal: LOADING_STATE,
      tokenTotal: LOADING_STATE,
      toolCallTotal: LOADING_STATE,
      topTools: LOADING_STATE,
    });

    void getProviderModelUsageSummary(null, { signal: controller.signal })
      .then((response) => {
        if (cancelled) {
          return;
        }
        const value = response.providers.reduce(
          (total, provider) => total + normalizeCount(provider.total_tokens),
          0,
        );
        setSummary((current) => ({
          ...current,
          tokenTotal: { state: "ready", value },
        }));
      })
      .catch((error: unknown) => {
        if (!cancelled && !isAbortError(error)) {
          setSummary((current) => ({ ...current, tokenTotal: { state: "error" } }));
        }
      });

    void getToolCallRecordOverview({ signal: controller.signal })
      .then((response) => {
        if (cancelled) {
          return;
        }
        setSummary((current) => ({
          ...current,
          toolCallTotal: {
            state: "ready",
            value: normalizeCount(response.total_call_count),
          },
          topTools: {
            state: "ready",
            items: response.top_tools,
          },
        }));
      })
      .catch((error: unknown) => {
        if (!cancelled && !isAbortError(error)) {
          setSummary((current) => ({
            ...current,
            toolCallTotal: { state: "error" },
            topTools: { state: "error" },
          }));
        }
      });

    void getWorkspaceActivitySummary({ signal: controller.signal })
      .then((response) => {
        if (cancelled) {
          return;
        }
        setSummary((current) => ({
          ...current,
          aiRuntimeTotal: {
            state: "ready",
            value: normalizeCount(response.ai_runtime_ms),
          },
          conversationTotal: {
            state: "ready",
            value: normalizeCount(response.conversation_count),
          },
          sentMessageTotal: {
            state: "ready",
            value: normalizeCount(response.sent_message_count),
          },
        }));
      })
      .catch((error: unknown) => {
        if (!cancelled && !isAbortError(error)) {
          setSummary((current) => ({
            ...current,
            aiRuntimeTotal: { state: "error" },
            conversationTotal: { state: "error" },
            sentMessageTotal: { state: "error" },
          }));
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [enabled]);

  const setConversationTotal = useCallback((value: number) => {
    setSummary((current) => ({
      ...current,
      conversationTotal: { state: "ready", value: normalizeCount(value) },
    }));
  }, []);

  return { setConversationTotal, summary };
}

function normalizeCount(value: number) {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

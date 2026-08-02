import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  ToolCallRecordSummaryItem,
  ToolCallRecordSummaryResponse,
} from "../../../entities/tool/model/toolCallRecord";
import { getToolsetCallRecordSummary } from "../../../services/tools/toolCallRecords";

type ToolsetCallRecordSummaryState = {
  error: string | null;
  itemsByFolderId: Map<string, ToolCallRecordSummaryItem>;
  reload: () => void;
  summary: ToolCallRecordSummaryResponse | null;
  state: "idle" | "loading" | "ready" | "error";
};

export function useToolsetCallRecordSummary(
  toolsetId: string | null,
  {
    isActive = true,
  }: {
    isActive?: boolean;
  } = {},
): ToolsetCallRecordSummaryState {
  const [summary, setSummary] = useState<ToolCallRecordSummaryResponse | null>(null);
  const [state, setState] = useState<ToolsetCallRecordSummaryState["state"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    if (!toolsetId) {
      setSummary(null);
      setState("idle");
      setError(null);
      return;
    }
    if (!isActive) {
      return;
    }

    const controller = new AbortController();
    setState("loading");
    setError(null);

    getToolsetCallRecordSummary(toolsetId, { signal: controller.signal })
      .then((response) => {
        setSummary(response);
        setState("ready");
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }
        setSummary(null);
        setState("error");
        setError(requestError instanceof Error ? requestError.message : "工具调用统计读取失败。");
      });

    return () => {
      controller.abort();
    };
  }, [isActive, reloadVersion, toolsetId]);

  const itemsByFolderId = useMemo(
    () => new Map((summary?.items ?? []).map((item) => [item.project_id, item])),
    [summary],
  );

  return {
    error,
    itemsByFolderId,
    reload: useCallback(() => setReloadVersion((current) => current + 1), []),
    summary,
    state,
  };
}

import { useCallback, useEffect, useState } from "react";
import { getConversationNavigation } from "../../../services/project/getConversationNavigation";
import type { UserMessageNavigationItem } from "./userMessageNavigation";

type Result = { key: string; items: UserMessageNavigationItem[]; error: string | null };

/** Search saved user text, including turns outside the loaded chat body. */
export function useUserMessageSearch({ projectId, sessionId, resetRevision, items, query }: {
  projectId: string;
  sessionId: string;
  resetRevision: number | null;
  items: UserMessageNavigationItem[];
  query: string;
}) {
  const keyword = query.trim();
  // Assistant streaming/preview changes must not restart a user-text search.
  const key = JSON.stringify([projectId, sessionId, resetRevision, items.map(item => item.userMessageId), keyword]);
  const [result, setResult] = useState<Result | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const retry = useCallback(() => setRetryVersion(value => value + 1), []);
  useEffect(() => {
    if (!keyword) return;
    const controller = new AbortController();
    setResult(null);
    const timer = setTimeout(() => {
      void getConversationNavigation(projectId, sessionId, controller.signal, keyword).then(response => {
        if (controller.signal.aborted) return;
        setResult({ key, error: null, items: response.items.map(item => ({
          userMessageId: item.user_message_id, turnNumber: item.turn_number,
          userPreview: item.user_preview || "（附件消息）", assistantPreview: item.assistant_preview,
          assistantMessageId: item.assistant_message_id ?? undefined,
        })) });
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) setResult({ key, items: [],
          error: `搜索失败：${error instanceof Error ? error.message : String(error)}` });
      });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [key, keyword, projectId, sessionId, retryVersion]);
  return {
    items: !keyword ? items : result?.key === key ? result.items : [],
    isLoading: Boolean(keyword && result?.key !== key),
    error: keyword && result?.key === key ? result.error : null,
    retry,
  };
}

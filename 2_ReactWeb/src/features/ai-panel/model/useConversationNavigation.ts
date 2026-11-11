import { useCallback, useEffect, useMemo, useState } from "react";
import { getConversationNavigation } from "../../../services/project/getConversationNavigation";
import type { ChatMessage } from "./chatMessage";
import { buildUserMessageNavigationItems, mergeUserMessageNavigationItems, type UserMessageNavigationItem } from "./userMessageNavigation";

type NavigationSnapshot = { key: string; reset: number; items: UserMessageNavigationItem[] };

export function useConversationNavigation({ projectId, sessionId, revision, resetRevision, running, messages }: {
  projectId: string | null;
  sessionId: string | null;
  revision: number | null;
  resetRevision: number | null;
  running: boolean;
  messages: ChatMessage[];
}) {
  const key = JSON.stringify([projectId, sessionId]);
  const [snapshot, setSnapshot] = useState<NavigationSnapshot | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const retry = useCallback(() => setRetryVersion((value) => value + 1), []);
  // Streaming deltas update the loaded body, not the complete directory.
  // Refresh saved previews at completion and on persisted idle changes.
  const settledRevision = running ? null : revision;
  useEffect(() => {
    if (!projectId || !sessionId) return;
    const controller = new AbortController();
    setFailure(null);
    void getConversationNavigation(projectId, sessionId, controller.signal).then((response) => {
      if (controller.signal.aborted) return;
      setSnapshot({ key, reset: response.reset_revision, items: response.items.map((item) => ({
        userMessageId: item.user_message_id, turnNumber: item.turn_number,
        userPreview: item.user_preview || "（附件消息）", assistantPreview: item.assistant_preview,
        assistantMessageId: item.assistant_message_id ?? undefined,
      })) });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setFailure({ key,
        message: `消息目录加载失败：${error instanceof Error ? error.message : String(error)}` });
    });
    return () => controller.abort();
  }, [projectId, sessionId, key, settledRevision, resetRevision, retryVersion]);
  const items = useMemo(() => {
    if (snapshot?.key !== key) return [];
    // A history replacement must not merge removed messages back into its index.
    if (resetRevision !== null && resetRevision !== snapshot.reset) return snapshot.items;
    return mergeUserMessageNavigationItems(snapshot.items, buildUserMessageNavigationItems(messages));
  }, [key, messages, resetRevision, snapshot]);
  const error = failure?.key === key ? failure.message : null;
  return { items, error, retry, isLoading: Boolean(projectId && sessionId && snapshot?.key !== key && !error) };
}

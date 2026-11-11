import { useCallback, useEffect, useState } from "react";
import { getProjectConversationMessage } from "../../../services/project/getProjectConversationMessage";
import { mapConversationMessages, type ChatMessage } from "./chatMessage";

export function useUserMessageDetail({ projectId, sessionId, messageId, resetRevision, messages }: {
  projectId: string;
  sessionId: string;
  messageId: string | null;
  resetRevision: number | null;
  messages: ChatMessage[];
}) {
  const local = messages.find((message) => message.id === messageId && message.role === "user");
  const key = JSON.stringify([projectId, sessionId, messageId, resetRevision]);
  const [result, setResult] = useState<{ key: string; message: ChatMessage | null; error: string | null } | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const retry = useCallback(() => setRetryVersion((value) => value + 1), []);
  useEffect(() => {
    if (!messageId || local) return;
    const controller = new AbortController();
    setResult(null);
    void getProjectConversationMessage(projectId, sessionId, messageId, controller.signal).then((response) => {
      if (controller.signal.aborted) return;
      if (response.message_id !== messageId || response.session_id !== sessionId || response.role !== "user") {
        throw new Error("消息与当前选择不一致，请重试。");
      }
      setResult({ key, message: mapConversationMessages([response])[0], error: null });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setResult({ key, message: null,
        error: error instanceof Error ? error.message : String(error) });
    });
    return () => controller.abort();
  }, [key, projectId, sessionId, messageId, local, retryVersion]);
  return {
    message: local ?? (result?.key === key ? result.message : null),
    error: local ? null : result?.key === key ? result.error : null,
    retry,
  };
}

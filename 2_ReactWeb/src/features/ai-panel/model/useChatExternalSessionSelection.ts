import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import type {
  ChatPanelSessionSelectionRequest,
  ChatPanelSessionSelectionResult,
} from "./chatSessionSelectionRequest";
import type { ConversationSessionsReloadResult } from "./useConversationSessions";

type ChatExternalSessionSelectionOptions = {
  activateSession: (sessionId: string) => void;
  activeSessionId: string | null;
  handledRequestIdRef: MutableRefObject<number | null>;
  onResult?: (result: ChatPanelSessionSelectionResult) => void;
  onNavigateToMessage?: (sessionId: string, messageId: string) => void;
  projectId: string | null;
  request?: ChatPanelSessionSelectionRequest | null;
  reloadSessions: (projectId: string) => Promise<ConversationSessionsReloadResult>;
  sessions: ConversationSession[];
  showChatView: () => void;
};

export function useChatExternalSessionSelection({
  activateSession,
  activeSessionId,
  handledRequestIdRef,
  onResult,
  onNavigateToMessage,
  projectId,
  request,
  reloadSessions,
  sessions,
  showChatView,
}: ChatExternalSessionSelectionOptions) {
  const reloadedRequestIdRef = useRef<number | null>(null);
  const latestRequestRef = useRef(request);
  latestRequestRef.current = request;

  useEffect(() => {
    if (!request || handledRequestIdRef.current === request.requestId) {
      return;
    }
    if (!projectId || request.projectId !== projectId) {
      return;
    }
    if (!sessions.some((session) => session.session_id === request.sessionId)) {
      if (reloadedRequestIdRef.current !== request.requestId) {
        reloadedRequestIdRef.current = request.requestId;
        void reloadSessions(projectId).then((result) => {
          const latestRequest = latestRequestRef.current;
          if (!latestRequest || latestRequest.requestId !== request.requestId) return;
          if (result.status === "ignored") {
            reloadedRequestIdRef.current = null;
            return;
          }
          if (result.status === "failed") {
            handledRequestIdRef.current = request.requestId;
            onResult?.({
              activeSessionId: result.activeSessionId,
              message: result.message,
              projectId,
              requestId: request.requestId,
              sessionId: request.sessionId,
              status: "failed",
            });
            return;
          }
          if (!result.sessionIds.has(request.sessionId)) {
            handledRequestIdRef.current = request.requestId;
            onResult?.({
              activeSessionId: result.activeSessionId,
              projectId,
              requestId: request.requestId,
              sessionId: request.sessionId,
              status: "missing",
            });
          }
        });
      }
      return;
    }

    reloadedRequestIdRef.current = null;
    handledRequestIdRef.current = request.requestId;
    if (request.messageId) {
      onNavigateToMessage?.(request.sessionId, request.messageId);
    }
    if (activeSessionId === request.sessionId) {
      showChatView();
      return;
    }
    activateSession(request.sessionId);
  }, [
    activateSession,
    activeSessionId,
    handledRequestIdRef,
    onResult,
    onNavigateToMessage,
    projectId,
    request,
    reloadSessions,
    sessions,
    showChatView,
  ]);
}

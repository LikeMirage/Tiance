import { useCallback, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type {
  ConversationSession,
  ConversationSessionState,
} from "../../../entities/llm-chat/model/conversation";
import type { ChatMessage } from "./chatMessage";
import { createDefaultConversation } from "./createDefaultConversation";
import { emptyConversationDraftReferences } from "./conversationDraftReferences";

type UseChatConversationCreatorOptions = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionIdRef: MutableRefObject<string | null>;
  isNotFoundRequestError: (error: unknown) => boolean;
  markConversationProjectUnavailable: (projectId: string) => void;
  projectId: string | null;
  replaceSessionMessages: (projectId: string, sessionId: string, messages: ChatMessage[]) => void;
  saveConversationState: (
    projectId: string,
    input: { active_session_id?: string | null },
  ) => Promise<void>;
  setActiveSessionId: Dispatch<SetStateAction<string | null>>;
  setDraft: Dispatch<SetStateAction<string>>;
  setSessionStates: Dispatch<SetStateAction<Record<string, ConversationSessionState>>>;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
  showChatView: () => void;
};

export function useChatConversationCreator({
  activeProjectIdRef,
  activeSessionIdRef,
  isNotFoundRequestError,
  markConversationProjectUnavailable,
  projectId,
  replaceSessionMessages,
  saveConversationState,
  setActiveSessionId,
  setDraft,
  setSessionStates,
  setSessions,
  showChatView,
}: UseChatConversationCreatorOptions) {
  const [createConversationError, setCreateConversationError] = useState<string | null>(null);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const createConversationRequestIdRef = useRef(0);
  const isCreatingConversationRef = useRef(false);

  const createNewConversation = useCallback(() => {
    if (!projectId || isCreatingConversationRef.current) return;
    const requestId = createConversationRequestIdRef.current + 1;
    createConversationRequestIdRef.current = requestId;
    isCreatingConversationRef.current = true;
    setIsCreatingConversation(true);
    setCreateConversationError(null);
    void createDefaultConversation(projectId).then((session) => {
      if (activeProjectIdRef.current !== projectId || createConversationRequestIdRef.current !== requestId) return;
      setSessions((prev) => [session, ...prev.filter((item) => item.session_id !== session.session_id)]);
      setSessionStates((prev) => ({
        ...prev,
        [session.session_id]: prev[session.session_id] ?? {
          runtime_status: "idle",
          draft: "",
          references: emptyConversationDraftReferences(),
          updated_at: new Date().toISOString(),
        },
      }));
      setActiveSessionId(session.session_id);
      activeSessionIdRef.current = session.session_id;
      replaceSessionMessages(projectId, session.session_id, []);
      setDraft("");
      showChatView();
      void saveConversationState(projectId, { active_session_id: session.session_id })
        .catch((saveError: unknown) => {
          if (activeProjectIdRef.current !== projectId || createConversationRequestIdRef.current !== requestId) return;
          setCreateConversationError(formatCreateConversationError("新建会话已完成，但激活状态保存失败", saveError));
        });
    }).catch((createError: unknown) => {
      if (activeProjectIdRef.current !== projectId || createConversationRequestIdRef.current !== requestId) return;
      if (isNotFoundRequestError(createError)) {
        markConversationProjectUnavailable(projectId);
        setCreateConversationError("项目不存在，无法新建会话。");
        return;
      }
      setCreateConversationError(formatCreateConversationError("新建会话失败", createError));
    }).finally(() => {
      if (createConversationRequestIdRef.current === requestId) {
        isCreatingConversationRef.current = false;
        setIsCreatingConversation(false);
      }
    });
  }, [
    activeProjectIdRef,
    activeSessionIdRef,
    isNotFoundRequestError,
    markConversationProjectUnavailable,
    projectId,
    replaceSessionMessages,
    saveConversationState,
    setActiveSessionId,
    setDraft,
    setSessionStates,
    setSessions,
    showChatView,
  ]);

  return {
    createConversationError,
    createNewConversation,
    isCreatingConversation,
  };
}

function formatCreateConversationError(prefix: string, error: unknown) {
  const message = error instanceof Error ? error.message : "未知错误";
  return `${prefix}：${message}`;
}

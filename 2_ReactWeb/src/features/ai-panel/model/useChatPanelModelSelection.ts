import { useCallback, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import type { ChatModelOption } from "./chatModelOption";
import { resolveSessionSettings } from "./sessionSettings";
import { shouldAutoEnableToolThinkingReturn } from "./toolThinkingReturn";

type UseChatPanelModelSelectionOptions = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionId: string | null;
  projectId: string | null;
  reloadSessions: (projectId: string) => Promise<void>;
  setIsModelMenuOpen: Dispatch<SetStateAction<boolean>>;
  setSelectedModel: (model: ChatModelOption) => void;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
};

export function useChatPanelModelSelection({
  activeProjectIdRef,
  activeSessionId,
  projectId,
  reloadSessions,
  setIsModelMenuOpen,
  setSelectedModel,
  setSessions,
}: UseChatPanelModelSelectionOptions) {
  const modelSelectionRequestSeqRef = useRef(0);

  return useCallback((model: ChatModelOption) => {
    const requestSeq = ++modelSelectionRequestSeqRef.current;
    setSelectedModel(model);
    setIsModelMenuOpen(false);
    if (!projectId || !activeSessionId) return;

    const returnToolThinking = shouldAutoEnableToolThinkingReturn(model);
    const patchSession = (session: ConversationSession): ConversationSession => ({
      ...session,
      provider_id: model.providerId,
      model_id: model.modelId,
      role_status: "custom",
      settings: {
        ...resolveSessionSettings(session),
        return_thinking_content: returnToolThinking,
      },
      updated_at: new Date().toISOString(),
    });
    setSessions((prev) => prev.map((session) =>
      session.session_id === activeSessionId ? patchSession(session) : session,
    ));

    void updateProjectConversation(projectId, activeSessionId, {
      provider_id: model.providerId,
      model_id: model.modelId,
      settings: {
        return_thinking_content: returnToolThinking,
      },
    }).then((updatedSession) => {
      if (modelSelectionRequestSeqRef.current !== requestSeq) return;
      if (activeProjectIdRef.current !== projectId) return;
      setSessions((prev) => prev.map((session) =>
        session.session_id === updatedSession.session_id
          ? { ...updatedSession, reasoning_mode: session.reasoning_mode }
          : session,
      ));
    }).catch(() => {
      if (modelSelectionRequestSeqRef.current !== requestSeq) return;
      if (activeProjectIdRef.current !== projectId) return;
      void reloadSessions(projectId);
    });
  }, [
    activeProjectIdRef,
    activeSessionId,
    projectId,
    reloadSessions,
    setIsModelMenuOpen,
    setSelectedModel,
    setSessions,
  ]);
}

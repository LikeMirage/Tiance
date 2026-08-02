import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { useI18n } from "../../../shared/i18n";
import { setProjectConversationPinned } from "../../../services/project/setProjectConversationPinned";

type UseConversationSessionPinningOptions = {
  activeProjectIdRef: RefObject<string | null>;
  projectId: string | null;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
};

export function useConversationSessionPinning({
  activeProjectIdRef,
  projectId,
  setSessions,
}: UseConversationSessionPinningOptions) {
  const { t } = useI18n();
  const requestIdRef = useRef(0);
  const pendingSessionIdRef = useRef<string | null>(null);
  const [pinningSessionId, setPinningSessionId] = useState<string | null>(null);
  const [pinErrorMessage, setPinErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    requestIdRef.current += 1;
    pendingSessionIdRef.current = null;
    setPinningSessionId(null);
    setPinErrorMessage(null);
  }, [projectId]);

  const toggleSessionPinned = useCallback(async (session: ConversationSession) => {
    if (!projectId || pendingSessionIdRef.current) return;
    const requestedProjectId = projectId;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    pendingSessionIdRef.current = session.session_id;
    setPinningSessionId(session.session_id);
    setPinErrorMessage(null);
    try {
      const updatedSession = await setProjectConversationPinned(
        requestedProjectId,
        session.session_id,
        !session.pinned,
      );
      if (
        requestIdRef.current !== requestId ||
        activeProjectIdRef.current !== requestedProjectId
      ) {
        return;
      }
      setSessions((current) => current.map((item) =>
        item.session_id === updatedSession.session_id ? updatedSession : item
      ));
      dispatchProjectConversationUpdated({
        kind: "structure",
        projectId: requestedProjectId,
        sessionId: updatedSession.session_id,
      });
    } catch (error) {
      if (requestIdRef.current !== requestId) return;
      setPinErrorMessage(
        error instanceof Error ? error.message : t("aiPanel.history.pinFailed"),
      );
    } finally {
      if (requestIdRef.current === requestId) {
        pendingSessionIdRef.current = null;
        setPinningSessionId(null);
      }
    }
  }, [activeProjectIdRef, projectId, setSessions, t]);

  return {
    pinErrorMessage,
    pinningSessionId,
    toggleSessionPinned,
  };
}

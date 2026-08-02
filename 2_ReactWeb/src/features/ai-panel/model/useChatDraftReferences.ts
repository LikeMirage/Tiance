import { useEffect, useMemo, useRef } from "react";
import type { MutableRefObject } from "react";

import type { ConversationMessageReferences } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ConversationDraftReferences,
  ConversationSessionState,
} from "../../../entities/llm-chat/model/conversation";
import {
  areConversationDraftReferencesEqual,
  fromConversationDraftReferences,
  toConversationDraftReferences,
} from "./conversationDraftReferences";

type UseChatDraftReferencesInput = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionId: string | null;
  activeSessionIdRef: MutableRefObject<string | null>;
  activeSessionState: ConversationSessionState | null;
  onDraftReferencesChange?: (references: ConversationMessageReferences) => void;
  projectId: string | null;
  references: ConversationMessageReferences;
  saveSessionReferences: (
    projectId: string,
    sessionId: string,
    references: ConversationDraftReferences,
  ) => void;
};

export function useChatDraftReferences({
  activeProjectIdRef,
  activeSessionId,
  activeSessionIdRef,
  activeSessionState,
  onDraftReferencesChange,
  projectId,
  references,
  saveSessionReferences,
}: UseChatDraftReferencesInput) {
  const latestReferencesRef = useRef(references);
  const lastRestoredReferenceKeyRef = useRef<string | null>(null);
  const restoredReferenceKeyRef = useRef<string | null>(null);
  const activeSessionReferenceKey = projectId && activeSessionId
    ? `${projectId}:${activeSessionId}`
    : null;
  const currentDraftReferences = useMemo(
    () => toConversationDraftReferences(references),
    [references],
  );

  useEffect(() => {
    latestReferencesRef.current = references;
  }, [references]);

  useEffect(() => {
    if (!activeSessionReferenceKey || !onDraftReferencesChange) {
      lastRestoredReferenceKeyRef.current = null;
      return;
    }
    if (lastRestoredReferenceKeyRef.current === activeSessionReferenceKey) return;
    lastRestoredReferenceKeyRef.current = activeSessionReferenceKey;
    restoredReferenceKeyRef.current = activeSessionReferenceKey;
    onDraftReferencesChange(fromConversationDraftReferences(activeSessionState?.references));
  }, [activeSessionReferenceKey, activeSessionState?.references, onDraftReferencesChange]);

  useEffect(() => {
    if (!projectId || !activeSessionId || !activeSessionReferenceKey) return;
    const isSynced = areConversationDraftReferencesEqual(
      activeSessionState?.references,
      currentDraftReferences,
    );
    if (restoredReferenceKeyRef.current === activeSessionReferenceKey) {
      if (isSynced) restoredReferenceKeyRef.current = null;
      return;
    }
    if (isSynced) return;
    const timer = window.setTimeout(() => {
      if (
        activeProjectIdRef.current !== projectId ||
        activeSessionIdRef.current !== activeSessionId
      ) {
        return;
      }
      saveSessionReferences(projectId, activeSessionId, currentDraftReferences);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    activeSessionReferenceKey,
    activeSessionState?.references,
    currentDraftReferences,
    projectId,
    saveSessionReferences,
  ]);

  useEffect(() => {
    if (!projectId || !activeSessionId) return;
    const sessionReferenceKey = `${projectId}:${activeSessionId}`;
    return () => {
      if (restoredReferenceKeyRef.current === sessionReferenceKey) return;
      saveSessionReferences(
        projectId,
        activeSessionId,
        toConversationDraftReferences(latestReferencesRef.current),
      );
    };
  }, [activeSessionId, projectId, saveSessionReferences]);
}

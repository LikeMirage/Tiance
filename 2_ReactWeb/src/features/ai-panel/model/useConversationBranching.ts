import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  ConversationForkResponse,
  ConversationMessageVariant,
  ConversationSession,
} from "../../../entities/llm-chat/model/conversation";
import { isAbortError } from "../../../services/http/httpErrors";
import { forkProjectConversation } from "../../../services/project/forkProjectConversation";
import type { ChatMessage } from "./chatMessage";
import { buildConversationForkDraft } from "./conversationForkDraft";
import {
  resolveMessageVariantNavigation,
  type MessageVariantTarget,
} from "./conversationMessageVariants";

type UseConversationBranchingOptions = {
  activeSessionId: string | null;
  applyForkResult: (response: ConversationForkResponse) => void;
  isActiveSessionBusy: boolean;
  messageVariants: ConversationMessageVariant[];
  onActivateSession: (sessionId: string) => void;
  onDraftReferencesChange?: (references: ConversationForkResponse["state"]["references"]) => void;
  onNavigateToVariant: (target: MessageVariantTarget) => void;
  projectId: string | null;
  reloadSessionMessages: (
    projectId: string,
    sessionId: string,
    options?: { forceRefresh?: boolean; preserveLocalIfShorter?: boolean },
  ) => Promise<unknown>;
  sessions: ConversationSession[];
};

export function useConversationBranching({
  activeSessionId,
  applyForkResult,
  isActiveSessionBusy,
  messageVariants,
  onActivateSession,
  onDraftReferencesChange,
  onNavigateToVariant,
  projectId,
  reloadSessionMessages,
  sessions,
}: UseConversationBranchingOptions) {
  const [forkingMessageId, setForkingMessageId] = useState<string | null>(null);
  const [branchError, setBranchError] = useState<string | null>(null);
  const operationIdRef = useRef(0);

  useEffect(() => {
    operationIdRef.current += 1;
    setForkingMessageId(null);
    setBranchError(null);
  }, [activeSessionId, projectId]);

  const forkUserMessage = useCallback(async (message: ChatMessage) => {
    if (
      !projectId ||
      !activeSessionId ||
      isActiveSessionBusy ||
      forkingMessageId ||
      message.role !== "user" ||
      message.status !== "done"
    ) {
      return;
    }
    const forkDraft = buildConversationForkDraft(message);
    const operationId = operationIdRef.current + 1;
    operationIdRef.current = operationId;
    setForkingMessageId(message.id);
    setBranchError(null);
    try {
      const response = await forkProjectConversation(projectId, activeSessionId, {
        source_message_id: message.id,
        draft: forkDraft.draft,
        references: forkDraft.references,
      });
      applyForkResult(response);
      onDraftReferencesChange?.(forkDraft.references);
      await reloadSessionMessages(projectId, response.session.session_id, {
        forceRefresh: true,
      });
    } catch (error) {
      if (operationIdRef.current === operationId && !isAbortError(error)) {
        setBranchError(error instanceof Error ? error.message : "创建会话分支失败。");
      }
    } finally {
      if (operationIdRef.current === operationId) {
        setForkingMessageId(null);
      }
    }
  }, [
    activeSessionId,
    applyForkResult,
    forkingMessageId,
    isActiveSessionBusy,
    onDraftReferencesChange,
    projectId,
    reloadSessionMessages,
  ]);

  const selectVariant = useCallback((target: MessageVariantTarget) => {
    if (!target.messageId || target.sessionId === activeSessionId) return;
    onNavigateToVariant(target);
    onActivateSession(target.sessionId);
  }, [activeSessionId, onActivateSession, onNavigateToVariant]);

  const getVariantNavigation = useCallback((message: ChatMessage) => {
    const navigation = resolveMessageVariantNavigation(
      message,
      messageVariants,
      sessions,
      activeSessionId,
    );
    if (!navigation) return null;
    return {
      count: navigation.count,
      currentPosition: navigation.currentPosition,
      onNext: () => selectVariant(navigation.next),
      onPrevious: () => selectVariant(navigation.previous),
    };
  }, [activeSessionId, messageVariants, selectVariant, sessions]);

  return useMemo(() => ({
    branchError,
    forkingMessageId,
    forkUserMessage,
    getVariantNavigation,
  }), [branchError, forkingMessageId, forkUserMessage, getVariantNavigation]);
}

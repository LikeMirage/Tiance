import { useCallback, useRef } from "react";
import type { MutableRefObject } from "react";

import {
  ConversationDraftProtectionStore,
  type ConversationDraftRequestSnapshot,
} from "./conversationDraftProtectionStore";
import type { ConversationSessionState } from "../../../entities/llm-chat/model/conversation";
import {
  saveProjectConversationState,
  type SaveProjectConversationStateInput,
} from "../../../services/project/saveProjectConversationState";

export type { ConversationDraftRequestSnapshot } from "./conversationDraftProtectionStore";

export type ConversationSessionStatePatch = Partial<Pick<
  ConversationSessionState,
  "draft" | "references" | "runtime_status"
>>;

type UseConversationStatePersistenceInput = {
  unavailableProjectIdRef: MutableRefObject<string | null>;
};

export function useConversationStatePersistence({
  unavailableProjectIdRef,
}: UseConversationStatePersistenceInput) {
  const saveQueuesRef = useRef(new Map<string, Promise<void>>());
  const draftProtectionStoreRef = useRef<ConversationDraftProtectionStore | null>(null);
  if (draftProtectionStoreRef.current === null) {
    draftProtectionStoreRef.current = new ConversationDraftProtectionStore();
  }
  const draftProtectionStore = draftProtectionStoreRef.current;

  const saveConversationState = useCallback((
    projectId: string,
    input: SaveProjectConversationStateInput,
  ) => {
    const previous = saveQueuesRef.current.get(projectId) ?? Promise.resolve();
    const request = previous.catch(() => undefined).then(async () => {
      if (unavailableProjectIdRef.current === projectId) return;
      // 这里的 404 也可能只是会话已失效；项目存在性由会话列表读取统一确认。
      await saveProjectConversationState(projectId, input);
    });
    saveQueuesRef.current.set(projectId, request);
    void request.finally(() => {
      if (saveQueuesRef.current.get(projectId) === request) {
        saveQueuesRef.current.delete(projectId);
      }
    }).catch(() => undefined);
    return request;
  }, [unavailableProjectIdRef]);

  const rememberPendingDraft = useCallback((
    projectId: string,
    sessionId: string,
    draft: string,
  ) => {
    draftProtectionStore.rememberPendingDraft(projectId, sessionId, draft);
  }, [draftProtectionStore]);

  const clearPendingDraft = useCallback((
    projectId: string,
    sessionId: string,
    savedDraft?: string,
  ) => {
    draftProtectionStore.clearPendingDraft(projectId, sessionId, savedDraft);
  }, [draftProtectionStore]);

  const forgetDraft = useCallback((projectId: string, sessionId: string) => {
    draftProtectionStore.forgetDraft(projectId, sessionId);
  }, [draftProtectionStore]);

  const clearProjectDrafts = useCallback((projectId: string) => {
    draftProtectionStore.clearProject(projectId);
  }, [draftProtectionStore]);

  const snapshotDraftRequest = useCallback((projectId: string) => (
    draftProtectionStore.snapshotRequest(projectId)
  ), [draftProtectionStore]);

  const releaseDraftRequest = useCallback((
    projectId: string,
    snapshot: ConversationDraftRequestSnapshot,
  ) => {
    draftProtectionStore.releaseRequest(projectId, snapshot);
  }, [draftProtectionStore]);

  const mergeProtectedDrafts = useCallback((
    projectId: string,
    states: Record<string, ConversationSessionState>,
    requestSnapshot?: ConversationDraftRequestSnapshot,
  ) => draftProtectionStore.mergeProtectedDrafts(
    projectId,
    states,
    requestSnapshot,
  ), [draftProtectionStore]);

  const persistSessionState = useCallback((
    projectId: string,
    sessionId: string,
    patch: ConversationSessionStatePatch,
  ) => {
    const savedDraft = patch.draft;
    if (savedDraft !== undefined) rememberPendingDraft(projectId, sessionId, savedDraft);
    const input: SaveProjectConversationStateInput = {};
    if (patch.runtime_status !== undefined) {
      input.session_runtime_statuses = { [sessionId]: patch.runtime_status };
    }
    if (patch.draft !== undefined) {
      input.session_drafts = { [sessionId]: patch.draft };
    }
    if (patch.references !== undefined) {
      input.session_references = { [sessionId]: patch.references };
    }
    void saveConversationState(projectId, {
      ...input,
    }).then(() => {
      if (savedDraft !== undefined) clearPendingDraft(projectId, sessionId, savedDraft);
    }).catch(() => undefined);
  }, [clearPendingDraft, rememberPendingDraft, saveConversationState]);

  return {
    clearProjectDrafts,
    forgetDraft,
    mergeProtectedDrafts,
    persistSessionState,
    releaseDraftRequest,
    rememberPendingDraft,
    saveConversationState,
    snapshotDraftRequest,
  };
}

import type { ConversationSessionState } from "../../../entities/llm-chat/model/conversation";

export type ConversationDraftRequestSnapshot = {
  pendingSessionIds: ReadonlySet<string>;
  requestId: number;
  revisions: ReadonlyMap<string, number>;
};

export class ConversationDraftProtectionStore {
  private readonly activeRequestIds = new Map<string, Set<number>>();
  private readonly localDrafts = new Map<string, Map<string, string>>();
  private readonly pendingDrafts = new Map<string, Map<string, string>>();
  private readonly revisions = new Map<string, Map<string, number>>();
  private requestSerial = 0;

  rememberPendingDraft(projectId: string, sessionId: string, draft: string) {
    const projectDrafts = this.pendingDrafts.get(projectId) ?? new Map<string, string>();
    projectDrafts.set(sessionId, draft);
    this.pendingDrafts.set(projectId, projectDrafts);

    const localProjectDrafts = this.localDrafts.get(projectId) ?? new Map<string, string>();
    if (localProjectDrafts.get(sessionId) !== draft) {
      const projectRevisions = this.revisions.get(projectId) ?? new Map<string, number>();
      projectRevisions.set(sessionId, (projectRevisions.get(sessionId) ?? 0) + 1);
      this.revisions.set(projectId, projectRevisions);
    }
    localProjectDrafts.set(sessionId, draft);
    this.localDrafts.set(projectId, localProjectDrafts);
  }

  clearPendingDraft(projectId: string, sessionId: string, savedDraft?: string) {
    const projectDrafts = this.pendingDrafts.get(projectId);
    if (!projectDrafts) return;
    if (savedDraft !== undefined && projectDrafts.get(sessionId) !== savedDraft) return;
    projectDrafts.delete(sessionId);
    if (projectDrafts.size === 0) this.pendingDrafts.delete(projectId);
    this.clearSettledProjectDrafts(projectId);
  }

  forgetDraft(projectId: string, sessionId: string) {
    this.clearPendingDraft(projectId, sessionId);
    this.deleteSessionEntry(this.localDrafts, projectId, sessionId);
    this.deleteSessionEntry(this.revisions, projectId, sessionId);
  }

  clearProject(projectId: string) {
    this.activeRequestIds.delete(projectId);
    this.pendingDrafts.delete(projectId);
    this.localDrafts.delete(projectId);
    this.revisions.delete(projectId);
  }

  snapshotRequest(projectId: string): ConversationDraftRequestSnapshot {
    this.requestSerial += 1;
    const requestId = this.requestSerial;
    const projectRequestIds = this.activeRequestIds.get(projectId) ?? new Set<number>();
    projectRequestIds.add(requestId);
    this.activeRequestIds.set(projectId, projectRequestIds);
    return {
      pendingSessionIds: new Set(this.pendingDrafts.get(projectId)?.keys() ?? []),
      requestId,
      revisions: new Map(this.revisions.get(projectId) ?? []),
    };
  }

  releaseRequest(projectId: string, snapshot: ConversationDraftRequestSnapshot) {
    const projectRequestIds = this.activeRequestIds.get(projectId);
    projectRequestIds?.delete(snapshot.requestId);
    if (projectRequestIds?.size === 0) this.activeRequestIds.delete(projectId);
    this.clearSettledProjectDrafts(projectId);
  }

  mergeProtectedDrafts(
    projectId: string,
    states: Record<string, ConversationSessionState>,
    requestSnapshot?: ConversationDraftRequestSnapshot,
  ) {
    const sessionIdsToPreserve = new Set(requestSnapshot?.pendingSessionIds ?? []);
    this.pendingDrafts.get(projectId)?.forEach((_draft, sessionId) => {
      sessionIdsToPreserve.add(sessionId);
    });
    if (requestSnapshot) {
      this.revisions.get(projectId)?.forEach((revision, sessionId) => {
        if (requestSnapshot.revisions.get(sessionId) !== revision) {
          sessionIdsToPreserve.add(sessionId);
        }
      });
    }
    if (!sessionIdsToPreserve.size) return states;
    const localProjectDrafts = this.localDrafts.get(projectId);
    const merged = { ...states };
    sessionIdsToPreserve.forEach((sessionId) => {
      const state = merged[sessionId];
      const localDraft = localProjectDrafts?.get(sessionId);
      if (!state || localDraft === undefined) return;
      merged[sessionId] = { ...state, draft: localDraft };
    });
    return merged;
  }

  private clearSettledProjectDrafts(projectId: string) {
    if ((this.activeRequestIds.get(projectId)?.size ?? 0) > 0) return;
    const pendingSessionIds = new Set(this.pendingDrafts.get(projectId)?.keys() ?? []);
    this.deleteSettledEntries(this.localDrafts, projectId, pendingSessionIds);
    this.deleteSettledEntries(this.revisions, projectId, pendingSessionIds);
  }

  private deleteSessionEntry<T>(
    store: Map<string, Map<string, T>>,
    projectId: string,
    sessionId: string,
  ) {
    const projectEntries = store.get(projectId);
    projectEntries?.delete(sessionId);
    if (projectEntries?.size === 0) store.delete(projectId);
  }

  private deleteSettledEntries<T>(
    store: Map<string, Map<string, T>>,
    projectId: string,
    pendingSessionIds: ReadonlySet<string>,
  ) {
    const projectEntries = store.get(projectId);
    if (!projectEntries) return;
    for (const sessionId of projectEntries.keys()) {
      if (!pendingSessionIds.has(sessionId)) projectEntries.delete(sessionId);
    }
    if (projectEntries.size === 0) store.delete(projectId);
  }
}

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { CONVERSATION_MESSAGE_PAGE_SIZE, getProjectConversationMessages } from "../../../services/project/getProjectConversationMessages";
import { getCachedProjectEntryWarmup } from "../../project-entry/model/projectEntryWarmup";
import type { ChatMessage } from "./chatMessage";
import { mapConversationMessages } from "./chatMessage";
import { buildSessionKey } from "./sessionKey";
import { mergeLiveChatNotifications, reuseChatMessageRevisions } from "./chatNotifications";

import { getConversationMessageState } from "../../../services/project/watchConversationChanges";
import type { ConversationMessageListResponse } from "../../../entities/llm-chat/model/conversation";

type HistoryPage = { before: string | null; after: string | null; revision: number; reset: number; reconcile: boolean };

type ReloadSessionMessagesOptions = {
  older?: boolean;
  forceRefresh?: boolean;
  preserveLocalIfShorter?: boolean;
  signal?: AbortSignal;
  shouldApply?: () => boolean;
  shouldPreserveLocal?: () => boolean;
  /** Reconnect/reset reads replace transient fragments using a durable checkpoint. */
  authoritative?: boolean;
};

type UseSessionMessagesOptions = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionIdRef: MutableRefObject<string | null>;
  isPresentationVisibleRef: MutableRefObject<boolean>;
};

type PruneSessionMessagesOptions = {
  activeProjectId: string | null;
  activeSessionId: string | null;
  retainedSessionKeys?: ReadonlySet<string>;
  streamingSessionKeys: Set<string>;
};

const maxRetainedInactiveSessionMessageCaches = 2;
const maxRetainedInactiveSessionMessageChars = 2_000_000;
const sessionMessagesRequestTimeoutMs = 12_000;

export function useSessionMessages({
  activeProjectIdRef,
  activeSessionIdRef,
  isPresentationVisibleRef,
}: UseSessionMessagesOptions) {
  const [sessionMessages, setSessionMessages] = useState<Record<string, ChatMessage[]>>({});
  const [loadingSessionKeys, setLoadingSessionKeys] = useState<Set<string>>(() => new Set());
  const sessionMessageSnapshotsRef = useRef<Record<string, ChatMessage[]>>({});
  const messageAccessedAtRef = useRef(new Map<string, number>());
  const historyPagesRef = useRef(new Map<string, HistoryPage>());
  const [historyPages, setHistoryPages] = useState<Record<string, HistoryPage>>({});
  const [messageLoadErrors, setMessageLoadErrors] = useState<Record<string, string>>({});
  const jobsRef = useRef(new Map<string, { promise: Promise<boolean>; queued: ReloadSessionMessagesOptions | null; older: boolean }>());
  const reloadControllersRef = useRef(new Map<string, AbortController>());

  useEffect(() => () => {
    for (const controller of reloadControllersRef.current.values()) {
      controller.abort();
    }
    reloadControllersRef.current.clear();
    jobsRef.current.clear();
  }, []);

  const isSessionMessagesPresented = useCallback((pid: string, sessionId: string) => (
    isPresentationVisibleRef.current &&
    activeProjectIdRef.current === pid &&
    activeSessionIdRef.current === sessionId
  ), [activeProjectIdRef, activeSessionIdRef, isPresentationVisibleRef]);

  const publishSessionMessages = useCallback((pid: string, sessionId: string) => {
    if (!isSessionMessagesPresented(pid, sessionId)) return false;
    const key = buildSessionKey(pid, sessionId);
    if (!Object.hasOwn(sessionMessageSnapshotsRef.current, key)) return false;
    const messages = sessionMessageSnapshotsRef.current[key];
    setSessionMessages((prev) => (
      prev[key] === messages ? prev : { ...prev, [key]: messages }
    ));
    return true;
  }, [isSessionMessagesPresented]);

  const markSessionMessagesAccessed = useCallback((pid: string, sessionId: string) => {
    messageAccessedAtRef.current.set(buildSessionKey(pid, sessionId), Date.now());
  }, []);

  const updateSessionMessages = useCallback((
    pid: string,
    sessionId: string,
    updater: (messages: ChatMessage[]) => ChatMessage[],
  ) => {
    const key = buildSessionKey(pid, sessionId);
    messageAccessedAtRef.current.set(key, Date.now());
    const currentMessages = sessionMessageSnapshotsRef.current[key] ?? [];
    const nextMessages = updater(currentMessages);
    if (nextMessages === currentMessages) return;
    sessionMessageSnapshotsRef.current[key] = nextMessages;
    if (isSessionMessagesPresented(pid, sessionId)) {
      setSessionMessages((prev) => ({ ...prev, [key]: nextMessages }));
    }
  }, [isSessionMessagesPresented]);

  const replaceSessionMessages = useCallback((
    pid: string,
    sessionId: string,
    messages: ChatMessage[],
  ) => {
    const key = buildSessionKey(pid, sessionId);
    messageAccessedAtRef.current.set(key, Date.now());
    sessionMessageSnapshotsRef.current[key] = messages;
    if (isSessionMessagesPresented(pid, sessionId)) {
      setSessionMessages((prev) => ({ ...prev, [key]: messages }));
    }
  }, [isSessionMessagesPresented]);

  const applyCachedSessionMessages = useCallback((pid: string, sessionId: string) => {
    const cachedResponse = getCachedProjectEntryWarmup(pid)?.sessionMessages[sessionId];
    if (!cachedResponse) return false;

    const key = buildSessionKey(pid, sessionId);
    const nextMessages = mapConversationMessages(
      cachedResponse.items,
      cachedResponse.run_outcomes,
      cachedResponse.run_attempt_failures,
    );
    messageAccessedAtRef.current.set(key, Date.now());
    const currentMessages = sessionMessageSnapshotsRef.current[key] ?? [];
    if (currentMessages.length === 0) {
      const page = pageFromResponse(cachedResponse);
      historyPagesRef.current.set(key, page);
      setHistoryPages((prev) => ({ ...prev, [key]: page }));
      sessionMessageSnapshotsRef.current[key] = nextMessages;
    }
    publishSessionMessages(pid, sessionId);
    return true;
  }, [publishSessionMessages]);

  const reloadSessionMessages = useCallback((
    pid: string, sessionId: string, options: ReloadSessionMessagesOptions = {},
  ): Promise<boolean> => {
    const key = buildSessionKey(pid, sessionId);
    if (options.signal?.aborted) return Promise.resolve(false);
    const existing = jobsRef.current.get(key);
    if (existing) {
      // Coalesce invalidations without aborting a slow read. One trailing read
      // reconciles changes committed while the current snapshot was in flight.
      if (options.older) existing.older = true;
      else existing.queued = { ...existing.queued, ...options, older: false,
        authoritative: existing.queued?.authoritative || options.authoritative };
      return existing.promise;
    }
    const controller = new AbortController();
    reloadControllersRef.current.set(key, controller);
    const job = { promise: Promise.resolve(false), queued: null as ReloadSessionMessagesOptions | null, older: false };
    jobsRef.current.set(key, job);
    setLoadingSessionKeys((prev) => new Set(prev).add(key));
    setMessageLoadErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });

    const read = async (request: ReloadSessionMessagesOptions) => {
      const previousPage = historyPagesRef.current.get(key);
      const current = sessionMessageSnapshotsRef.current[key] ?? [];
      const preservingLive = request.shouldPreserveLocal?.() ?? (!request.authoritative &&
        current.some((message) => message.role === "assistant" && message.status === "running"));
      if (request.older && !previousPage?.before) return;
      const cached = !request.forceRefresh && !previousPage && !request.older
        ? getCachedProjectEntryWarmup(pid)?.sessionMessages[sessionId] : null;
      const state = previousPage && !request.older
        ? await getConversationMessageState(pid, sessionId, controller.signal) : null;
      const reset = state !== null && state.reset_revision !== previousPage?.reset;
      if (state && state.revision === previousPage?.revision && !reset && !request.authoritative &&
          !(previousPage.reconcile && !preservingLive)) return;
      let incremental = Boolean(previousPage?.after && !reset && !request.older && !request.authoritative &&
        !(previousPage?.reconcile && !preservingLive));
      let cursor = incremental ? previousPage!.after : null;
      do {
        let response: ConversationMessageListResponse;
        try {
          response = cached ?? await getProjectConversationMessages(pid, sessionId, {
            limit: CONVERSATION_MESSAGE_PAGE_SIZE,
            beforeMessageId: request.older ? previousPage?.before : null,
            afterMessageId: cursor, signal: controller.signal,
          });
        } catch (error) {
          if (!(cursor || request.older) || !error || typeof error !== "object" ||
              !("status" in error) || ![400, 409].includes(Number(error.status))) throw error;
          response = await getProjectConversationMessages(pid, sessionId, {
            limit: CONVERSATION_MESSAGE_PAGE_SIZE, signal: controller.signal,
          });
          incremental = false;
          request = { ...request, older: false };
        }
        // A history replacement can commit between the state check and page read.
        if (previousPage && response.reset_revision !== previousPage.reset && (incremental || request.older)) {
          response = await getProjectConversationMessages(pid, sessionId, {
            limit: CONVERSATION_MESSAGE_PAGE_SIZE, signal: controller.signal,
          });
          incremental = false;
          request = { ...request, older: false };
        }
        if (incremental && !response.items.length) {
          response = await getProjectConversationMessages(pid, sessionId, {
            limit: CONVERSATION_MESSAGE_PAGE_SIZE, signal: controller.signal,
          });
          incremental = false;
        }
        if (controller.signal.aborted) return;
        const nextMessages = mapConversationMessages(response.items, response.run_outcomes, response.run_attempt_failures);
        const latest = sessionMessageSnapshotsRef.current[key] ?? [];
        const replaced = previousPage && (response.reset_revision ?? 0) !== previousPage.reset;
        const tailReplacement = !incremental && !request.older;
        let merged = mergeHistoryPage(latest, nextMessages, {
          older: Boolean(request.older), replace: Boolean(replaced) || !previousPage,
          tail: tailReplacement,
        });
        const keepLive = request.shouldPreserveLocal?.() ?? (!request.authoritative &&
          latest.some((message) => message.role === "assistant" && message.status === "running"));
        if (keepLive && latest.length && !request.older) merged = mergeLiveChatNotifications(latest, nextMessages);
        sessionMessageSnapshotsRef.current[key] = reuseChatMessageRevisions(latest, merged);
        messageAccessedAtRef.current.set(key, Date.now());
        const page = pageFromResponse(response);
        if (request.older) {
          page.after = previousPage!.after;
          // An older-page read is not an acknowledgement of newer messages.
          page.revision = previousPage!.revision;
          page.reconcile = previousPage!.reconcile;
        } else if (previousPage && !replaced && (incremental || latest.some((m) => m.id === response.items[0]?.message_id))) {
          page.before = previousPage.before;
        }
        if (incremental && response.has_more) page.revision = previousPage?.revision ?? -1;
        page.reconcile ||= Boolean(keepLive);
        historyPagesRef.current.set(key, page);
        setHistoryPages((prev) => ({ ...prev, [key]: page }));
        publishSessionMessages(pid, sessionId);
        const nextCursor = response.next_after_message_id ?? response.items.at(-1)?.message_id ?? cursor;
        if (!incremental || !response.has_more || nextCursor === cursor) break;
        cursor = nextCursor;
      } while (!controller.signal.aborted);
    };

    job.promise = (async () => {
      let request: ReloadSessionMessagesOptions | null = options;
      try {
        while (request && !controller.signal.aborted) {
          const timeout = window.setTimeout(() => controller.abort(), sessionMessagesRequestTimeoutMs);
          try { await read(request); } finally { window.clearTimeout(timeout); }
          request = job.queued;
          job.queued = null;
          if (!request && job.older) {
            request = { older: true, forceRefresh: true };
            job.older = false;
          }
        }
        return !controller.signal.aborted;
      } catch (error) {
        if (jobsRef.current.get(key) === job) {
          setMessageLoadErrors((prev) => ({ ...prev, [key]: controller.signal.aborted
            ? "aiPanel.messageList.loadTimeout" : "aiPanel.messageList.loadFailed" }));
        }
        throw error;
      } finally {
        if (jobsRef.current.get(key) === job) {
          jobsRef.current.delete(key);
          reloadControllersRef.current.delete(key);
          setLoadingSessionKeys((prev) => { const next = new Set(prev); next.delete(key); return next; });
        }
      }
    })();
    return job.promise;
  }, [publishSessionMessages]);

  const loadOlderSessionMessages = useCallback((pid: string, sessionId: string) =>
    reloadSessionMessages(pid, sessionId, { older: true, forceRefresh: true }), [reloadSessionMessages]);

  const pruneSessionMessages = useCallback((options: PruneSessionMessagesOptions) => {
    const snapshots = sessionMessageSnapshotsRef.current;
    const retainedKeys = new Set<string>();
    for (const key of options.streamingSessionKeys) {
      retainedKeys.add(key);
    }
    for (const key of options.retainedSessionKeys ?? []) {
      retainedKeys.add(key);
    }

    if (options.activeProjectId && options.activeSessionId) {
      retainedKeys.add(buildSessionKey(options.activeProjectId, options.activeSessionId));
    }

    const inactiveKeys = Object.keys(snapshots)
      .filter((key) => !retainedKeys.has(key))
      .sort((left, right) =>
        (messageAccessedAtRef.current.get(right) ?? 0) -
        (messageAccessedAtRef.current.get(left) ?? 0)
      );

    let retainedInactiveCaches = 0;
    let retainedInactiveChars = 0;
    for (const key of inactiveKeys) {
      const messages = snapshots[key] ?? [];
      const charCount = countMessagesChars(messages);
      const canRetain =
        retainedInactiveCaches < maxRetainedInactiveSessionMessageCaches &&
        retainedInactiveChars + charCount <= maxRetainedInactiveSessionMessageChars;
      if (!canRetain) continue;

      retainedKeys.add(key);
      retainedInactiveCaches += 1;
      retainedInactiveChars += charCount;
    }

    let snapshotsChanged = false;
    const nextSnapshots: Record<string, ChatMessage[]> = {};
    for (const [key, messages] of Object.entries(snapshots)) {
      if (retainedKeys.has(key)) {
        nextSnapshots[key] = messages;
        continue;
      }
      snapshotsChanged = true;
      messageAccessedAtRef.current.delete(key);
      historyPagesRef.current.delete(key);
      jobsRef.current.delete(key);
      reloadControllersRef.current.get(key)?.abort();
      reloadControllersRef.current.delete(key);
    }
    if (snapshotsChanged) {
      sessionMessageSnapshotsRef.current = nextSnapshots;
    }
    // Navigation may discard an in-flight first page before it has a snapshot.
    for (const [key, controller] of reloadControllersRef.current) {
      if (retainedKeys.has(key)) continue;
      jobsRef.current.delete(key);
      controller.abort();
      reloadControllersRef.current.delete(key);
      historyPagesRef.current.delete(key);
    }
    setLoadingSessionKeys((prev) => {
      const next = new Set([...prev].filter((key) => retainedKeys.has(key)));
      return next.size === prev.size ? prev : next;
    });
    setHistoryPages((prev) => retainSessionRecords(prev, retainedKeys));
    setMessageLoadErrors((prev) => retainSessionRecords(prev, retainedKeys));

    setSessionMessages((prev) => {
      let changed = false;
      const next: Record<string, ChatMessage[]> = {};
      for (const [key, messages] of Object.entries(prev)) {
        if (retainedKeys.has(key)) {
          next[key] = messages;
          continue;
        }
        changed = true;
      }
      return changed ? next : prev;
    });
  }, []);

  return {
    applyCachedSessionMessages,
    markSessionMessagesAccessed,
    isSessionMessagesPresented,
    publishSessionMessages,
    pruneSessionMessages,
    reloadSessionMessages,
    replaceSessionMessages,
    sessionMessages,
    loadingSessionKeys,
    messageLoadErrors,
    historyPages,
    loadOlderSessionMessages,
    updateSessionMessages,
  };
}

function countMessagesChars(messages: ChatMessage[]) {
  let total = 0;
  for (const message of messages) {
    total += message.content.length;
    total += message.thinkingContent.length;
    for (const part of message.contentParts ?? []) {
      if (part.type === "text") {
        total += part.text.length;
      }
    }
    for (const item of message.processItems ?? []) {
      if (item.type === "thinking" || item.type === "content") {
        total += item.content.length;
      } else if (item.type === "tool") {
        total += item.tool.arguments.length;
        total += item.tool.result.length;
        total += item.tool.error.length;
      }
    }
    for (const tool of message.toolCalls ?? []) {
      total += tool.arguments.length;
      total += tool.result.length;
      total += tool.error.length;
    }
  }
  return total;
}

function pageFromResponse(response: ConversationMessageListResponse): HistoryPage {
  return { before: response.next_before_message_id, after: response.next_after_message_id ?? response.items.at(-1)?.message_id ?? null,
    revision: response.revision ?? 0, reset: response.reset_revision ?? 0, reconcile: false };
}

export function mergeHistoryPage(current: ChatMessage[], incoming: ChatMessage[], options: {
  older?: boolean; replace?: boolean; tail?: boolean;
}) {
  if (options.replace) return incoming;
  let retained = current;
  if (options.tail && incoming.length) {
    const boundary = current.findIndex((message) => message.id === incoming[0].id);
    if (boundary >= 0) retained = current.slice(0, boundary);
    else retained = current.filter((message) => (message.createdAt ?? 0) < (incoming[0].createdAt ?? 0));
  }
  const merged = new Map<string, ChatMessage>();
  for (const message of options.older ? [...incoming, ...retained] : [...retained, ...incoming]) merged.set(message.id, message);
  return [...merged.values()].sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
}

function retainSessionRecords<T>(records: Record<string, T>, keys: ReadonlySet<string>) {
  const entries = Object.entries(records).filter(([key]) => keys.has(key));
  return entries.length === Object.keys(records).length ? records : Object.fromEntries(entries);
}

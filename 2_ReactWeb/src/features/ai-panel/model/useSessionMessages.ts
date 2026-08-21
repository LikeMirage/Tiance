import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { getProjectConversationMessages } from "../../../services/project/getProjectConversationMessages";
import { getCachedProjectEntryWarmup } from "../../project-entry/model/projectEntryWarmup";
import type { ChatMessage } from "./chatMessage";
import { mapConversationMessages } from "./chatMessage";
import { buildSessionKey } from "./sessionKey";

type ReloadSessionMessagesOptions = {
  forceRefresh?: boolean;
  preserveLocalIfShorter?: boolean;
  signal?: AbortSignal;
  shouldApply?: () => boolean;
  shouldPreserveLocal?: () => boolean;
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
  const sessionMessageSnapshotsRef = useRef<Record<string, ChatMessage[]>>({});
  const messageAccessedAtRef = useRef(new Map<string, number>());
  const reloadRequestIdsRef = useRef(new Map<string, number>());
  const reloadControllersRef = useRef(new Map<string, AbortController>());

  useEffect(() => () => {
    for (const controller of reloadControllersRef.current.values()) {
      controller.abort();
    }
    reloadControllersRef.current.clear();
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
      sessionMessageSnapshotsRef.current[key] = nextMessages;
    }
    publishSessionMessages(pid, sessionId);
    return true;
  }, [publishSessionMessages]);

  const reloadSessionMessages = useCallback(async (
    pid: string,
    sessionId: string,
    options: ReloadSessionMessagesOptions = {},
  ) => {
    const key = buildSessionKey(pid, sessionId);
    const requestId = (reloadRequestIdsRef.current.get(key) ?? 0) + 1;
    reloadRequestIdsRef.current.set(key, requestId);
    reloadControllersRef.current.get(key)?.abort();
    const controller = new AbortController();
    reloadControllersRef.current.set(key, controller);
    const abortFromCaller = () => controller.abort();
    if (options.signal?.aborted) {
      controller.abort();
    } else {
      options.signal?.addEventListener("abort", abortFromCaller, { once: true });
    }
    const timeout = window.setTimeout(
      () => controller.abort(),
      sessionMessagesRequestTimeoutMs,
    );
    const cachedResponse = options.forceRefresh
      ? null
      : getCachedProjectEntryWarmup(pid)?.sessionMessages[sessionId];
    try {
      const response = cachedResponse ?? await getProjectConversationMessages(
        pid,
        sessionId,
        { signal: controller.signal },
      );
      if (options.shouldApply && !options.shouldApply()) return false;
      if (reloadRequestIdsRef.current.get(key) !== requestId) return false;
      const nextMessages = mapConversationMessages(
        response.items,
        response.run_outcomes,
        response.run_attempt_failures,
      );
      messageAccessedAtRef.current.set(key, Date.now());
      const currentMessages = sessionMessageSnapshotsRef.current[key] ?? [];
      if (options.shouldPreserveLocal?.() && currentMessages.length > 0) {
        publishSessionMessages(pid, sessionId);
        return true;
      }
      if (options.preserveLocalIfShorter && currentMessages.length > nextMessages.length) {
        publishSessionMessages(pid, sessionId);
        return true;
      }
      if (hasSameMessageRevisions(currentMessages, nextMessages)) {
        publishSessionMessages(pid, sessionId);
        return true;
      }
      sessionMessageSnapshotsRef.current[key] = nextMessages;
      publishSessionMessages(pid, sessionId);
      return true;
    } finally {
      window.clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abortFromCaller);
      if (reloadControllersRef.current.get(key) === controller) {
        reloadControllersRef.current.delete(key);
      }
    }
  }, [publishSessionMessages]);

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
      reloadRequestIdsRef.current.delete(key);
      reloadControllersRef.current.get(key)?.abort();
      reloadControllersRef.current.delete(key);
    }
    if (snapshotsChanged) {
      sessionMessageSnapshotsRef.current = nextSnapshots;
    }

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

function hasSameMessageRevisions(
  currentMessages: ChatMessage[],
  nextMessages: ChatMessage[],
) {
  if (currentMessages.length !== nextMessages.length) return false;
  return currentMessages.every((message, index) => {
    const nextMessage = nextMessages[index];
    return message.id === nextMessage.id && message.updatedAt === nextMessage.updatedAt;
  });
}

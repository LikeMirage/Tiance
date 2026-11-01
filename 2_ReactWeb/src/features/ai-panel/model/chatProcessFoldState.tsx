import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import type { ChatMessage } from "./chatMessage";

type FoldSnapshot = Readonly<Record<string, boolean>>;
const EMPTY_FOLDS: FoldSnapshot = Object.freeze({});
const EMPTY_AUTOMATIC_FOLDS: ReadonlySet<string> = new Set();

// Panel-lifetime presentation state only. No messages, content or timings are stored here.
export function createChatProcessFoldStore() {
  const snapshots = new Map<string, FoldSnapshot>();
  const automaticSnapshots = new Map<string, ReadonlySet<string>>();
  const listeners = new Map<string, Set<() => void>>();
  return {
    get: (scope: string) => snapshots.get(scope) ?? EMPTY_FOLDS,
    getAutomatic: (scope: string, group: string) =>
      automaticSnapshots.get(JSON.stringify([scope, group])) ?? EMPTY_AUTOMATIC_FOLDS,
    setAutomatic(scope: string, group: string, expanded: ReadonlySet<string>) {
      const key = JSON.stringify([scope, group]);
      if ((automaticSnapshots.get(key) ?? EMPTY_AUTOMATIC_FOLDS) === expanded) return;
      automaticSnapshots.set(key, expanded);
      listeners.get(scope)?.forEach((notify) => notify());
    },
    set(scope: string, fold: string, expanded: boolean) {
      const previous = snapshots.get(scope) ?? EMPTY_FOLDS;
      if (previous[fold] === expanded) return;
      snapshots.set(scope, { ...previous, [fold]: expanded });
      listeners.get(scope)?.forEach((notify) => notify());
    },
    subscribe(scope: string, notify: () => void) {
      let subscribers = listeners.get(scope);
      if (!subscribers) listeners.set(scope, subscribers = new Set());
      subscribers.add(notify);
      return () => {
        subscribers.delete(notify);
        if (!subscribers.size) listeners.delete(scope);
      };
    },
  };
}

type FoldStore = ReturnType<typeof createChatProcessFoldStore>;
const PanelContext = createContext<{ store: FoldStore; sessionKey: string | null; isFollowing: boolean } | null>(null);
const TurnContext = createContext<{ store: FoldStore; scope: string; thinkingOffset: number; isFollowing: boolean } | null>(null);

export function ChatProcessFoldProvider({ sessionKey, children, isFollowing = true }: {
  sessionKey: string | null;
  isFollowing?: boolean;
  children: ReactNode;
}) {
  const [store] = useState(createChatProcessFoldStore);
  const value = useMemo(() => ({ store, sessionKey, isFollowing }), [store, sessionKey, isFollowing]);
  return <PanelContext.Provider value={value}>{children}</PanelContext.Provider>;
}

export function ChatProcessFoldScope({ turnId, thinkingOffset, children }: {
  turnId: string;
  thinkingOffset: number;
  children: ReactNode;
}) {
  const panel = useContext(PanelContext);
  if (!panel) throw new Error("ChatProcessFoldScope requires ChatProcessFoldProvider");
  const value = useMemo(() => ({
    store: panel.store,
    scope: JSON.stringify([panel.sessionKey, turnId]),
    thinkingOffset,
    isFollowing: panel.isFollowing,
  }), [panel, turnId, thinkingOffset]);
  return <TurnContext.Provider value={value}>{children}</TurnContext.Provider>;
}

export function useChatProcessFolds() {
  const context = useContext(TurnContext);
  if (!context) throw new Error("Process folds require ChatProcessFoldScope");
  const { store, scope, thinkingOffset } = context;
  const subscribe = useCallback((notify: () => void) => store.subscribe(scope, notify), [store, scope]);
  const getSnapshot = useCallback(() => store.get(scope), [store, scope]);
  const states = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const setExpanded = useCallback((fold: string, expanded: boolean) => {
    store.set(scope, fold, expanded);
  }, [store, scope]);
  return { states, setExpanded, thinkingOffset, isFollowing: context.isFollowing };
}

/** Only a mounted live response (including its completion transition) may
 * update automatic folds. History keeps its in-memory presentation even when
 * following resumes, a virtual row remounts, or another response starts.
 */
export function useAutomaticProcessFolds(
  group: string,
  desiredKey: string | null,
  isStreaming: boolean,
  allowCollapse: boolean,
) {
  const context = useContext(TurnContext);
  if (!context) throw new Error("Automatic folds require ChatProcessFoldScope");
  const { store, scope } = context;
  const subscribe = useCallback((notify: () => void) => store.subscribe(scope, notify), [store, scope]);
  const getSnapshot = useCallback(() => store.getAutomatic(scope, group), [store, scope, group]);
  const saved = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const previous = useRef({ scope, group, isStreaming: false });
  const completingLiveResponse = previous.current.scope === scope && previous.current.group === group
    && previous.current.isStreaming;
  let expanded = saved;
  if (isStreaming || completingLiveResponse) {
    const desired = allowCollapse ? new Set<string>() : new Set(saved);
    if (desiredKey !== null) desired.add(desiredKey);
    if (desired.size !== saved.size || [...desired].some((key) => !saved.has(key))) expanded = desired;
  }
  useLayoutEffect(() => {
    previous.current = { scope, group, isStreaming };
    store.setAutomatic(scope, group, expanded);
  }, [store, scope, group, isStreaming, expanded]);
  return expanded;
}

export function buildChatProcessFoldIdentities(messages: ChatMessage[]) {
  const identities = new Map<string, { turnId: string; thinkingOffset: number }>();
  let turnId = messages[0]?.id ?? "";
  let thinkingOffset = 0;
  for (const message of messages) {
    if (message.role === "user") {
      turnId = message.id;
      thinkingOffset = 0;
    }
    identities.set(message.id, { turnId, thinkingOffset });
    thinkingOffset += countMessageThinkingSegments(message);
  }
  return identities;
}

export function countMessageThinkingSegments(message: ChatMessage) {
  return message.processItems
    ? message.processItems.filter((item) => item.type === "thinking" && item.content.trim()).length
    : message.thinkingContent.trim() ? 1 : 0;
}

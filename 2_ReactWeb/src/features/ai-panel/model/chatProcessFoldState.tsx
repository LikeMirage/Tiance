import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import type { ChatMessage } from "./chatMessage";

type FoldSnapshot = Readonly<Record<string, boolean>>;
const EMPTY_FOLDS: FoldSnapshot = Object.freeze({});

// Panel-lifetime presentation state only. No messages, content or timings are stored here.
export function createChatProcessFoldStore() {
  const snapshots = new Map<string, FoldSnapshot>();
  const listeners = new Map<string, Set<() => void>>();
  return {
    get: (scope: string) => snapshots.get(scope) ?? EMPTY_FOLDS,
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
const PanelContext = createContext<{ store: FoldStore; sessionKey: string | null } | null>(null);
const TurnContext = createContext<{ store: FoldStore; scope: string; thinkingOffset: number } | null>(null);

export function ChatProcessFoldProvider({ sessionKey, children }: {
  sessionKey: string | null;
  children: ReactNode;
}) {
  const [store] = useState(createChatProcessFoldStore);
  const value = useMemo(() => ({ store, sessionKey }), [store, sessionKey]);
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
  return { states, setExpanded, thinkingOffset };
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

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

import type { ChatMessage } from "./chatMessage";
import type { UserMessageNavigationItem } from "./userMessageNavigation";

type UseMessageNavigatorActiveTurnOptions = {
  bodyRef: RefObject<HTMLDivElement | null>;
  enabled: boolean;
  items: UserMessageNavigationItem[];
  messages: ChatMessage[];
  sessionKey: string | null;
};

type ActiveTurn = {
  sessionKey: string;
  turnNumber: number | null;
  visibleMessageKeys: ReadonlySet<string>;
};

type ViewportMessageEntry = {
  bottom: number;
  isUserMessage: boolean;
  top: number;
  turnNumber: number;
};

export function useMessageNavigatorActiveTurn({
  bodyRef,
  enabled,
  items,
  messages,
  sessionKey,
}: UseMessageNavigatorActiveTurnOptions) {
  const frameIdRef = useRef<number | null>(null);
  const [activeTurn, setActiveTurn] = useState<ActiveTurn | null>(null);
  const messageTurnNumbers = useMemo(
    () => buildMessageTurnNumbers(messages, items),
    [items, messages],
  );
  const userMessageTurnNumbers = useMemo(
    () => new Map(items.map((item) => [item.userMessageId, item.turnNumber])),
    [items],
  );

  const syncActiveTurn = useCallback(() => {
    if (!enabled || !sessionKey) return;
    const body = bodyRef.current;
    if (!body) return;
    const { turnNumber, visibleMessageKeys } = readMessageViewport(
      body,
      messageTurnNumbers,
      userMessageTurnNumbers,
    );
    setActiveTurn((current) => {
      const nextTurnNumber = turnNumber ?? (current?.sessionKey === sessionKey ? current.turnNumber : null);
      return current?.sessionKey === sessionKey && current.turnNumber === nextTurnNumber
        && current.visibleMessageKeys.size === visibleMessageKeys.size
        && [...visibleMessageKeys].every((key) => current.visibleMessageKeys.has(key))
        ? current
        : { sessionKey, turnNumber: nextTurnNumber, visibleMessageKeys };
    });
  }, [bodyRef, enabled, messageTurnNumbers, sessionKey, userMessageTurnNumbers]);
  const syncActiveTurnRef = useRef(syncActiveTurn);
  syncActiveTurnRef.current = syncActiveTurn;

  const scheduleActiveTurnSync = useCallback(() => {
    if (frameIdRef.current !== null) return;
    frameIdRef.current = window.requestAnimationFrame(() => {
      frameIdRef.current = window.requestAnimationFrame(() => {
        frameIdRef.current = null;
        syncActiveTurnRef.current();
      });
    });
  }, []);

  useEffect(() => {
    if (enabled) scheduleActiveTurnSync();
  }, [enabled, items, messages, scheduleActiveTurnSync]);

  useEffect(() => {
    scheduleActiveTurnSync();
    return () => {
      if (frameIdRef.current !== null) {
        window.cancelAnimationFrame(frameIdRef.current);
        frameIdRef.current = null;
      }
    };
  }, [sessionKey, enabled, scheduleActiveTurnSync]);

  useEffect(() => {
    if (!enabled || !bodyRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(scheduleActiveTurnSync);
    observer.observe(bodyRef.current);
    // Includes explicit folds, images and layout changes without polling.
    for (const child of bodyRef.current.children) observer.observe(child);
    return () => observer.disconnect();
  }, [bodyRef, enabled, sessionKey, messages.length, scheduleActiveTurnSync]);

  const selectTurn = useCallback((turnNumber: number) => {
    if (!sessionKey) return;
    setActiveTurn((current) => ({ sessionKey, turnNumber,
      visibleMessageKeys: current?.sessionKey === sessionKey ? current.visibleMessageKeys : new Set() }));
  }, [sessionKey]);

  const activeTurnNumber = activeTurn?.sessionKey === sessionKey &&
    items.some((item) => item.turnNumber === activeTurn.turnNumber)
    ? activeTurn.turnNumber
    : items.at(-1)?.turnNumber ?? null;
  const activeUserMessageId = items.find(
    (item) => item.turnNumber === activeTurnNumber,
  )?.userMessageId ?? null;

  return {
    activeTurnNumber,
    activeUserMessageId,
    visibleMessageKeys: enabled && activeTurn?.sessionKey === sessionKey ? activeTurn.visibleMessageKeys : null,
    scheduleActiveTurnSync,
    selectTurn,
  };
}

export function buildMessageTurnNumbers(
  messages: ChatMessage[],
  items: UserMessageNavigationItem[],
) {
  const userTurns = new Map(
    items.map((item) => [item.userMessageId, item.turnNumber]),
  );
  const result = new Map<string, number>();
  for (const item of items) {
    result.set(item.userMessageId, item.turnNumber);
    if (item.assistantMessageId) result.set(item.assistantMessageId, item.turnNumber);
  }
  let currentTurnNumber: number | null = null;

  messages.forEach((message) => {
    if (message.role === "user") {
      currentTurnNumber = userTurns.get(message.id) ?? null;
    }
    if (currentTurnNumber !== null) {
      result.set(message.id, currentTurnNumber);
    }
  });

  return result;
}

export function readMessageViewport(
  body: HTMLDivElement,
  messageTurnNumbers: ReadonlyMap<string, number>,
  userMessageTurnNumbers: ReadonlyMap<string, number>,
) {
  const viewport = body.getBoundingClientRect();
  const messages = body.querySelectorAll<HTMLElement>("[data-chat-message-id]");
  const visibleEntries: ViewportMessageEntry[] = [];
  const visibleMessageKeys = new Set<string>();

  for (const message of messages) {
    const messageId = message.dataset.chatMessageId;
    const turnNumber = messageId ? messageTurnNumbers.get(messageId) : undefined;
    const bounds = message.getBoundingClientRect();
    if (bounds.bottom <= viewport.top) continue;
    if (bounds.top >= viewport.bottom) break;
    const messageKey = message.dataset.chatMessageKey ?? messageId;
    if (messageKey) visibleMessageKeys.add(messageKey);
    if (turnNumber === undefined) continue;
    visibleEntries.push({
      bottom: bounds.bottom,
      isUserMessage: Boolean(messageId && userMessageTurnNumbers.has(messageId)),
      top: bounds.top,
      turnNumber,
    });
  }

  return { turnNumber: resolveViewportTurnNumber(viewport.top, viewport.bottom, visibleEntries), visibleMessageKeys };
}

export function resolveViewportTurnNumber(
  viewportTop: number,
  viewportBottom: number,
  entries: readonly ViewportMessageEntry[],
) {
  const visibleUserMessage = entries.find((entry) => {
    if (!entry.isUserMessage) return false;
    const messageHeight = Math.max(1, entry.bottom - entry.top);
    const visibleHeight = Math.min(entry.bottom, viewportBottom) -
      Math.max(entry.top, viewportTop);
    const minimumVisibleHeight = Math.min(24, messageHeight * 0.35);
    return visibleHeight >= minimumVisibleHeight;
  });

  return visibleUserMessage?.turnNumber ?? entries[0]?.turnNumber ?? null;
}

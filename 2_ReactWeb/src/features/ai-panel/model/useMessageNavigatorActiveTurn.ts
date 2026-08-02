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
  turnNumber: number;
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
    const turnNumber = findViewportTurnNumber(
      body,
      messageTurnNumbers,
      userMessageTurnNumbers,
    );
    if (turnNumber === null) return;

    setActiveTurn((current) => (
      current?.sessionKey === sessionKey && current.turnNumber === turnNumber
        ? current
        : { sessionKey, turnNumber }
    ));
  }, [bodyRef, enabled, messageTurnNumbers, sessionKey, userMessageTurnNumbers]);

  const scheduleActiveTurnSync = useCallback(() => {
    if (frameIdRef.current !== null) return;
    frameIdRef.current = window.requestAnimationFrame(() => {
      frameIdRef.current = window.requestAnimationFrame(() => {
        frameIdRef.current = null;
        syncActiveTurn();
      });
    });
  }, [syncActiveTurn]);

  useEffect(() => {
    scheduleActiveTurnSync();
    return () => {
      if (frameIdRef.current !== null) {
        window.cancelAnimationFrame(frameIdRef.current);
        frameIdRef.current = null;
      }
    };
  }, [scheduleActiveTurnSync]);

  const selectTurn = useCallback((turnNumber: number) => {
    if (!sessionKey) return;
    setActiveTurn({ sessionKey, turnNumber });
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
    scheduleActiveTurnSync,
    selectTurn,
  };
}

function buildMessageTurnNumbers(
  messages: ChatMessage[],
  items: UserMessageNavigationItem[],
) {
  const completedTurns = new Map(
    items.map((item) => [item.userMessageId, item.turnNumber]),
  );
  const result = new Map<string, number>();
  let currentTurnNumber: number | null = null;

  messages.forEach((message) => {
    if (message.role === "user") {
      currentTurnNumber = completedTurns.get(message.id) ?? currentTurnNumber;
    }
    if (currentTurnNumber !== null) {
      result.set(message.id, currentTurnNumber);
    }
  });

  return result;
}

function findViewportTurnNumber(
  body: HTMLDivElement,
  messageTurnNumbers: ReadonlyMap<string, number>,
  userMessageTurnNumbers: ReadonlyMap<string, number>,
) {
  const viewport = body.getBoundingClientRect();
  const messages = body.querySelectorAll<HTMLElement>("[data-chat-message-id]");
  const visibleEntries: ViewportMessageEntry[] = [];

  for (const message of messages) {
    const messageId = message.dataset.chatMessageId;
    const turnNumber = messageId ? messageTurnNumbers.get(messageId) : undefined;
    if (turnNumber === undefined) continue;

    const bounds = message.getBoundingClientRect();
    if (bounds.bottom <= viewport.top) continue;
    if (bounds.top >= viewport.bottom) break;
    visibleEntries.push({
      bottom: bounds.bottom,
      isUserMessage: Boolean(messageId && userMessageTurnNumbers.has(messageId)),
      top: bounds.top,
      turnNumber,
    });
  }

  return resolveViewportTurnNumber(viewport.top, viewport.bottom, visibleEntries);
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

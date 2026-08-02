import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { WheelEvent } from "react";

import type { ChatMessage } from "./chatMessage";

export function useThinkingAutoScroll(messages: ChatMessage[]) {
  const thinkingContentRefs = useRef(new Map<string, HTMLDivElement>());
  const thinkingStickToBottomRefs = useRef(new Map<string, boolean>());
  const thinkingScrollFrameRefs = useRef(new Map<string, number>());
  const thinkingResizeObserversRef = useRef(new Map<string, ResizeObserver>());

  const scrollThinkingContentToBottom = useCallback((messageId: string) => {
    const previousFrame = thinkingScrollFrameRefs.current.get(messageId);
    if (previousFrame !== undefined) {
      window.cancelAnimationFrame(previousFrame);
    }

    const frame = window.requestAnimationFrame(() => {
      thinkingScrollFrameRefs.current.delete(messageId);
      const el = thinkingContentRefs.current.get(messageId);
      if (!el) return;
      el.scrollTop = el.scrollHeight;
      window.requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    });
    thinkingScrollFrameRefs.current.set(messageId, frame);
  }, []);

  useLayoutEffect(() => {
    messages.forEach((message) => {
      if (!message.isThinkingExpanded || !message.thinkingContent.trim()) return;
      if (thinkingStickToBottomRefs.current.get(message.id) === false) return;
      scrollThinkingContentToBottom(message.id);
    });
  }, [messages, scrollThinkingContentToBottom]);

  useEffect(() => {
    return () => {
      for (const frame of thinkingScrollFrameRefs.current.values()) {
        window.cancelAnimationFrame(frame);
      }
      thinkingScrollFrameRefs.current.clear();
      for (const observer of thinkingResizeObserversRef.current.values()) {
        observer.disconnect();
      }
      thinkingResizeObserversRef.current.clear();
    };
  }, []);

  const setThinkingContentRef = useCallback((messageId: string, node: HTMLDivElement | null) => {
    const existingObserver = thinkingResizeObserversRef.current.get(messageId);
    if (existingObserver) {
      existingObserver.disconnect();
      thinkingResizeObserversRef.current.delete(messageId);
    }

    if (node) {
      thinkingContentRefs.current.set(messageId, node);
      if (!thinkingStickToBottomRefs.current.has(messageId)) {
        thinkingStickToBottomRefs.current.set(messageId, true);
      }
      if (typeof ResizeObserver !== "undefined") {
        const observer = new ResizeObserver(() => {
          if (thinkingStickToBottomRefs.current.get(messageId) !== false) {
            scrollThinkingContentToBottom(messageId);
          }
        });
        observer.observe(node);
        const preview = node.querySelector(".markdown-preview");
        if (preview) {
          observer.observe(preview);
        }
        thinkingResizeObserversRef.current.set(messageId, observer);
      }
      if (thinkingStickToBottomRefs.current.get(messageId) !== false) {
        scrollThinkingContentToBottom(messageId);
      }
      return;
    }
    thinkingContentRefs.current.delete(messageId);
    thinkingStickToBottomRefs.current.delete(messageId);
    const frame = thinkingScrollFrameRefs.current.get(messageId);
    if (frame !== undefined) {
      window.cancelAnimationFrame(frame);
      thinkingScrollFrameRefs.current.delete(messageId);
    }
  }, [scrollThinkingContentToBottom]);

  const handleThinkingContentScroll = useCallback((messageId: string) => {
    const el = thinkingContentRefs.current.get(messageId);
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom < 16) {
      thinkingStickToBottomRefs.current.set(messageId, true);
    }
  }, []);

  const handleThinkingContentWheel = useCallback((messageId: string, event: WheelEvent<HTMLDivElement>) => {
    const el = thinkingContentRefs.current.get(messageId);
    if (!el || el.scrollHeight <= el.clientHeight) return;
    if (event.deltaY >= 0) return;
    thinkingStickToBottomRefs.current.set(messageId, false);
  }, []);

  const pauseThinkingAutoScroll = useCallback((messageId: string) => {
    const el = thinkingContentRefs.current.get(messageId);
    if (!el || el.scrollHeight <= el.clientHeight) return;
    thinkingStickToBottomRefs.current.set(messageId, false);
  }, []);

  const isThinkingStuckToBottom = useCallback((messageId: string) => (
    thinkingStickToBottomRefs.current.get(messageId) !== false
  ), []);

  return {
    handleThinkingContentScroll,
    handleThinkingContentWheel,
    isThinkingStuckToBottom,
    pauseThinkingAutoScroll,
    scrollThinkingContentToBottom,
    setThinkingContentRef,
  };
}

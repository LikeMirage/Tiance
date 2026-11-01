import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { WheelEvent } from "react";

import type { ChatMessage } from "./chatMessage";

export function useThinkingAutoScroll(messages: ChatMessage[], onPauseReading?: () => void) {
  const thinkingContentRefs = useRef(new Map<string, HTMLDivElement>());
  const thinkingStickToBottomRefs = useRef(new Map<string, boolean>());
  const thinkingScrollFrameRefs = useRef(new Map<string, number>());
  const thinkingResizeObserversRef = useRef(new Map<string, ResizeObserver>());

  const cancelThinkingScroll = useCallback((messageId: string) => {
    const frame = thinkingScrollFrameRefs.current.get(messageId);
    if (frame !== undefined) window.cancelAnimationFrame(frame);
    thinkingScrollFrameRefs.current.delete(messageId);
  }, []);

  const scrollThinkingContentToBottom = useCallback((messageId: string) => {
    if (thinkingScrollFrameRefs.current.has(messageId)) return;
    const step = () => {
      thinkingScrollFrameRefs.current.delete(messageId);
      const el = thinkingContentRefs.current.get(messageId);
      if (!el || thinkingStickToBottomRefs.current.get(messageId) === false) return;
      const target = Math.max(0, el.scrollHeight - el.clientHeight);
      const distance = target - el.scrollTop;
      if (Math.abs(distance) <= 1 || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        el.scrollTop = target;
        return;
      }
      // A single animation follows the moving tail instead of restarting on every token.
      el.scrollTop += distance * 0.35;
      thinkingScrollFrameRefs.current.set(messageId, window.requestAnimationFrame(step));
    };
    thinkingScrollFrameRefs.current.set(messageId, window.requestAnimationFrame(step));
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
    if (node && thinkingContentRefs.current.get(messageId) === node) return;
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
        const preview = node.querySelector(".sliding-content__inner") ?? node.querySelector(".markdown-preview");
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
    cancelThinkingScroll(messageId);
  }, [cancelThinkingScroll, scrollThinkingContentToBottom]);

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
    cancelThinkingScroll(messageId);
    onPauseReading?.();
  }, [cancelThinkingScroll, onPauseReading]);

  const pauseThinkingAutoScroll = useCallback((messageId: string) => {
    const el = thinkingContentRefs.current.get(messageId);
    if (!el || el.scrollHeight <= el.clientHeight) return;
    thinkingStickToBottomRefs.current.set(messageId, false);
    cancelThinkingScroll(messageId);
    onPauseReading?.();
  }, [cancelThinkingScroll, onPauseReading]);

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

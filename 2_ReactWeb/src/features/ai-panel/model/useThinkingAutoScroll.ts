import { useCallback, useRef, type WheelEvent } from "react";

import { createChatBottomFollower, type ChatBottomFollower } from "./chatBottomFollower";

type ThinkingViewport = {
  node: HTMLDivElement;
  follower: ChatBottomFollower;
  observer: ResizeObserver;
  following: boolean;
  lastScrollTop: number;
};

export function useThinkingAutoScroll(onPauseReading?: () => void) {
  const viewports = useRef(new Map<string, ThinkingViewport>());

  const setThinkingContentRef = useCallback((messageId: string, node: HTMLDivElement | null) => {
    const previous = viewports.current.get(messageId);
    if (previous?.node === node) return;
    if (previous) {
      previous.observer.disconnect();
      previous.follower.cancel();
      viewports.current.delete(messageId);
    }
    if (!node) return;

    const follower = createChatBottomFollower({
      canFollow: () => viewports.current.get(messageId)?.following === true,
      getScrollElement: () => node,
    });
    const observer = new ResizeObserver(follower.request);
    viewports.current.set(messageId, { node, follower, observer, following: true, lastScrollTop: node.scrollTop });
    observer.observe(node);
    // The preview stops growing at four lines. Its inner content keeps growing.
    const inner = node.querySelector(".sliding-content__inner");
    if (inner) observer.observe(inner);
    follower.request();
  }, []);

  const handleThinkingContentScroll = useCallback((messageId: string) => {
    const viewport = viewports.current.get(messageId);
    if (!viewport || viewport.following) return;
    const { node } = viewport;
    const top = node.scrollTop;
    if (top > viewport.lastScrollTop && node.scrollHeight - node.clientHeight - top < 16) {
      viewport.following = true;
      viewport.follower.request();
    }
    viewport.lastScrollTop = top;
  }, []);

  const pauseThinkingAutoScroll = useCallback((messageId: string) => {
    const viewport = viewports.current.get(messageId);
    if (!viewport || viewport.node.scrollHeight <= viewport.node.clientHeight) return;
    viewport.following = false;
    viewport.lastScrollTop = viewport.node.scrollTop;
    viewport.follower.cancel();
    onPauseReading?.();
  }, [onPauseReading]);

  const handleThinkingContentWheel = useCallback((messageId: string, event: WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) pauseThinkingAutoScroll(messageId);
  }, [pauseThinkingAutoScroll]);

  return {
    handleThinkingContentScroll,
    handleThinkingContentWheel,
    pauseThinkingAutoScroll,
    setThinkingContentRef,
  };
}

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  captureChatScrollPosition,
  type ChatScrollPosition,
  type ChatScrollRestoreRequest,
} from "./chatScrollPosition";
import {
  createChatBottomFollower,
  type ChatBottomFollower,
} from "./chatBottomFollower";
import type { ChatMessage } from "./chatMessage";

type UseBodyAutoScrollOptions = {
  activeSessionKey: string | null;
  isChatViewActive: boolean;
  messages: ChatMessage[];
  navigationTargetSessionKey?: string | null;
};

const NEAR_BOTTOM_PX = 8;
const NAVIGATION_GUARD_MAX_MS = 2500;
const SESSION_SETTLE_QUIET_MS = 420;
const SESSION_SETTLE_MAX_MS = 1200;

export function useBodyAutoScroll({
  activeSessionKey,
  isChatViewActive,
  messages,
  navigationTargetSessionKey = null,
}: UseBodyAutoScrollOptions) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const restoredSessionKeyRef = useRef<string | null>(null);
  const presentedSessionKeyRef = useRef<string | null>(null);
  const scrollPositionsRef = useRef(new Map<string, ChatScrollPosition>());
  const restoreRequestIdRef = useRef(0);
  const autoScrollEnabledRef = useRef(true);
  const bottomFollowerRef = useRef<ChatBottomFollower | null>(null);
  const isSessionSettlingRef = useRef(false);
  const isNavigationGuardedRef = useRef(false);
  const navigationGuardTimerRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const maxSettleTimerRef = useRef<number | null>(null);
  const settleFrameRef = useRef<number | null>(null);
  const [isSessionSettling, setIsSessionSettlingState] = useState(false);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [viewRestoreRequest, setViewRestoreRequest] =
    useState<ChatScrollRestoreRequest | null>(null);

  const setAutoScrollEnabled = useCallback((enabled: boolean) => {
    autoScrollEnabledRef.current = enabled;
    if (!enabled) bottomFollowerRef.current?.cancel();
  }, []);

  const setIsSessionSettling = useCallback((settling: boolean) => {
    isSessionSettlingRef.current = settling;
    setIsSessionSettlingState(settling);
  }, []);

  const clearSettleTimers = useCallback(() => {
    if (settleFrameRef.current !== null) {
      window.cancelAnimationFrame(settleFrameRef.current);
      settleFrameRef.current = null;
    }
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
    if (maxSettleTimerRef.current !== null) {
      window.clearTimeout(maxSettleTimerRef.current);
      maxSettleTimerRef.current = null;
    }
  }, []);

  const clearNavigationGuard = useCallback(() => {
    isNavigationGuardedRef.current = false;
    if (navigationGuardTimerRef.current !== null) {
      window.clearTimeout(navigationGuardTimerRef.current);
      navigationGuardTimerRef.current = null;
    }
  }, []);

  const startNavigationGuard = useCallback(() => {
    clearNavigationGuard();
    isNavigationGuardedRef.current = true;
    navigationGuardTimerRef.current = window.setTimeout(
      clearNavigationGuard,
      NAVIGATION_GUARD_MAX_MS,
    );
  }, [clearNavigationGuard]);

  const finishSessionSettle = useCallback(() => {
    if (!isSessionSettlingRef.current) return;
    clearSettleTimers();
    setIsSessionSettling(false);
    scrollElementToBottom(bodyRef.current);
    setAutoScrollEnabled(true);
    setShowScrollToBottom(false);
  }, [clearSettleTimers, setAutoScrollEnabled, setIsSessionSettling]);

  const scheduleSessionSettleFinish = useCallback(() => {
    if (!isSessionSettlingRef.current) return;
    if (settleFrameRef.current !== null) {
      window.cancelAnimationFrame(settleFrameRef.current);
      settleFrameRef.current = null;
    }
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current);
    }
    settleTimerRef.current = window.setTimeout(() => {
      settleTimerRef.current = null;
      settleFrameRef.current = window.requestAnimationFrame(() => {
        settleFrameRef.current = null;
        finishSessionSettle();
      });
    }, SESSION_SETTLE_QUIET_MS);
  }, [finishSessionSettle]);

  const cacheCurrentView = useCallback(() => {
    const el = bodyRef.current;
    if (!el || !activeSessionKey) return null;
    const position = captureChatScrollPosition(el, NEAR_BOTTOM_PX);
    scrollPositionsRef.current.set(activeSessionKey, position);
    return position;
  }, [activeSessionKey]);

  const preserveCurrentView = useCallback(() => {
    const position = cacheCurrentView();
    if (!position) return;
    setAutoScrollEnabled(position.isFollowingBottom);
    setShowScrollToBottom(!position.isFollowingBottom);
  }, [cacheCurrentView, setAutoScrollEnabled]);

  const pauseAutoScrollForNavigation = useCallback(() => {
    clearSettleTimers();
    startNavigationGuard();
    setIsSessionSettling(false);
    setAutoScrollEnabled(false);
    setShowScrollToBottom(true);
  }, [
    clearSettleTimers,
    setAutoScrollEnabled,
    setIsSessionSettling,
    startNavigationGuard,
  ]);

  const pauseForUserScroll = useCallback(() => {
    clearSettleTimers();
    clearNavigationGuard();
    setIsSessionSettling(false);
    setAutoScrollEnabled(false);
    setShowScrollToBottom(true);
    setViewRestoreRequest(null);
  }, [clearSettleTimers, clearNavigationGuard, setIsSessionSettling, setAutoScrollEnabled]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = bodyRef.current;
    if (!el) return;
    clearNavigationGuard();
    setAutoScrollEnabled(true);
    setShowScrollToBottom(false);
    if (behavior === "smooth" && bottomFollowerRef.current) {
      bottomFollowerRef.current.request();
    } else {
      bottomFollowerRef.current?.cancel();
      scrollElementToBottom(el);
    }
    if (activeSessionKey) {
      scrollPositionsRef.current.set(activeSessionKey, {
        anchorMessageId: null,
        anchorViewportOffset: 0,
        isFollowingBottom: true,
        scrollTop: el.scrollHeight,
      });
    }
  }, [activeSessionKey, clearNavigationGuard, setAutoScrollEnabled]);

  const handleBodyScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el || !isChatViewActive) return;
    if (isSessionSettlingRef.current) {
      setAutoScrollEnabled(true);
      setShowScrollToBottom(false);
      return;
    }
    if (bottomFollowerRef.current?.isActive()) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const isNearBottom = distanceToBottom < NEAR_BOTTOM_PX;
    if (isNavigationGuardedRef.current) {
      cacheCurrentView();
      setAutoScrollEnabled(false);
      setShowScrollToBottom(true);
      if (!isNearBottom) {
        clearNavigationGuard();
      }
      return;
    }

    // A late formula, table, image or font layout can move the scroll position
    // before ResizeObserver asks the follower to catch up. Only explicit user
    // intent handlers may cancel an active bottom-follow session; a layout-
    // generated scroll event must not turn following off by itself.
    if (autoScrollEnabledRef.current) {
      if (isNearBottom) cacheCurrentView();
      setShowScrollToBottom(false);
      if (!isNearBottom) {
        bottomFollowerRef.current?.request();
      }
      return;
    }
    cacheCurrentView();
    setAutoScrollEnabled(isNearBottom);
    setShowScrollToBottom(!isNearBottom);
  }, [
    cacheCurrentView,
    clearNavigationGuard,
    isChatViewActive,
    setAutoScrollEnabled,
  ]);

  // Neither delayed settling nor its queued animation frame may affect another
  // conversation, the settings screen, or a view the user has taken over.
  useLayoutEffect(() => () => {
    clearSettleTimers();
    clearNavigationGuard();
    isSessionSettlingRef.current = false;
    bottomFollowerRef.current?.cancel();
  }, [activeSessionKey, isChatViewActive, clearSettleTimers, clearNavigationGuard]);

  useLayoutEffect(() => {
    if (!isChatViewActive) {
      setIsSessionSettling(false);
      presentedSessionKeyRef.current = null;
      setViewRestoreRequest(null);
      return undefined;
    }

    const el = bodyRef.current;
    if (!el || !activeSessionKey) {
      setIsSessionSettling(false);
      return undefined;
    }

    const isNewPresentation = presentedSessionKeyRef.current !== activeSessionKey;
    presentedSessionKeyRef.current = activeSessionKey;
    const scrollMode = resolveSessionScrollMode(
      activeSessionKey,
      restoredSessionKeyRef.current,
      navigationTargetSessionKey,
    );
    if (scrollMode === "navigate") {
      clearSettleTimers();
      startNavigationGuard();
      restoredSessionKeyRef.current = activeSessionKey;
      setIsSessionSettling(false);
      setAutoScrollEnabled(false);
      setShowScrollToBottom(true);
      setViewRestoreRequest(null);
      return undefined;
    }
    if (!isNewPresentation) {
      return undefined;
    }

    const cachedPosition = scrollPositionsRef.current.get(activeSessionKey);
    if (cachedPosition && !cachedPosition.isFollowingBottom) {
      clearSettleTimers();
      clearNavigationGuard();
      restoredSessionKeyRef.current = activeSessionKey;
      setIsSessionSettling(false);
      setAutoScrollEnabled(false);
      setShowScrollToBottom(true);
      el.scrollTop = Math.min(
        cachedPosition.scrollTop,
        Math.max(0, el.scrollHeight - el.clientHeight),
      );
      if (cachedPosition.anchorMessageId) {
        restoreRequestIdRef.current += 1;
        setViewRestoreRequest({
          behavior: "auto",
          messageId: cachedPosition.anchorMessageId,
          requestId: restoreRequestIdRef.current,
          sessionKey: activeSessionKey,
          viewportOffset: cachedPosition.anchorViewportOffset,
        });
      }
      return undefined;
    }

    if (scrollMode === "restore") {
      clearSettleTimers();
      clearNavigationGuard();
      setIsSessionSettling(true);
      setAutoScrollEnabled(true);
      setShowScrollToBottom(false);
      setViewRestoreRequest(null);
      restoredSessionKeyRef.current = activeSessionKey;
      maxSettleTimerRef.current = window.setTimeout(
        finishSessionSettle,
        SESSION_SETTLE_MAX_MS,
      );
    } else {
      return undefined;
    }

    settleFrameRef.current = window.requestAnimationFrame(() => {
      settleFrameRef.current = null;
      if (!isSessionSettlingRef.current) return;
      scrollToBottom("auto");
      scheduleSessionSettleFinish();
    });
    // Session/view lifecycle cleanup above owns cancellation. A navigation
    // request for another session must not cancel this session's settle timers.
    return undefined;
  }, [
    activeSessionKey,
    clearNavigationGuard,
    clearSettleTimers,
    finishSessionSettle,
    isChatViewActive,
    navigationTargetSessionKey,
    scheduleSessionSettleFinish,
    scrollToBottom,
    setAutoScrollEnabled,
    setIsSessionSettling,
    startNavigationGuard,
  ]);

  const handleViewRestoreHandled = useCallback((requestId: number) => {
    setViewRestoreRequest((current) => (
      current?.requestId === requestId ? null : current
    ));
    window.requestAnimationFrame(cacheCurrentView);
  }, [cacheCurrentView]);

  const syncAfterContentReady = useCallback(() => {
    const el = bodyRef.current;
    if (!el || !activeSessionKey) return;
    if (autoScrollEnabledRef.current || isSessionSettlingRef.current) {
      if (isSessionSettlingRef.current) finishSessionSettle();
      else scrollElementToBottom(el);
      return;
    }
    if (isNavigationGuardedRef.current) return;
    const position = scrollPositionsRef.current.get(activeSessionKey);
    if (!position?.anchorMessageId) return;
    const anchor = Array.from(el.querySelectorAll<HTMLElement>("[data-chat-message-id]"))
      .find((element) => element.dataset.chatMessageId === position.anchorMessageId);
    if (!anchor) return;
    el.scrollTop += anchor.getBoundingClientRect().top - el.getBoundingClientRect().top - position.anchorViewportOffset;
  }, [activeSessionKey, finishSessionSettle]);

  useLayoutEffect(() => {
    if (!isChatViewActive || !activeSessionKey) return undefined;
    const scrollEl = bodyRef.current;
    if (!scrollEl) return undefined;

    const scheduleStickToBottom = () => {
      if (!autoScrollEnabledRef.current && !isSessionSettlingRef.current) return;
      if (isSessionSettlingRef.current) {
        bottomFollowerRef.current?.cancel();
        scrollElementToBottom(scrollEl);
        scheduleSessionSettleFinish();
        return;
      }
      bottomFollowerRef.current?.request();
    };

    const bottomFollower = createChatBottomFollower({
      canFollow: () => autoScrollEnabledRef.current && !isSessionSettlingRef.current,
      getScrollElement: () => bodyRef.current,
    });
    bottomFollowerRef.current = bottomFollower;

    const pauseForUpwardWheel = (event: WheelEvent) => {
      if (event.deltaY >= 0) return;
      pauseForUserScroll();
    };
    const pauseForScrollKey = (event: KeyboardEvent) => {
      if (!["ArrowUp", "Home", "PageUp"].includes(event.key)) return;
      pauseForUserScroll();
    };
    const pauseForScrollbarPointer = (event: PointerEvent) => {
      const rect = scrollEl.getBoundingClientRect();
      if (event.clientX < rect.right - scrollEl.offsetWidth + scrollEl.clientWidth) return;
      pauseForUserScroll();
    };

    const pauseForTouchScroll = pauseForUserScroll;

    const resizeObserver = new ResizeObserver(scheduleStickToBottom);
    const observedMessageElements = new Set<HTMLElement>();
    const observeRenderedMessages = () => {
      observedMessageElements.forEach((element) => {
        if (scrollEl.contains(element)) return;
        resizeObserver.unobserve(element);
        observedMessageElements.delete(element);
      });
      scrollEl.querySelectorAll<HTMLElement>("[data-chat-message-id]").forEach((element) => {
        if (observedMessageElements.has(element)) return;
        observedMessageElements.add(element);
        resizeObserver.observe(element);
      });
    };
    resizeObserver.observe(scrollEl);
    const messagesEl = scrollEl.querySelector(".ai-panel__messages");
    if (messagesEl instanceof HTMLElement) {
      resizeObserver.observe(messagesEl);
    }
    const virtualListEl = scrollEl.querySelector(".ai-panel__virtual-list");
    if (virtualListEl instanceof HTMLElement) {
      resizeObserver.observe(virtualListEl);
    }
    observeRenderedMessages();
    const mutationObserver = new MutationObserver(() => {
      observeRenderedMessages();
      scheduleStickToBottom();
    });
    mutationObserver.observe(scrollEl, { childList: true, subtree: true });
    scrollEl.addEventListener("wheel", pauseForUpwardWheel, { passive: true });
    scrollEl.addEventListener("keydown", pauseForScrollKey);
    scrollEl.addEventListener("pointerdown", pauseForScrollbarPointer);
    scrollEl.addEventListener("touchmove", pauseForTouchScroll, { passive: true });
    scrollEl.addEventListener("load", scheduleStickToBottom, true);
    scheduleStickToBottom();

    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      scrollEl.removeEventListener("wheel", pauseForUpwardWheel);
      scrollEl.removeEventListener("keydown", pauseForScrollKey);
      scrollEl.removeEventListener("pointerdown", pauseForScrollbarPointer);
      scrollEl.removeEventListener("touchmove", pauseForTouchScroll);
      scrollEl.removeEventListener("load", scheduleStickToBottom, true);
      bottomFollower.cancel();
      if (bottomFollowerRef.current === bottomFollower) {
        bottomFollowerRef.current = null;
      }
    };
  }, [
    activeSessionKey,
    isChatViewActive,
    messages.length,
    scheduleSessionSettleFinish,
    setAutoScrollEnabled,
    pauseForUserScroll,
  ]);

  useEffect(() => {
    return () => {
      clearNavigationGuard();
      clearSettleTimers();
      bottomFollowerRef.current?.cancel();
    };
  }, [clearNavigationGuard, clearSettleTimers]);

  return {
    bodyRef,
    handleBodyScroll,
    isSessionSettling,
    pauseAutoScrollForNavigation,
    preserveCurrentView,
    scrollToBottom,
    showScrollToBottom,
    viewRestoreRequest,
    onViewRestoreHandled: handleViewRestoreHandled,
    syncAfterContentReady,
  };
}

function scrollElementToBottom(el: HTMLDivElement | null) {
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

export function resolveSessionScrollMode(
  activeSessionKey: string | null,
  restoredSessionKey: string | null,
  navigationTargetSessionKey: string | null,
) {
  if (!activeSessionKey) return "preserve" as const;
  if (navigationTargetSessionKey === activeSessionKey) return "navigate" as const;
  if (restoredSessionKey !== activeSessionKey) return "restore" as const;
  return "preserve" as const;
}

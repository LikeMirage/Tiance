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

type UseBodyAutoScrollOptions = {
  activeSessionKey: string | null;
  isChatViewActive: boolean;
  navigationTargetSessionKey?: string | null;
};

const NEAR_BOTTOM_PX = 8;
const NAVIGATION_GUARD_MAX_MS = 2500;
const SESSION_SETTLE_QUIET_MS = 420;
const SESSION_SETTLE_MAX_MS = 1200;

export function useBodyAutoScroll({
  activeSessionKey,
  isChatViewActive,
  navigationTargetSessionKey = null,
}: UseBodyAutoScrollOptions) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const restoredSessionKeyRef = useRef<string | null>(null);
  const presentedSessionKeyRef = useRef<string | null>(null);
  const scrollPositionsRef = useRef(new Map<string, ChatScrollPosition>());
  const restoreRequestIdRef = useRef(0);
  const autoScrollEnabledRef = useRef(true);
  const [isFollowingBottom, setIsFollowingBottom] = useState(true);
  const [lockedSessions, setLockedSessions] = useState<ReadonlySet<string>>(() => new Set());
  const isBottomFollowLocked = activeSessionKey !== null && lockedSessions.has(activeSessionKey);
  const setBottomFollowLocked = useCallback((locked: boolean) => {
    if (!activeSessionKey) return;
    setLockedSessions((sessions) => {
      if (sessions.has(activeSessionKey) === locked) return sessions;
      const next = new Set(sessions);
      if (locked) next.add(activeSessionKey);
      else next.delete(activeSessionKey);
      return next;
    });
  }, [activeSessionKey]);
  const bottomFollowerRef = useRef<ChatBottomFollower | null>(null);
  const isSessionSettlingRef = useRef(false);
  const isNavigationGuardedRef = useRef(false);
  const navigationGuardTimerRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const maxSettleTimerRef = useRef<number | null>(null);
  const settleFrameRef = useRef<number | null>(null);
  const [isSessionSettling, setIsSessionSettlingState] = useState(false);
  const [viewRestoreRequest, setViewRestoreRequest] =
    useState<ChatScrollRestoreRequest | null>(null);
  // Scroll events may arrive before React publishes the new state. Keep the
  // immutable restore target protected synchronously throughout restoration.
  const pendingRestoreRef = useRef<ChatScrollRestoreRequest | null>(null);
  const updateViewRestoreRequest = useCallback((request: ChatScrollRestoreRequest | null) => {
    pendingRestoreRef.current = request;
    setViewRestoreRequest(request);
  }, []);

  const setAutoScrollEnabled = useCallback((enabled: boolean) => {
    autoScrollEnabledRef.current = enabled;
    setIsFollowingBottom(enabled);
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
    if (!el || !activeSessionKey || !isChatViewActive || pendingRestoreRef.current
      || presentedSessionKeyRef.current !== activeSessionKey) return;
    // Content can already have grown before ResizeObserver schedules the next frame.
    const position = captureChatScrollPosition(el, autoScrollEnabledRef.current);
    if (position.anchorMessageId) scrollPositionsRef.current.set(activeSessionKey, position);
  }, [activeSessionKey, isChatViewActive]);

  const pauseAutoScrollForNavigation = useCallback(() => {
    setBottomFollowLocked(false);
    updateViewRestoreRequest(null);
    clearSettleTimers();
    startNavigationGuard();
    setIsSessionSettling(false);
    setAutoScrollEnabled(false);
  }, [
    clearSettleTimers,
    setBottomFollowLocked,
    setAutoScrollEnabled,
    setIsSessionSettling,
    startNavigationGuard,
    updateViewRestoreRequest,
  ]);

  const pauseForUserScroll = useCallback(() => {
    if (isBottomFollowLocked) return;
    clearSettleTimers();
    clearNavigationGuard();
    setIsSessionSettling(false);
    setAutoScrollEnabled(false);
    updateViewRestoreRequest(null);
  }, [clearSettleTimers, clearNavigationGuard, isBottomFollowLocked, setIsSessionSettling, setAutoScrollEnabled, updateViewRestoreRequest]);

  const handleScrollbarScroll = useCallback((moved: boolean) => {
    if (!moved && !pendingRestoreRef.current) return;
    pauseForUserScroll();
    const el = bodyRef.current;
    if (moved && el && el.scrollHeight - el.clientHeight - el.scrollTop < NEAR_BOTTOM_PX) {
      setAutoScrollEnabled(true);
    }
  }, [pauseForUserScroll, setAutoScrollEnabled]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = bodyRef.current;
    if (!el) return;
    updateViewRestoreRequest(null);
    clearNavigationGuard();
    setAutoScrollEnabled(true);
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
  }, [activeSessionKey, clearNavigationGuard, setAutoScrollEnabled, updateViewRestoreRequest]);

  const activateBottomButton = useCallback((lockRequested: boolean) => {
    if (isBottomFollowLocked) {
      setBottomFollowLocked(false);
      return;
    }
    if (lockRequested) setBottomFollowLocked(true);
    scrollToBottom("smooth");
  }, [isBottomFollowLocked, scrollToBottom, setBottomFollowLocked]);

  const handleBodyScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el || !isChatViewActive) return;
    if (pendingRestoreRef.current) return;
    if (isSessionSettlingRef.current) {
      setAutoScrollEnabled(true);
      return;
    }
    if (bottomFollowerRef.current?.isActive()) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const isNearBottom = distanceToBottom < NEAR_BOTTOM_PX;
    if (isNavigationGuardedRef.current) {
      cacheCurrentView();
      setAutoScrollEnabled(false);
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
      if (!isNearBottom) {
        bottomFollowerRef.current?.request();
      }
      return;
    }
    setAutoScrollEnabled(isNearBottom);
    cacheCurrentView();
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
    pendingRestoreRef.current = null;
  }, [activeSessionKey, isChatViewActive, clearSettleTimers, clearNavigationGuard]);

  useLayoutEffect(() => {
    if (!isChatViewActive) {
      setIsSessionSettling(false);
      presentedSessionKeyRef.current = null;
      updateViewRestoreRequest(null);
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
      restoredSessionKeyRef.current = activeSessionKey;
      pauseAutoScrollForNavigation();
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
      if (cachedPosition.anchorMessageId) {
        restoreRequestIdRef.current += 1;
        updateViewRestoreRequest({
          behavior: "auto",
          messageId: cachedPosition.anchorMessageId,
          requestId: restoreRequestIdRef.current,
          sessionKey: activeSessionKey,
          viewportOffset: cachedPosition.anchorViewportOffset,
        });
      } else {
        el.scrollTop = cachedPosition.scrollTop;
      }
      return undefined;
    }

    // A fresh presentation also includes returning from settings in the same
    // session. Without a reading bookmark it must resume bottom following.
    clearSettleTimers();
    clearNavigationGuard();
    setIsSessionSettling(true);
    setAutoScrollEnabled(true);
    updateViewRestoreRequest(null);
    restoredSessionKeyRef.current = activeSessionKey;
    maxSettleTimerRef.current = window.setTimeout(
      finishSessionSettle,
      SESSION_SETTLE_MAX_MS,
    );

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
    pauseAutoScrollForNavigation,
    updateViewRestoreRequest,
  ]);

  const handleViewRestoreHandled = useCallback((requestId: number) => {
    const request = pendingRestoreRef.current;
    if (request?.requestId !== requestId || request.sessionKey !== activeSessionKey) return;
    updateViewRestoreRequest(null);
    // Do not leave a frame callback that can capture the next session's DOM.
    cacheCurrentView();
  }, [activeSessionKey, cacheCurrentView, updateViewRestoreRequest]);

  const syncAfterContentReady = useCallback(() => {
    const el = bodyRef.current;
    if (!el || !activeSessionKey) return;
    if (pendingRestoreRef.current) return;
    if (autoScrollEnabledRef.current || isSessionSettlingRef.current) {
      if (isSessionSettlingRef.current) finishSessionSettle();
      else scrollElementToBottom(el);
      return;
    }
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
      if ((event.deltaY < 0 && scrollEl.scrollTop > 0) || (pendingRestoreRef.current && event.deltaY !== 0)) {
        pauseForUserScroll();
      }
    };
    const pauseForScrollKey = (event: KeyboardEvent) => {
      const keys = pendingRestoreRef.current
        ? ["ArrowUp", "Home", "PageUp", "ArrowDown", "End", "PageDown", " "]
        : ["ArrowUp", "Home", "PageUp"];
      if (!keys.includes(event.key) || (!pendingRestoreRef.current && scrollEl.scrollTop <= 0)) return;
      pauseForUserScroll();
    };
    const pauseForScrollbarPointer = (event: PointerEvent) => {
      const rect = scrollEl.getBoundingClientRect();
      if (event.clientX < rect.right - scrollEl.offsetWidth + scrollEl.clientWidth) return;
      pauseForUserScroll();
    };

    let previousTouchY = 0;
    const trackTouchStart = (event: TouchEvent) => {
      previousTouchY = event.touches[0]?.clientY ?? 0;
    };
    const pauseForTouchScroll = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const y = event.touches[0].clientY;
      if ((y > previousTouchY && scrollEl.scrollTop > 0) || pendingRestoreRef.current) pauseForUserScroll();
      previousTouchY = y;
    };

    const resizeObserver = new ResizeObserver(scheduleStickToBottom);
    let messagesEl: Element | null = null;
    const observeMessageList = () => {
      const next = scrollEl.querySelector(".ai-panel__messages");
      if (next === messagesEl) return;
      if (messagesEl) resizeObserver.unobserve(messagesEl);
      messagesEl = next;
      if (messagesEl) resizeObserver.observe(messagesEl);
      scheduleStickToBottom();
    };
    resizeObserver.observe(scrollEl);
    observeMessageList();
    // Rebind when the empty state is replaced. Text, rich content and virtual
    // row measurements all change the height of the same message-list wrapper.
    const mutationObserver = new MutationObserver(observeMessageList);
    mutationObserver.observe(scrollEl, { childList: true });
    scrollEl.addEventListener("wheel", pauseForUpwardWheel, { passive: true });
    scrollEl.addEventListener("keydown", pauseForScrollKey);
    scrollEl.addEventListener("pointerdown", pauseForScrollbarPointer);
    scrollEl.addEventListener("touchstart", trackTouchStart, { passive: true });
    scrollEl.addEventListener("touchmove", pauseForTouchScroll, { passive: true });
    scrollEl.addEventListener("load", scheduleStickToBottom, true);
    scheduleStickToBottom();

    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      scrollEl.removeEventListener("wheel", pauseForUpwardWheel);
      scrollEl.removeEventListener("keydown", pauseForScrollKey);
      scrollEl.removeEventListener("pointerdown", pauseForScrollbarPointer);
      scrollEl.removeEventListener("touchstart", trackTouchStart);
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
    activateBottomButton,
    isBottomFollowLocked,
    isFollowingBottom,
    pauseForUserScroll,
    bodyRef,
    handleBodyScroll,
    handleScrollbarScroll,
    isSessionSettling,
    pauseAutoScrollForNavigation,
    preserveCurrentView: cacheCurrentView,
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

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  captureChatScrollPosition,
  type ChatScrollPosition,
  type ChatScrollRestoreRequest,
} from "./chatScrollPosition";
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
  const isSessionSettlingRef = useRef(false);
  const isNavigationGuardedRef = useRef(false);
  const navigationGuardTimerRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const maxSettleTimerRef = useRef<number | null>(null);
  const [isAutoScrollEnabled, setIsAutoScrollEnabled] = useState(true);
  const [isSessionSettling, setIsSessionSettlingState] = useState(false);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [viewRestoreRequest, setViewRestoreRequest] =
    useState<ChatScrollRestoreRequest | null>(null);

  const setAutoScrollEnabled = useCallback((enabled: boolean) => {
    autoScrollEnabledRef.current = enabled;
    setIsAutoScrollEnabled(enabled);
  }, []);

  const setIsSessionSettling = useCallback((settling: boolean) => {
    isSessionSettlingRef.current = settling;
    setIsSessionSettlingState(settling);
  }, []);

  const clearSettleTimers = useCallback(() => {
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
    clearSettleTimers();
    setIsSessionSettling(false);
    scrollElementToBottom(bodyRef.current);
    setAutoScrollEnabled(true);
    setShowScrollToBottom(false);
  }, [clearSettleTimers, setAutoScrollEnabled, setIsSessionSettling]);

  const scheduleSessionSettleFinish = useCallback(() => {
    if (!isSessionSettlingRef.current) return;
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current);
    }
    settleTimerRef.current = window.setTimeout(() => {
      settleTimerRef.current = null;
      window.requestAnimationFrame(finishSessionSettle);
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

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = bodyRef.current;
    if (!el) return;
    clearNavigationGuard();
    el.scrollTo({ top: el.scrollHeight, behavior });
    setAutoScrollEnabled(true);
    setShowScrollToBottom(false);
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
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const isNearBottom = distanceToBottom < NEAR_BOTTOM_PX;
    cacheCurrentView();
    if (isNavigationGuardedRef.current) {
      setAutoScrollEnabled(false);
      setShowScrollToBottom(true);
      if (!isNearBottom) {
        clearNavigationGuard();
      }
      return;
    }
    setAutoScrollEnabled(isNearBottom);
    setShowScrollToBottom(!isNearBottom);
  }, [
    cacheCurrentView,
    clearNavigationGuard,
    isChatViewActive,
    setAutoScrollEnabled,
  ]);

  useLayoutEffect(() => {
    if (!isChatViewActive) {
      presentedSessionKeyRef.current = null;
      setViewRestoreRequest(null);
      return undefined;
    }

    const el = bodyRef.current;
    if (!el || !activeSessionKey) {
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

    const frameId = window.requestAnimationFrame(() => {
      scrollToBottom("auto");
      scheduleSessionSettleFinish();
    });
    return () => window.cancelAnimationFrame(frameId);
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

  useLayoutEffect(() => {
    if (!isChatViewActive || !activeSessionKey) return undefined;
    const scrollEl = bodyRef.current;
    if (!scrollEl) return undefined;

    let frameId: number | null = null;
    const scheduleStickToBottom = () => {
      if (!autoScrollEnabledRef.current && !isSessionSettlingRef.current) return;
      if (isSessionSettlingRef.current) {
        scrollElementToBottom(scrollEl);
        scheduleSessionSettleFinish();
        return;
      }
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        if (autoScrollEnabledRef.current || isSessionSettlingRef.current) {
          scrollToBottom("auto");
          scheduleSessionSettleFinish();
        }
      });
    };

    const resizeObserver = new ResizeObserver(scheduleStickToBottom);
    resizeObserver.observe(scrollEl);
    const messagesEl = scrollEl.querySelector(".ai-panel__messages");
    if (messagesEl instanceof HTMLElement) {
      resizeObserver.observe(messagesEl);
    }
    const virtualListEl = scrollEl.querySelector(".ai-panel__virtual-list");
    if (virtualListEl instanceof HTMLElement) {
      resizeObserver.observe(virtualListEl);
    }
    scheduleStickToBottom();

    return () => {
      resizeObserver.disconnect();
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [
    activeSessionKey,
    isChatViewActive,
    messages.length,
    scheduleSessionSettleFinish,
    scrollToBottom,
  ]);

  useEffect(() => {
    if (isChatViewActive && isAutoScrollEnabled) {
      scrollToBottom("auto");
    }
  }, [isAutoScrollEnabled, isChatViewActive, messages, scrollToBottom]);

  useEffect(() => {
    return () => {
      clearNavigationGuard();
      clearSettleTimers();
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

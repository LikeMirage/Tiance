import { CaretDown } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject, type UIEventHandler } from "react";

import { buildUserMessageNavigationItems } from "../model/userMessageNavigation";
import { useMessageNavigatorActiveTurn } from "../model/useMessageNavigatorActiveTurn";
import type { ChatPanelView } from "./ChatHeader";
import {
  ChatMessageList,
  type ChatMessageNavigationRequest,
} from "./ChatMessageList";
import { ChatSettingsView } from "./ChatSettingsView";
import { UserMessageNavigator } from "./UserMessageNavigator";

type ChatPanelBodyFrameProps = {
  activeView: ChatPanelView;
  activeSessionKey: string | null;
  bodyRef: RefObject<HTMLDivElement | null>;
  externalNavigationRequest?: (ChatMessageNavigationRequest & { sessionKey: string }) | null;
  viewRestoreRequest?: (ChatMessageNavigationRequest & { sessionKey: string }) | null;
  chat: Parameters<typeof ChatMessageList>[0];
  isMessageNavigationTrackingEnabled: boolean;
  onBodyScroll: UIEventHandler<HTMLDivElement>;
  onActiveUserMessageChange?: (messageId: string | null) => void;
  onMessageNavigationStart: () => void;
  onExternalNavigationHandled?: (requestId: number) => void;
  onViewRestoreHandled?: (requestId: number) => void;
  scrollBottom: {
    isVisible: boolean;
    onClick: () => void;
  };
  settings: Parameters<typeof ChatSettingsView>[0];
};

export function ChatPanelBodyFrame({
  activeView,
  activeSessionKey,
  bodyRef,
  externalNavigationRequest = null,
  viewRestoreRequest = null,
  chat,
  isMessageNavigationTrackingEnabled,
  onActiveUserMessageChange,
  onBodyScroll,
  onMessageNavigationStart,
  onExternalNavigationHandled,
  onViewRestoreHandled,
  scrollBottom,
  settings,
}: ChatPanelBodyFrameProps) {
  const navigationRequestIdRef = useRef(0);
  const [navigationRequest, setNavigationRequest] =
    useState<(ChatMessageNavigationRequest & { sessionKey: string }) | null>(null);
  const navigationItems = useMemo(
    () => buildUserMessageNavigationItems(chat.messages),
    [chat.messages],
  );
  const localNavigationRequest = navigationRequest?.sessionKey === activeSessionKey
    ? navigationRequest
    : null;
  const activeExternalNavigationRequest = externalNavigationRequest?.sessionKey === activeSessionKey
    ? externalNavigationRequest
    : null;
  const activeViewRestoreRequest = viewRestoreRequest?.sessionKey === activeSessionKey
    ? viewRestoreRequest
    : null;
  const effectiveNavigationRequest =
    localNavigationRequest ?? activeExternalNavigationRequest ?? activeViewRestoreRequest;
  const handleNavigationHandled = useCallback((requestId: number) => {
    if (localNavigationRequest?.requestId === requestId) {
      setNavigationRequest((current) => current?.requestId === requestId ? null : current);
      return;
    }
    if (activeExternalNavigationRequest?.requestId === requestId) {
      onExternalNavigationHandled?.(requestId);
      return;
    }
    if (activeViewRestoreRequest?.requestId === requestId) {
      onViewRestoreHandled?.(requestId);
    }
  }, [
    activeExternalNavigationRequest?.requestId,
    activeViewRestoreRequest?.requestId,
    localNavigationRequest?.requestId,
    onExternalNavigationHandled,
    onViewRestoreHandled,
  ]);
  const hasMessageNavigator =
    activeView === "chat" && Boolean(activeSessionKey) && navigationItems.length >= 2;
  const messageNavigator = useMessageNavigatorActiveTurn({
    bodyRef,
    enabled: hasMessageNavigator && isMessageNavigationTrackingEnabled,
    items: navigationItems,
    messages: chat.messages,
    sessionKey: activeSessionKey,
  });
  useEffect(() => {
    onActiveUserMessageChange?.(messageNavigator.activeUserMessageId);
  }, [messageNavigator.activeUserMessageId, onActiveUserMessageChange]);
  const handleBodyScroll: UIEventHandler<HTMLDivElement> = (event) => {
    onBodyScroll(event);
    messageNavigator.scheduleActiveTurnSync();
  };

  return (
    <div className="ai-panel__body-frame">
      <div
        id="ai-panel-message-scroll-region"
        className={hasMessageNavigator
          ? "ai-panel__body ai-panel__body--with-message-navigator"
          : "ai-panel__body"}
        ref={bodyRef}
        onScroll={handleBodyScroll}
      >
        {activeView === "settings" ? (
          <ChatSettingsView {...settings} />
        ) : (
          <ChatMessageList
            {...chat}
            navigationRequest={effectiveNavigationRequest}
            onNavigationHandled={handleNavigationHandled}
          />
        )}
      </div>
      {hasMessageNavigator ? (
        <UserMessageNavigator
          activeTurnNumber={messageNavigator.activeTurnNumber}
          items={navigationItems}
          onSelect={(item) => {
            if (!activeSessionKey) return;
            onMessageNavigationStart();
            if (activeExternalNavigationRequest) {
              onExternalNavigationHandled?.(activeExternalNavigationRequest.requestId);
            }
            navigationRequestIdRef.current += 1;
            messageNavigator.selectTurn(item.turnNumber);
            setNavigationRequest({
              behavior: "smooth",
              messageId: item.userMessageId,
              requestId: navigationRequestIdRef.current,
              sessionKey: activeSessionKey,
            });
          }}
        />
      ) : null}
      {activeView === "chat" && scrollBottom.isVisible ? (
        <button
          className="ai-panel__scroll-bottom"
          type="button"
          aria-label="回到底部"
          title="回到底部"
          onClick={scrollBottom.onClick}
        >
          <CaretDown size={18} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

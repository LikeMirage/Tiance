import { useCallback, useEffect, type RefObject, type UIEventHandler } from "react";

import type { useConversationNavigation } from "../model/useConversationNavigation";
import { ChatPanelErrorNotice } from "./ChatPanelErrorNotice";
import { ChatProcessFoldProvider } from "../model/chatProcessFoldState";
import { useChatContentReadiness } from "../model/useChatContentReadiness";
import { ContentReadinessContext } from "../../../shared/lib/contentReadiness";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { EdgeScrollbar } from "../../../shared/ui/edge-scrollbar";
import { useMessageNavigatorActiveTurn } from "../model/useMessageNavigatorActiveTurn";
import type { ChatPanelView } from "./ChatHeader";
import {
  ChatMessageList,
  type ChatMessageNavigationRequest,
} from "./ChatMessageList";
import { ChatSettingsView } from "./ChatSettingsView";
import type { UserMessageNavigationItem } from "../model/userMessageNavigation";
import { UserMessageNavigator } from "./UserMessageNavigator";

type ChatPanelBodyFrameProps = {
  isFollowingBottom: boolean;
  activeView: ChatPanelView;
  activeSessionKey: string | null;
  navigation: ReturnType<typeof useConversationNavigation>;
  onSelectUserMessage: (item: UserMessageNavigationItem) => void;
  bodyRef: RefObject<HTMLDivElement | null>;
  externalNavigationRequest?: (ChatMessageNavigationRequest & { sessionKey: string }) | null;
  viewRestoreRequest?: (ChatMessageNavigationRequest & { sessionKey: string }) | null;
  chat: Parameters<typeof ChatMessageList>[0];
  isMessageNavigationTrackingEnabled: boolean;
  onBodyScroll: UIEventHandler<HTMLDivElement>;
  onUserScroll: () => void;
  onActiveUserMessageChange?: (messageId: string | null) => void;
  onExternalNavigationHandled?: (requestId: number) => void;
  onViewRestoreHandled?: (requestId: number) => void;
  onContentReady?: () => void;
  settings: Parameters<typeof ChatSettingsView>[0];
};

export function ChatPanelBodyFrame({
  isFollowingBottom,
  activeView,
  activeSessionKey,
  navigation,
  onSelectUserMessage,
  bodyRef,
  externalNavigationRequest = null,
  viewRestoreRequest = null,
  chat,
  isMessageNavigationTrackingEnabled,
  onActiveUserMessageChange,
  onBodyScroll,
  onUserScroll,
  onExternalNavigationHandled,
  onViewRestoreHandled,
  onContentReady,
  settings,
}: ChatPanelBodyFrameProps) {
  const { readiness, isPreparing } = useChatContentReadiness(
    activeView === "chat" ? activeSessionKey : null,
    Boolean(chat.isLoadingSession || (viewRestoreRequest?.sessionKey === activeSessionKey && !chat.loadError)),
    onContentReady,
  );
  const navigationItems = navigation.items;
  const activeExternalNavigationRequest = externalNavigationRequest?.sessionKey === activeSessionKey
    ? externalNavigationRequest
    : null;
  const activeViewRestoreRequest = viewRestoreRequest?.sessionKey === activeSessionKey
    ? viewRestoreRequest
    : null;
  const effectiveNavigationRequest =
    activeExternalNavigationRequest ?? activeViewRestoreRequest;
  const handleNavigationHandled = useCallback((requestId: number) => {
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
    onExternalNavigationHandled,
    onViewRestoreHandled,
  ]);
  const hasMessageNavigator =
    activeView === "chat" && Boolean(activeSessionKey) && navigationItems.length >= 2;
  const messageNavigator = useMessageNavigatorActiveTurn({
    bodyRef,
    enabled: activeView === "chat" && Boolean(activeSessionKey) && isMessageNavigationTrackingEnabled,
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
    <ContentReadinessContext.Provider value={readiness}>
    {activeView === "chat" ? <ChatPanelErrorNotice message={navigation.error} scopeKey={activeSessionKey}
      onRetry={navigation.retry} autoDismiss={false} /> : null}
    <div className="ai-panel__body-frame" data-chat-loading={isPreparing || undefined} aria-busy={isPreparing}>
      <div
        id="ai-panel-message-scroll-region"
        className={hasMessageNavigator
          ? "ai-panel__body ai-panel__body--with-message-navigator"
          : "ai-panel__body"}
        ref={bodyRef}
        aria-hidden={isPreparing || undefined}
        onScroll={handleBodyScroll}
      >
        <ChatProcessFoldProvider sessionKey={activeSessionKey} isFollowing={isFollowingBottom}
          visibleMessageKeys={messageNavigator.visibleMessageKeys}>
          {activeView === "settings" ? (
            <ChatSettingsView {...settings} />
          ) : (
            <ChatMessageList
              {...chat}
              navigationRequest={effectiveNavigationRequest}
              onNavigationHandled={handleNavigationHandled}
            />
          )}
        </ChatProcessFoldProvider>
      </div>
      <EdgeScrollbar
        scrollRef={bodyRef}
        scrollId="ai-panel-message-scroll-region"
        label={activeView === "chat" ? "对话滚动条" : "会话设置滚动条"}
        refreshKey={`${activeSessionKey}:${activeView}`}
        enabled={!isPreparing}
        onUserScroll={onUserScroll}
      />
      {isPreparing ? <div className="ai-panel__session-loading">
        <LoadingStrip ariaLabel="正在加载会话" label="正在加载会话" mode="fill" visual="bar" />
      </div> : null}
      {hasMessageNavigator && !isPreparing ? (
        <UserMessageNavigator
          activeTurnNumber={messageNavigator.activeTurnNumber}
          items={navigationItems}
          onSelect={(item) => {
            if (!activeSessionKey) return;
            messageNavigator.selectTurn(item.turnNumber);
            onSelectUserMessage(item);
          }}
        />
      ) : null}
    </div>
    </ContentReadinessContext.Provider>
  );
}

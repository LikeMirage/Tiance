import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type MutableRefObject,
  type RefObject,
} from "react";

import type { ChatMessage } from "../model/chatMessage";
import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import { buildChatDisplayMessages } from "../model/chatDisplayMessages";
import { buildModelSwitches } from "../model/chatModelTransitions";
import {
  ChatMessageItem,
  type ChatMessageItemInteractions,
} from "./ChatMessageItem";
import {
  useVirtualMessageList,
  type VirtualMessageItem,
} from "../model/useVirtualMessageList";

const VIRTUALIZE_MIN_HISTORICAL_MESSAGES = 28;

export type ChatMessageNavigationRequest = {
  behavior?: ScrollBehavior;
  messageId: string;
  requestId: number;
  viewportOffset?: number;
};

type ChatMessageListProps = {
  autoCollapseAssistantProcess: boolean;
  clockTick: number;
  expandedUserMessageIds: Set<string>;
  interactions: ChatMessageItemInteractions;
  isActiveSessionStreaming: boolean;
  isLoadingSession?: boolean;
  messages: ChatMessage[];
  navigationRequest?: ChatMessageNavigationRequest | null;
  onNavigationHandled?: (requestId: number) => void;
  runtimeStatus: ConversationRuntimeStatus | null;
  scrollParentRef: RefObject<HTMLDivElement | null>;
};

export function ChatMessageList({
  autoCollapseAssistantProcess,
  clockTick,
  expandedUserMessageIds,
  interactions,
  isActiveSessionStreaming,
  isLoadingSession = false,
  messages,
  navigationRequest = null,
  onNavigationHandled,
  runtimeStatus,
  scrollParentRef,
}: ChatMessageListProps) {
  const { t } = useI18n();
  const messageSizeCacheRef = useRef(new Map<string, number>());
  const displayMessages = useMemo(
    () => buildChatDisplayMessages(messages, { runtimeStatus }),
    [messages, runtimeStatus],
  );
  const historicalMessages = useStableHistoricalMessages(displayMessages);
  const modelSwitches = useMemo(
    () => buildModelSwitches(displayMessages),
    [displayMessages],
  );
  const liveMessage = displayMessages.length > 0
    ? displayMessages[displayMessages.length - 1]
    : null;

  useLayoutEffect(() => {
    const liveMessageId = liveMessage?.id;
    const scrollElement = scrollParentRef.current;
    if (!liveMessageId || !scrollElement) return undefined;
    const messageElement = findRenderedMessage(scrollElement, liveMessageId);
    if (!messageElement) return undefined;

    const measure = () => {
      const messageHeight = messageElement.getBoundingClientRect().height;
      const modelSwitchElement = messageElement.previousElementSibling;
      const modelSwitchHeight = modelSwitchElement instanceof HTMLElement &&
        modelSwitchElement.classList.contains("chat-msg__model-switch")
        ? modelSwitchElement.getBoundingClientRect().height
        : 0;
      messageSizeCacheRef.current.set(
        liveMessageId,
        Math.ceil(messageHeight + modelSwitchHeight),
      );
    };
    const observer = new ResizeObserver(measure);
    measure();
    observer.observe(messageElement);
    const modelSwitchElement = messageElement.previousElementSibling;
    if (
      modelSwitchElement instanceof HTMLElement &&
      modelSwitchElement.classList.contains("chat-msg__model-switch")
    ) {
      observer.observe(modelSwitchElement);
    }
    return () => observer.disconnect();
  }, [liveMessage?.id, scrollParentRef]);

  useEffect(() => {
    const visibleMessageIds = new Set(displayMessages.map((message) => message.id));
    messageSizeCacheRef.current.forEach((_, messageId) => {
      if (!visibleMessageIds.has(messageId)) {
        messageSizeCacheRef.current.delete(messageId);
      }
    });
  }, [displayMessages]);

  useEffect(() => {
    if (!navigationRequest || liveMessage?.id !== navigationRequest.messageId) return undefined;
    const frameId = window.requestAnimationFrame(() => {
      if (scrollRenderedMessageIntoView(
        scrollParentRef.current,
        navigationRequest.messageId,
        navigationRequest.behavior,
        navigationRequest.viewportOffset,
      )) {
        onNavigationHandled?.(navigationRequest.requestId);
      }
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [liveMessage?.id, navigationRequest, onNavigationHandled, scrollParentRef]);

  if (displayMessages.length === 0) {
    return (
      <div
        className={isLoadingSession ? "ai-panel__empty ai-panel__empty--loading" : "ai-panel__empty"}
        role={isLoadingSession ? "status" : undefined}
      >
        {isLoadingSession ? <span className="ai-panel__loading-spinner" aria-hidden="true" /> : null}
        <span>{isLoadingSession ? t("aiPanel.messageList.loadingSession") : t("aiPanel.messageList.empty")}</span>
      </div>
    );
  }

  return (
    <div className="ai-panel__messages">
      <HistoricalMessageItems
        autoCollapseAssistantProcess={autoCollapseAssistantProcess}
        expandedUserMessageIds={expandedUserMessageIds}
        interactions={interactions}
        messages={historicalMessages}
        modelSwitches={modelSwitches}
        navigationRequest={navigationRequest}
        onNavigationHandled={onNavigationHandled}
        scrollParentRef={scrollParentRef}
        sizeCacheRef={messageSizeCacheRef}
      />
      {liveMessage ? (
        <ChatMessageItem
          key={liveMessage.id}
          autoCollapseAssistantProcess={autoCollapseAssistantProcess}
          clockTick={clockTick}
          expandedUserMessageIds={expandedUserMessageIds}
          interactions={interactions}
          isLastMessage
          isSessionStreaming={isActiveSessionStreaming}
          message={liveMessage}
          modelSwitchModelId={modelSwitches.get(liveMessage.id) ?? null}
        />
      ) : null}
    </div>
  );
}

type HistoricalMessageItemsProps = {
  autoCollapseAssistantProcess: boolean;
  expandedUserMessageIds: Set<string>;
  interactions: ChatMessageItemInteractions;
  messages: ChatMessage[];
  modelSwitches: Map<string, string>;
  navigationRequest: ChatMessageNavigationRequest | null;
  onNavigationHandled?: (requestId: number) => void;
  scrollParentRef: RefObject<HTMLDivElement | null>;
  sizeCacheRef: MutableRefObject<Map<string, number>>;
};

const HistoricalMessageItems = memo(function HistoricalMessageItems({
  autoCollapseAssistantProcess,
  expandedUserMessageIds,
  interactions,
  messages,
  modelSwitches,
  navigationRequest,
  onNavigationHandled,
  scrollParentRef,
  sizeCacheRef,
}: HistoricalMessageItemsProps) {
  const shouldVirtualize = messages.length >= VIRTUALIZE_MIN_HISTORICAL_MESSAGES;
  const virtualList = useVirtualMessageList({
    enabled: shouldVirtualize,
    messages,
    scrollParentRef,
    sizeCacheRef,
  });
  const navigationTargetIsRendered = Boolean(
    navigationRequest && virtualList.virtualItems.some(
      (item) => item.message.id === navigationRequest.messageId,
    ),
  );

  useEffect(() => {
    if (!navigationRequest) return undefined;
    if (!messages.some((message) => message.id === navigationRequest.messageId)) {
      return undefined;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (shouldVirtualize) {
        if (navigationTargetIsRendered && scrollRenderedMessageIntoView(
          scrollParentRef.current,
          navigationRequest.messageId,
          "auto",
          navigationRequest.viewportOffset,
        )) {
          onNavigationHandled?.(navigationRequest.requestId);
          return;
        }
        virtualList.scrollToMessage(navigationRequest.messageId, "auto");
        return;
      }
      if (scrollRenderedMessageIntoView(
        scrollParentRef.current,
        navigationRequest.messageId,
        navigationRequest.behavior,
        navigationRequest.viewportOffset,
      )) {
        onNavigationHandled?.(navigationRequest.requestId);
      }
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [
    messages,
    navigationRequest,
    navigationTargetIsRendered,
    onNavigationHandled,
    scrollParentRef,
    shouldVirtualize,
    virtualList.scrollToMessage,
  ]);

  if (shouldVirtualize) {
    return (
      <div
        className="ai-panel__virtual-list"
        ref={virtualList.listRef}
        style={{ height: virtualList.totalSize }}
      >
        {virtualList.virtualItems.map((item) => (
          <VirtualMessageRow
            key={item.key}
            autoCollapseAssistantProcess={autoCollapseAssistantProcess}
            clockTick={0}
            expandedUserMessageIds={expandedUserMessageIds}
            interactions={interactions}
            item={item}
            modelSwitchModelId={modelSwitches.get(item.message.id) ?? null}
            onMeasure={virtualList.measureMessage}
          />
        ))}
      </div>
    );
  }

  return (
    <>
      {messages.map((message) => (
        <ChatMessageItem
          key={message.id}
          autoCollapseAssistantProcess={autoCollapseAssistantProcess}
          clockTick={0}
          expandedUserMessageIds={expandedUserMessageIds}
          interactions={interactions}
          isLastMessage={false}
          isSessionStreaming={false}
          message={message}
          modelSwitchModelId={modelSwitches.get(message.id) ?? null}
        />
      ))}
    </>
  );
});

type VirtualMessageRowProps = {
  autoCollapseAssistantProcess: boolean;
  clockTick: number;
  expandedUserMessageIds: Set<string>;
  interactions: ChatMessageItemInteractions;
  item: VirtualMessageItem;
  modelSwitchModelId: string | null;
  onMeasure: (messageId: string, index: number, height: number) => void;
};

function VirtualMessageRow({
  autoCollapseAssistantProcess,
  clockTick,
  expandedUserMessageIds,
  interactions,
  item,
  modelSwitchModelId,
  onMeasure,
}: VirtualMessageRowProps) {
  const rowRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = rowRef.current;
    if (!node) return undefined;

    const measure = () => {
      onMeasure(
        item.message.id,
        item.index,
        node.getBoundingClientRect().height,
      );
    };
    const observer = new ResizeObserver(measure);
    measure();
    observer.observe(node);

    return () => {
      observer.disconnect();
    };
  }, [item.index, item.message.id, onMeasure]);

  return (
    <div
      className="ai-panel__virtual-row"
      ref={rowRef}
      style={{ transform: `translateY(${item.start}px)` }}
    >
      <ChatMessageItem
        autoCollapseAssistantProcess={autoCollapseAssistantProcess}
        clockTick={clockTick}
        expandedUserMessageIds={expandedUserMessageIds}
        interactions={interactions}
        isLastMessage={false}
        isSessionStreaming={false}
        message={item.message}
        modelSwitchModelId={modelSwitchModelId}
      />
    </div>
  );
}

function useStableHistoricalMessages(messages: ChatMessage[]) {
  const stableRef = useRef<ChatMessage[]>([]);
  const historicalLength = Math.max(0, messages.length - 1);
  const current = stableRef.current;
  let canReuse = current.length === historicalLength;

  if (canReuse) {
    for (let index = 0; index < historicalLength; index += 1) {
      if (current[index] !== messages[index]) {
        canReuse = false;
        break;
      }
    }
  }

  if (canReuse) {
    return current;
  }

  const next = messages.slice(0, historicalLength);
  stableRef.current = next;
  return next;
}

function scrollRenderedMessageIntoView(
  scrollElement: HTMLDivElement | null,
  messageId: string,
  behavior: ScrollBehavior = "smooth",
  viewportOffset = 8,
) {
  if (!scrollElement) return false;
  const messageElement = findRenderedMessage(scrollElement, messageId);
  if (!messageElement) return false;
  const scrollRect = scrollElement.getBoundingClientRect();
  const messageRect = messageElement.getBoundingClientRect();
  scrollElement.scrollTo({
    top: Math.max(
      0,
      scrollElement.scrollTop + messageRect.top - scrollRect.top - viewportOffset,
    ),
    behavior,
  });
  return true;
}

function findRenderedMessage(
  scrollElement: HTMLDivElement,
  messageId: string,
) {
  return Array.from(
    scrollElement.querySelectorAll<HTMLElement>("[data-chat-message-id]"),
  ).find((element) => element.dataset.chatMessageId === messageId);
}

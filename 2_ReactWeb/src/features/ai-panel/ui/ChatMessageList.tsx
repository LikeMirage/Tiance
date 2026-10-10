import {
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type RefObject,
} from "react";

import type { ChatMessage } from "../model/chatMessage";
import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import { ContentReadinessContext } from "../../../shared/lib/contentReadiness";
import { createChatDisplayProjector } from "../model/chatDisplayMessages";
import { buildModelSwitches } from "../model/chatModelTransitions";
import { buildChatProcessFoldIdentities } from "../model/chatProcessFoldState";
import {
  ChatMessageItem,
  type ChatMessageItemInteractions,
} from "./ChatMessageItem";
import {
  useVirtualMessageList,
  type VirtualMessageItem,
} from "../model/useVirtualMessageList";

const VIRTUALIZE_MIN_HISTORICAL_MESSAGES = 28;
const noPendingContent = () => 0;
const subscribeNoContent = () => () => {};

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
  const readiness = useContext(ContentReadinessContext);
  const contentPending = useSyncExternalStore(readiness?.subscribe ?? subscribeNoContent,
    readiness?.getSnapshot ?? noPendingContent, readiness?.getSnapshot ?? noPendingContent);
  const messageSizeCacheRef = useRef(new Map<string, number>());
  const projectDisplayMessages = useMemo(() => createChatDisplayProjector(), []);
  const effectiveRuntimeStatus = isActiveSessionStreaming ? "running" : runtimeStatus;
  const displayMessages = useMemo(
    () => projectDisplayMessages(messages, { runtimeStatus: effectiveRuntimeStatus }),
    [messages, effectiveRuntimeStatus, projectDisplayMessages],
  );
  const historicalMessages = useStableHistoricalMessages(displayMessages);
  const modelSwitches = useStableModelSwitches(displayMessages);
  const foldIdentities = useMemo(() => buildChatProcessFoldIdentities(displayMessages), [displayMessages]);
  const liveMessage = [...displayMessages].reverse().find((message) => message.role === "assistant") ?? null;
  const lastUserIndex = displayMessages.reduce((last, message, index) => message.role === "user" ? index : last, -1);
  const liveMessageIndex = liveMessage ? displayMessages.indexOf(liveMessage) : -1;
  const activeAssistantId = (isActiveSessionStreaming || runtimeStatus === "running")
    && liveMessageIndex > lastUserIndex && liveMessage?.finishReason !== "output_limit"
    ? liveMessage?.id ?? null : null;
  const shouldVirtualize = historicalMessages.length >= VIRTUALIZE_MIN_HISTORICAL_MESSAGES;
  const virtualList = useVirtualMessageList({ enabled: shouldVirtualize, keepLastMessageMounted: true, keepMessageMountedId: activeAssistantId,
    messages: displayMessages, scrollParentRef, sizeCacheRef: messageSizeCacheRef });
  const navigationTargetIsRendered = Boolean(navigationRequest && virtualList.virtualItems.some(
    (item) => item.message.id === navigationRequest.messageId,
  ));

  useLayoutEffect(() => {
    const liveMessageId = liveMessage?.id;
    const scrollElement = scrollParentRef.current;
    if (!liveMessageId || !scrollElement) return undefined;
    const messageElement = findRenderedMessage(scrollElement, liveMessageId);
    if (!messageElement) return undefined;

    const measure = () => {
      if (messageElement.querySelector('[aria-busy="true"]')) return;
      const messageHeight = messageElement.getBoundingClientRect().height;
      const modelSwitchElement = messageElement.previousElementSibling;
      const modelSwitchHeight = modelSwitchElement instanceof HTMLElement &&
        modelSwitchElement.classList.contains("chat-msg__model-switch")
        ? modelSwitchElement.getBoundingClientRect().height
        : 0;
      messageSizeCacheRef.current.set(
        liveMessage?.displayKey ?? liveMessageId,
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
  }, [liveMessage?.id, liveMessage?.displayKey, scrollParentRef]);

  useEffect(() => {
    const visibleMessageIds = new Set(displayMessages.map((message) => message.displayKey ?? message.id));
    messageSizeCacheRef.current.forEach((_, messageId) => {
      if (!visibleMessageIds.has(messageId)) {
        messageSizeCacheRef.current.delete(messageId);
      }
    });
  }, [displayMessages]);

  useEffect(() => {
    if (!navigationRequest || contentPending) return undefined;
    if (!displayMessages.some((message) => message.id === navigationRequest.messageId)) return undefined;
    const frameId = window.requestAnimationFrame(() => {
      if (shouldVirtualize && !navigationTargetIsRendered) {
        virtualList.scrollToMessage(navigationRequest.messageId, "auto");
        return;
      }
      if (scrollRenderedMessageIntoView(
        scrollParentRef.current,
        navigationRequest.messageId,
        shouldVirtualize ? "auto" : navigationRequest.behavior,
        navigationRequest.viewportOffset,
      )) {
        onNavigationHandled?.(navigationRequest.requestId);
      }
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [contentPending, displayMessages, navigationRequest, navigationTargetIsRendered, onNavigationHandled,
    scrollParentRef, shouldVirtualize, virtualList.scrollToMessage]);

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

  const renderedItems = shouldVirtualize ? virtualList.virtualItems : displayMessages.map((message, index) => ({
    index, key: message.displayKey ?? message.id, message, size: 0, start: 0,
  }));

  return <div className="ai-panel__messages">
    <div className={shouldVirtualize ? "ai-panel__virtual-list" : undefined} ref={virtualList.listRef}
      style={shouldVirtualize ? { height: virtualList.totalSize } : undefined}>
      {renderedItems.map((item) => {
        const isLastMessage = item.index === displayMessages.length - 1;
        const identity = foldIdentities.get(item.message.id);
        return <VirtualMessageRow
          key={item.key}
          autoCollapseAssistantProcess={autoCollapseAssistantProcess}
          clockTick={item.message.id === activeAssistantId ? clockTick : 0}
          expandedUserMessageIds={expandedUserMessageIds}
          interactions={interactions}
          isLastMessage={isLastMessage}
          isVirtualized={shouldVirtualize}
          isSessionStreaming={item.message.id === activeAssistantId}
          item={item}
          foldTurnId={identity!.turnId}
          foldThinkingOffset={identity!.thinkingOffset}
          modelSwitchModelId={modelSwitches.get(item.message.id) ?? null}
          onMeasure={virtualList.measureMessage}
        />;
      })}
    </div>
  </div>;
}

type VirtualMessageRowProps = {
  isVirtualized: boolean;
  isLastMessage: boolean;
  isSessionStreaming: boolean;
  foldTurnId: string;
  foldThinkingOffset: number;
  autoCollapseAssistantProcess: boolean;
  clockTick: number;
  expandedUserMessageIds: Set<string>;
  interactions: ChatMessageItemInteractions;
  item: VirtualMessageItem;
  modelSwitchModelId: string | null;
  onMeasure: (messageId: string, index: number, height: number) => void;
};

function VirtualMessageRow({
  isVirtualized,
  isLastMessage,
  isSessionStreaming,
  foldTurnId,
  foldThinkingOffset,
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
    if (!node || !isVirtualized) return undefined;

    const measure = () => {
      // A reattached deferred preview is briefly empty. Do not let that empty
      // height evict neighboring rows and cancel/restart their Markdown jobs.
      if (node.querySelector('[aria-busy="true"]')) return;
      onMeasure(
        item.key,
        item.index,
        node.getBoundingClientRect().height,
      );
    };
    const observer = new ResizeObserver(measure);
    let frame: number | null = null;
    const mutations = new MutationObserver(() => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => { frame = null; measure(); });
    });
    measure();
    observer.observe(node);
    mutations.observe(node, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-busy"] });

    return () => {
      observer.disconnect();
      mutations.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [isVirtualized, item.index, item.key, onMeasure]);

  return (
    <div
      className={isVirtualized ? "ai-panel__virtual-row" : undefined}
      ref={rowRef}
      style={isVirtualized ? { transform: `translateY(${item.start}px)` } : undefined}
    >
      <ChatMessageItem
        autoCollapseAssistantProcess={autoCollapseAssistantProcess}
        clockTick={clockTick}
        expandedUserMessageIds={expandedUserMessageIds}
        interactions={interactions}
        isLastMessage={isLastMessage}
        isSessionStreaming={isSessionStreaming}
        message={item.message}
        foldTurnId={foldTurnId}
        foldThinkingOffset={foldThinkingOffset}
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

function useStableModelSwitches(messages: ChatMessage[]) {
  const previousRef = useRef(new Map<string, string>());
  return useMemo(() => {
    const next = buildModelSwitches(messages);
    const previous = previousRef.current;
    if (next.size === previous.size && Array.from(next).every(([id, model]) => previous.get(id) === model)) {
      return previous;
    }
    previousRef.current = next;
    return next;
  }, [messages]);
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

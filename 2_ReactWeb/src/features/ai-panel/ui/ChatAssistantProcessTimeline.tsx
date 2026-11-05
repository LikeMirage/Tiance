import { useMemo } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { SlidingContent } from "../../../shared/ui/sliding-content/SlidingContent";

import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import {
  findLastRunningThinkingId,
  resolveAssistantMessageElapsedSeconds,
  resolveProcessElapsedSeconds,
} from "../model/chatAssistantProcessTime";
import { resolveAssistantBodyContent } from "../model/chatDisplayMessages";
import { useAutomaticProcessFolds, useChatProcessFolds } from "../model/chatProcessFoldState";
import type {
  ChatAssistantProcessItem,
  ChatMessage,
} from "../model/chatMessage";
import type { ChatMessageItemInteractions } from "./chatMessageItemTypes";
import { ChatThinkingContent } from "./ChatThinkingContent";
import { RunFailureNotice, ChatNotificationNotice } from "./ChatRunNotices";
import {
  formatElapsedSeconds,
  ToolProcessBlock,
  toolGroupFoldKey,
  type ToolProcessEntry,
} from "./ChatToolProcessBlock";

type AssistantProcessTimelineProps = {
  autoCollapseProcess: boolean;
  clockTick: number;
  interactions: ChatMessageItemInteractions;
  isStreamingMessage: boolean;
  message: ChatMessage;
};

type AssistantProcessRenderItem =
  | Extract<ChatAssistantProcessItem, { type: "thinking" | "content" | "attempt_failure" | "notification" }>
  | {
      id: string;
      type: "tool_group";
      entries: ToolProcessEntry[];
    };

type RenderAssistantProcessItemOptions = {
  clockTick: number;
  interactions: ChatMessageItemInteractions;
  isStreamingMessage: boolean;
  item: AssistantProcessRenderItem;
  lastRunningThinkingId: string | null;
  message: ChatMessage;
  resolveFoldExpanded: (foldId: string) => boolean;
  toggleFold: (foldId: string, currentExpanded: boolean) => void;
  foldKey?: string;
};

type ThinkingProcessBlockProps = {
  foldKey: string;
  clockTick: number;
  interactions: ChatMessageItemInteractions;
  isExpanded: boolean;
  isLiveSegment: boolean;
  isStreaming: boolean;
  item: Extract<ChatAssistantProcessItem, { type: "thinking" }>;
  message: ChatMessage;
  onToggleExpanded: () => void;
};

const EMPTY_PROCESS_ITEMS: ChatAssistantProcessItem[] = [];

export function AssistantProcessTimeline({
  autoCollapseProcess,
  clockTick,
  interactions,
  isStreamingMessage,
  message,
}: AssistantProcessTimelineProps) {
  const { states: manualFoldStates, setExpanded, thinkingOffset, allowAutomaticCollapse } = useChatProcessFolds();
  const items = message.processItems ?? EMPTY_PROCESS_ITEMS;
  const renderItems = useMemo(() => buildAssistantProcessRenderItems(items), [items]);
  const foldKeys = useMemo(() => {
    const keys = new Map<string, string>();
    let thinkingIndex = thinkingOffset;
    for (const item of renderItems) {
      if (item.type === "thinking") keys.set(item.id, `thinking:${thinkingIndex++}`);
      if (item.type === "tool_group") keys.set(item.id, toolGroupFoldKey(item.entries));
    }
    return keys;
  }, [renderItems, thinkingOffset]);
  const lastRunningThinkingId = useMemo(() => findLastRunningThinkingId(items), [items]);
  const hasTrailingBodyContent = useMemo(
    () => resolveAssistantBodyContent(message).trim().length > 0,
    [message],
  );
  const autoExpandedFoldId = useMemo(() => (
    isStreamingMessage && !hasTrailingBodyContent
      ? resolveLatestAutoExpandedFoldId(renderItems)
      : null
  ), [hasTrailingBodyContent, isStreamingMessage, renderItems]);
  const desiredFoldKey = autoExpandedFoldId ? foldKeys.get(autoExpandedFoldId) : undefined;
  const automaticFolds = useAutomaticProcessFolds(
    `timeline:${thinkingOffset}`, desiredFoldKey ?? null, isStreamingMessage, allowAutomaticCollapse,
  );
  const resolveFoldExpanded = (foldId: string) =>
    manualFoldStates[foldKeys.get(foldId)!] ?? automaticFolds.has(foldKeys.get(foldId)!);
  const toggleFold = (foldId: string, currentExpanded: boolean) => {
    setExpanded(foldKeys.get(foldId)!, !currentExpanded);
  };
  if (!renderItems.length && !autoCollapseProcess) return null;

  return (
    <section className="chat-msg__process">
      {renderItems.length > 0 || autoCollapseProcess ? (
        <ProcessedProcessBlock
          showHeader={autoCollapseProcess}
          clockTick={clockTick}
          interactions={interactions}
          isStreamingMessage={isStreamingMessage}
          items={renderItems}
          foldKeys={foldKeys}
          lastRunningThinkingId={lastRunningThinkingId}
          message={message}
          resolveFoldExpanded={resolveFoldExpanded}
          toggleFold={toggleFold}
          totalElapsedSeconds={
            resolveAssistantMessageElapsedSeconds(message, clockTick) ??
            resolveRenderItemsElapsedSeconds(renderItems, clockTick)
          }
        />
      ) : null}
    </section>
  );
}

function buildAssistantProcessRenderItems(items: ChatAssistantProcessItem[]) {
  const renderItems: AssistantProcessRenderItem[] = [];
  let toolGroup: ToolProcessEntry[] = [];
  let toolGroupIndex = 0;

  const flushToolGroup = () => {
    if (toolGroup.length === 0) return;
    toolGroupIndex += 1;
    renderItems.push({
      id: `tool-group-${toolGroupIndex}`,
      type: "tool_group",
      entries: toolGroup,
    });
    toolGroup = [];
  };

  items.forEach((item) => {
    if (item.type === "tool") {
      toolGroup.push({
        id: item.id,
        type: "tool",
        tool: item.tool,
      });
      return;
    }
    if (item.type === "tool_preparing") {
      toolGroup.push(item);
      return;
    }
    flushToolGroup();
    if (item.type === "content" && !item.content.trim()) {
      return;
    }
    if (item.type === "thinking" && !item.content.trim()) {
      return;
    }
    renderItems.push(item);
  });
  flushToolGroup();

  return renderItems;
}

function renderAssistantProcessItem({
  clockTick,
  interactions,
  isStreamingMessage,
  item,
  lastRunningThinkingId,
  message,
  resolveFoldExpanded,
  toggleFold,
  foldKey,
}: RenderAssistantProcessItemOptions) {
  if (item.type === "notification") {
    return <ChatNotificationNotice key={item.id} message={item.message} />;
  }
  if (item.type === "attempt_failure") {
    return <RunFailureNotice key={item.id} message={item.message} />;
  }
  if (item.type === "tool_group") {
    const isExpanded = resolveFoldExpanded(item.id);
    return (
      <ToolProcessBlock
        key={item.id}
        clockTick={clockTick}
        entries={item.entries}
        isExpanded={isExpanded}
        onToggleExpanded={() => toggleFold(item.id, isExpanded)}
      />
    );
  }
  if (item.type === "content") {
    return (
      <AssistantContentProcessBlock
        key={item.id}
        content={item.content}
        interactions={interactions}
        isStreaming={false}
      />
    );
  }
  const isExpanded = resolveFoldExpanded(item.id);
  return (
    <ThinkingProcessBlock
      key={foldKey ?? item.id}
      foldKey={foldKey!}
      clockTick={clockTick}
      interactions={interactions}
      isExpanded={isExpanded}
      isLiveSegment={isStreamingMessage && item.id === lastRunningThinkingId}
      isStreaming={isStreamingMessage && item.status === "running"}
      item={item}
      message={message}
      onToggleExpanded={() => toggleFold(item.id, isExpanded)}
    />
  );
}

function ProcessedProcessBlock({
  showHeader,
  clockTick,
  interactions,
  isStreamingMessage,
  items,
  foldKeys,
  lastRunningThinkingId,
  message,
  totalElapsedSeconds,
  resolveFoldExpanded,
  toggleFold,
}: {
  showHeader: boolean;
  clockTick: number;
  interactions: ChatMessageItemInteractions;
  isStreamingMessage: boolean;
  items: AssistantProcessRenderItem[];
  foldKeys: Map<string, string>;
  lastRunningThinkingId: string | null;
  message: ChatMessage;
  totalElapsedSeconds: number | null;
  resolveFoldExpanded: RenderAssistantProcessItemOptions["resolveFoldExpanded"];
  toggleFold: RenderAssistantProcessItemOptions["toggleFold"];
}) {
  const { states, setExpanded, allowAutomaticCollapse, thinkingOffset } = useChatProcessFolds();
  const hasManualOpenChild = Object.entries(states).some(([key, value]) => key !== "processed" && value);
  const automaticExpanded = useAutomaticProcessFolds(
    `processed:${thinkingOffset}`, isStreamingMessage ? "expanded" : null,
    isStreamingMessage, allowAutomaticCollapse && !hasManualOpenChild,
  ).has("expanded");
  const isExpanded = !showHeader || (states.processed ?? (hasManualOpenChild || automaticExpanded));

  return (
    <section className={showHeader ? "chat-msg__processed" : undefined}>
      {showHeader ? <button
        className="chat-msg__processed-toggle"
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setExpanded("processed", !isExpanded)}
      >
        <span className="chat-msg__processed-main">
          <span className="chat-msg__processed-caret" aria-hidden="true">
            {isExpanded ? (
              <CaretDown size={14} weight="bold" />
            ) : (
              <CaretRight size={14} weight="bold" />
            )}
          </span>
          <span>{isStreamingMessage ? "处理中" : "已处理"}</span>
        </span>
        {totalElapsedSeconds !== null ? (
          <span className="chat-msg__processed-timer">
            {formatElapsedSeconds(totalElapsedSeconds)}
          </span>
        ) : null}
      </button> : null}
      <SlidingContent expanded={isExpanded}>
        <div className={showHeader && items.length ? "chat-msg__processed-list" : undefined}>
          {items.map((item) =>
            renderAssistantProcessItem({
              clockTick,
              interactions,
              isStreamingMessage,
              item,
              foldKey: foldKeys.get(item.id),
              lastRunningThinkingId,
              message,
              resolveFoldExpanded,
              toggleFold,
            }),
          )}
        </div>
      </SlidingContent>
    </section>
  );
}

function resolveLatestAutoExpandedFoldId(items: AssistantProcessRenderItem[]) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.type === "content") {
      return null;
    }
    if (item.type === "thinking" || item.type === "tool_group") {
      return item.id;
    }
  }
  return null;
}

function AssistantContentProcessBlock({
  content,
  interactions,
  isStreaming,
}: {
  content: string;
  interactions: ChatMessageItemInteractions;
  isStreaming: boolean;
}) {
  return (
    <div className="chat-msg__markdown chat-msg__markdown--process">
      <LazyMarkdownPreview
        content={content}
        isStreaming={isStreaming}
        renderStrategy="responsive"
        mathErrorMode="neutral"
        localFileActions={interactions.localFileActions}
        onPreviewHtmlCode={interactions.onPreviewHtmlCode}
        onSaveCodeBlock={interactions.onSaveCodeBlock}
        resolveLocalFileReference={interactions.resolveLocalFileReference}
      />
    </div>
  );
}

function ThinkingProcessBlock({
  foldKey,
  clockTick,
  interactions,
  isExpanded,
  isLiveSegment,
  isStreaming,
  item,
  message,
  onToggleExpanded,
}: ThinkingProcessBlockProps) {
  const elapsedSeconds = resolveProcessElapsedSeconds(item, clockTick);

  return (
    <section className="chat-msg__thinking chat-msg__thinking--process">
      <div className="chat-msg__thinking-head">
        <button
          className="chat-msg__thinking-toggle"
          type="button"
          aria-expanded={isExpanded}
          onClick={onToggleExpanded}
        >
          <span aria-hidden="true">
            {isExpanded ? (
              <CaretDown size={14} weight="bold" />
            ) : (
              <CaretRight size={14} weight="bold" />
            )}
          </span>
          <span>Thinking......</span>
        </button>
        {elapsedSeconds !== null ? (
          <span className="chat-msg__thinking-timer">{elapsedSeconds}s</span>
        ) : null}
      </div>
      <ChatThinkingContent content={item.content} foldKey={foldKey} interactions={interactions}
        isExpanded={isExpanded} isLiveSegment={isLiveSegment} isStreaming={isStreaming} messageId={message.id} />
    </section>
  );
}

function resolveRenderItemsElapsedSeconds(
  items: AssistantProcessRenderItem[],
  clockTick: number,
) {
  const starts: number[] = [];
  const ends: number[] = [];
  let hasActiveItem = false;

  items.forEach((item) => {
    if (item.type === "thinking") {
      if (item.startedAt === null) return;
      starts.push(item.startedAt);
      if (item.finishedAt === null || item.status === "running") {
        hasActiveItem = true;
      } else {
        ends.push(item.finishedAt);
      }
      return;
    }
    if (item.type === "tool_group") {
      item.entries.forEach((entry) => {
        if (entry.type === "tool_preparing") {
          starts.push(entry.startedAt);
          hasActiveItem = true;
          return;
        }
        if (entry.tool.startedAt !== null) {
          starts.push(entry.tool.startedAt);
        }
        if (
          entry.tool.startedAt !== null &&
          (
            entry.tool.finishedAt === null ||
            entry.tool.status === "preparing" ||
            entry.tool.status === "running"
          )
        ) {
          hasActiveItem = true;
        } else if (entry.tool.finishedAt !== null) {
          ends.push(entry.tool.finishedAt);
        }
      });
    }
  });

  if (starts.length === 0) return null;
  const start = Math.min(...starts);
  const end = hasActiveItem
    ? clockTick
    : ends.length > 0
      ? Math.max(...ends)
      : start;
  if (!end || end < start) return null;
  return Math.max(0, Math.floor((end - start) / 1000));
}

import { useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import {
  findLastRunningThinkingId,
  resolveAssistantMessageElapsedSeconds,
  resolveProcessElapsedSeconds,
} from "../model/chatAssistantProcessTime";
import {
  useAssistantProcessAutoCollapse,
  type AssistantProcessArchiveMode,
} from "../model/useAssistantProcessAutoCollapse";
import { resolveAssistantBodyContent } from "../model/chatDisplayMessages";
import type {
  ChatAssistantProcessItem,
  ChatMessage,
} from "../model/chatMessage";
import type { ChatMessageItemInteractions } from "./chatMessageItemTypes";
import {
  formatElapsedSeconds,
  ToolProcessBlock,
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
  | Extract<ChatAssistantProcessItem, { type: "thinking" | "content" }>
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
};

type ThinkingProcessBlockProps = {
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
  const [manualFoldStates, setManualFoldStates] = useState<Record<string, boolean>>({});
  const items = message.processItems ?? EMPTY_PROCESS_ITEMS;
  const renderItems = useMemo(() => buildAssistantProcessRenderItems(items), [items]);
  const lastRunningThinkingId = useMemo(() => findLastRunningThinkingId(items), [items]);
  const hasTrailingBodyContent = useMemo(
    () => resolveAssistantBodyContent(message).trim().length > 0,
    [message],
  );
  const desiredArchiveMode = resolveAssistantProcessArchiveMode({
    autoCollapseProcess,
    isStreamingMessage,
  });
  const {
    archiveMode,
    processRegionRef,
  } = useAssistantProcessAutoCollapse(desiredArchiveMode);
  const partitionedItems = useMemo(() => (
    partitionAssistantProcessItems(renderItems, archiveMode)
  ), [
    archiveMode,
    renderItems,
  ]);
  const autoExpandedFoldId = useMemo(() => (
    isStreamingMessage && !hasTrailingBodyContent
      ? resolveLatestAutoExpandedFoldId(partitionedItems.visibleItems)
      : null
  ), [hasTrailingBodyContent, isStreamingMessage, partitionedItems.visibleItems]);
  const resolveFoldExpanded = (foldId: string) =>
    manualFoldStates[foldId] ?? autoExpandedFoldId === foldId;
  const toggleFold = (foldId: string, currentExpanded: boolean) => {
    setManualFoldStates((prev) => ({
      ...prev,
      [foldId]: !currentExpanded,
    }));
  };

  return (
    <section className="chat-msg__process" ref={processRegionRef}>
      {partitionedItems.archivedItems.length > 0 ? (
        <ProcessedProcessBlock
          clockTick={clockTick}
          interactions={interactions}
          isStreamingMessage={isStreamingMessage}
          items={partitionedItems.archivedItems}
          lastRunningThinkingId={lastRunningThinkingId}
          message={message}
          totalElapsedSeconds={
            resolveAssistantMessageElapsedSeconds(message, clockTick) ??
            resolveRenderItemsElapsedSeconds(partitionedItems.archivedItems, clockTick)
          }
        />
      ) : null}
      {partitionedItems.visibleItems.map((item) =>
        renderAssistantProcessItem({
          clockTick,
          interactions,
          isStreamingMessage,
          item,
          lastRunningThinkingId,
          message,
          resolveFoldExpanded,
          toggleFold,
        }),
      )}
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

function partitionAssistantProcessItems(
  items: AssistantProcessRenderItem[],
  archiveMode: AssistantProcessArchiveMode,
) {
  if (items.length === 0) {
    return { archivedItems: [], visibleItems: items };
  }

  if (archiveMode === "all") {
    return { archivedItems: items, visibleItems: [] };
  }

  if (archiveMode === "none" || items.length <= 1) {
    return { archivedItems: [], visibleItems: items };
  }

  return {
    archivedItems: items.slice(0, -1),
    visibleItems: items.slice(-1),
  };
}

function resolveAssistantProcessArchiveMode({
  autoCollapseProcess,
  isStreamingMessage,
}: {
  autoCollapseProcess: boolean;
  isStreamingMessage: boolean;
}): AssistantProcessArchiveMode {
  if (!autoCollapseProcess || isStreamingMessage) return "none";
  return "all";
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
}: RenderAssistantProcessItemOptions) {
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
      key={item.id}
      clockTick={clockTick}
      interactions={interactions}
      isExpanded={isExpanded}
      isLiveSegment={item.id === lastRunningThinkingId}
      isStreaming={isStreamingMessage && item.status === "running"}
      item={item}
      message={message}
      onToggleExpanded={() => toggleFold(item.id, isExpanded)}
    />
  );
}

function ProcessedProcessBlock({
  clockTick,
  interactions,
  isStreamingMessage,
  items,
  lastRunningThinkingId,
  message,
  totalElapsedSeconds,
}: {
  clockTick: number;
  interactions: ChatMessageItemInteractions;
  isStreamingMessage: boolean;
  items: AssistantProcessRenderItem[];
  lastRunningThinkingId: string | null;
  message: ChatMessage;
  totalElapsedSeconds: number | null;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [manualFoldStates, setManualFoldStates] = useState<Record<string, boolean>>({});
  const resolveFoldExpanded = (foldId: string) => manualFoldStates[foldId] ?? false;
  const toggleFold = (foldId: string, currentExpanded: boolean) => {
    setManualFoldStates((prev) => ({
      ...prev,
      [foldId]: !currentExpanded,
    }));
  };

  return (
    <section className="chat-msg__processed">
      <button
        className="chat-msg__processed-toggle"
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((value) => !value)}
      >
        <span className="chat-msg__processed-main">
          <span className="chat-msg__processed-caret" aria-hidden="true">
            {isExpanded ? (
              <CaretDown size={14} weight="bold" />
            ) : (
              <CaretRight size={14} weight="bold" />
            )}
          </span>
          <span>已处理</span>
        </span>
        {totalElapsedSeconds !== null ? (
          <span className="chat-msg__processed-timer">
            {formatElapsedSeconds(totalElapsedSeconds)}
          </span>
        ) : null}
      </button>
      {isExpanded ? (
        <div className="chat-msg__processed-list">
          {items.map((item) =>
            renderAssistantProcessItem({
              clockTick,
              interactions,
              isStreamingMessage,
              item,
              lastRunningThinkingId,
              message,
              resolveFoldExpanded,
              toggleFold,
            }),
          )}
        </div>
      ) : null}
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
      {isExpanded ? (
        <div
          ref={(node) => {
            if (isLiveSegment) {
              interactions.setThinkingContentRef(message.id, node);
            }
          }}
          className={[
            "chat-msg__thinking-content",
            isStreaming ? "chat-msg__thinking-content--streaming" : "",
          ].filter(Boolean).join(" ")}
          onScroll={() => interactions.onThinkingContentScroll(message.id)}
          onWheel={(event) =>
            interactions.onThinkingContentWheel(message.id, event)
          }
          onTouchMove={() => interactions.onTouchMoveThinkingContent(message.id)}
        >
          <LazyMarkdownPreview
            content={item.content}
            isStreaming={isStreaming}
            mathErrorMode="neutral"
            localFileActions={interactions.localFileActions}
            onPreviewHtmlCode={interactions.onPreviewHtmlCode}
            onSaveCodeBlock={interactions.onSaveCodeBlock}
            resolveLocalFileReference={interactions.resolveLocalFileReference}
          />
        </div>
      ) : null}
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

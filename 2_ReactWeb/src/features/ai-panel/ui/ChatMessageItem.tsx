import {
  CaretDown,
  CaretLeft,
  CaretRight,
  Check,
  Copy,
  DownloadSimple,
  ArrowsLeftRight,
  ArrowsClockwise,
  PencilSimple,
} from "@phosphor-icons/react";
import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import { Tooltip } from "../../../shared/ui/tooltip";
import { SlidingContent } from "../../../shared/ui/sliding-content/SlidingContent";
import { ReferencedUserMessageView } from "./ReferencedUserMessageView";
import { ChatThinkingContent } from "./ChatThinkingContent";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { resolveAssistantBodyContent } from "../model/chatDisplayMessages";
import { ChatProcessFoldScope, useAutomaticProcessFolds, useChatProcessFolds } from "../model/chatProcessFoldState";
import { ConversationEventNotice, RunFailureNotice, MemoryCompactionNotice } from "./ChatRunNotices";
import { createWorkspaceAssetUrl } from "../../document-editor-canvas/model/documentAssetUrls";
import {
  buildChatMessageClass,
  formatChatRetryNotice,
  readToolProcessItemFromMessage,
  resolveThinkingElapsedSeconds,
  type ChatMessage,
} from "../model/chatMessage";
import {
  buildReferencedUserMessage,
  resolveUserMessageContent,
  type ReferencedUserMessage,
  type UserMessageReferenceDisplay,
} from "../model/userMessageReferences";
import { formatTokenCount } from "../model/usageSummary";
import { formatChatMessageTimestamp } from "../model/chatMessageTimestamp";
import { AssistantProcessTimeline } from "./ChatAssistantProcessTimeline";
import {
  formatToolPayload,
  ToolProcessBlock,
  toolProcessEntriesFromTools,
} from "./ChatToolProcessBlock";
import type { ChatMessageItemInteractions } from "./chatMessageItemTypes";

export type { ChatMessageItemInteractions } from "./chatMessageItemTypes";

type ChatMessageItemProps = {
  autoCollapseAssistantProcess: boolean;
  clockTick: number;
  expandedUserMessageIds: Set<string>;
  interactions: ChatMessageItemInteractions;
  isLastMessage: boolean;
  isSessionStreaming: boolean;
  message: ChatMessage;
  modelSwitchModelId: string | null;
  foldTurnId: string;
  foldThinkingOffset: number;
};

export const ChatMessageItem = memo(function ChatMessageItem({
  autoCollapseAssistantProcess,
  clockTick,
  expandedUserMessageIds,
  interactions,
  isSessionStreaming,
  message,
  modelSwitchModelId,
  foldTurnId,
  foldThinkingOffset,
}: ChatMessageItemProps) {
  const isStreamingMessage =
    isSessionStreaming &&
    message.role === "assistant" &&
    message.status === "running";
  const referencedUserMessage = useMemo(
    () => message.role === "user" ? buildReferencedUserMessage(message) : null,
    [message.content, message.references, message.role],
  );
  const isUserMessageExpanded = expandedUserMessageIds.has(message.id);
  const isBodyStreaming =
    isStreamingMessage && message.content.trim().length > 0;
  const shouldRenderThinking = message.thinkingContent.trim().length > 0;
  const shouldRenderProcessTimeline = message.role === "assistant" && message.processItems !== undefined;
  const isThinkingStreaming =
    isStreamingMessage &&
    !isBodyStreaming &&
    message.isThinkingExpanded &&
    shouldRenderThinking;
  const thinkingElapsedSeconds = resolveThinkingElapsedSeconds(
    message,
    clockTick,
  );
  const hasAssistantBody = message.role === "assistant" && Boolean(resolveAssistantBodyContent(message).trim());
  const isMemoryCompactionStatus =
    message.role === "system" && message.name === "memory_compaction";

  return (
    <ChatProcessFoldScope turnId={foldTurnId} messageKey={message.displayKey ?? message.id} thinkingOffset={foldThinkingOffset}>
      {modelSwitchModelId ? <ModelSwitchNotice modelId={modelSwitchModelId} /> : null}
      {isMemoryCompactionStatus ? (
        <MemoryCompactionNotice message={message} />
      ) : message.role === "error" ? (
        <RunFailureNotice message={message} />
      ) : (
        <div
          className={buildChatMessageClass(message)}
          data-chat-message-id={message.id}
          data-chat-message-key={message.displayKey ?? message.id}
        >
          <SystemMessage message={message} />
          {shouldRenderProcessTimeline ? (
            <AssistantProcessTimeline
              autoCollapseProcess={autoCollapseAssistantProcess}
              clockTick={clockTick}
              interactions={interactions}
              isStreamingMessage={isStreamingMessage}
              message={message}
            />
          ) : shouldRenderThinking ? (
            <ThinkingBlock
              elapsedSeconds={thinkingElapsedSeconds}
              interactions={interactions}
              isStreaming={isThinkingStreaming}
              isStreamingMessage={isStreamingMessage}
              message={message}
            />
          ) : null}
          {!shouldRenderProcessTimeline && message.toolCalls && message.toolCalls.length > 0 ? (
            <ToolProcessBlock
              clockTick={clockTick}
              entries={toolProcessEntriesFromTools(message.toolCalls)}
            />
          ) : null}
          <MessageBody
            interactions={interactions}
            isBodyStreaming={isBodyStreaming}
            isSessionStreaming={isSessionStreaming}
            isUserMessageExpanded={isUserMessageExpanded}
            message={message}
            referencedUserMessage={referencedUserMessage}
          />
          <SlidingContent expanded={!isStreamingMessage} className="chat-msg__footer">
          <div className={hasAssistantBody ? "chat-msg__footer-content" : undefined}>
          <AssistantActions
            interactions={interactions}
            message={message}
          />
          {hasAssistantBody || message.usage ? (
            <div className="chat-msg__usage" aria-hidden={!message.usage || undefined}
              style={{ visibility: !message.usage ? "hidden" : undefined }}>
              {message.usage ? formatChatUsage(message.usage) : "\u00a0"}
            </div>
          ) : null}
          </div>
          </SlidingContent>
          {message.finishReason === "output_limit" ? <div className="chat-msg__usage">输出已截断</div> : null}
          {message.retryStatus ? <RetryNotice message={message} /> : null}
        </div>
      )}
    </ChatProcessFoldScope>
  );
}, areChatMessageItemPropsEqual);

function RetryNotice({ message }: { message: ChatMessage }) {
  if (!message.retryStatus) return null;
  const text = formatChatRetryNotice(message.retryStatus);
  return (
    <ConversationEventNotice
      className="chat-msg__upstream-retry"
      icon={<ArrowsClockwise size={12} weight="bold" aria-hidden="true" />}
      text={text}
      title={`${text}。${message.retryStatus.error}`}
    />
  );
}

function ModelSwitchNotice({ modelId }: { modelId: string }) {
  return (
    <ConversationEventNotice
      className="chat-msg__model-switch"
      icon={<ArrowsLeftRight size={12} weight="bold" aria-hidden="true" />}
      text={modelId}
      title={modelId}
    />
  );
}

function areChatMessageItemPropsEqual(
  previous: ChatMessageItemProps,
  next: ChatMessageItemProps,
) {
  const previousExpanded = previous.expandedUserMessageIds.has(previous.message.id);
  const nextExpanded = next.expandedUserMessageIds.has(next.message.id);
  const previousIsStreamingMessage =
    previous.isSessionStreaming &&
    previous.message.role === "assistant" &&
    previous.message.status === "running";
  const nextIsStreamingMessage =
    next.isSessionStreaming &&
    next.message.role === "assistant" &&
    next.message.status === "running";
  const needsClockTick =
    (next.message.processItems ?? []).some((item) =>
      item.type === "thinking" && item.status === "running" && item.startedAt !== null,
    ) ||
    (
      next.message.thinkingStartedAt !== null &&
      next.message.thinkingFinishedAt === null &&
      next.message.isThinkingExpanded
    ) ||
    messageHasActiveToolTimer(next.message);

  return (
    previous.message === next.message &&
    previous.foldTurnId === next.foldTurnId &&
    previous.foldThinkingOffset === next.foldThinkingOffset &&
    previous.interactions === next.interactions &&
    previous.isLastMessage === next.isLastMessage &&
    previous.autoCollapseAssistantProcess === next.autoCollapseAssistantProcess &&
    previous.modelSwitchModelId === next.modelSwitchModelId &&
    previousIsStreamingMessage === nextIsStreamingMessage &&
    previousExpanded === nextExpanded &&
    (!needsClockTick || previous.clockTick === next.clockTick)
  );
}

function SystemMessage({ message }: { message: ChatMessage }) {
  if (message.role !== "system") return null;
  return (
    <div className="chat-msg__system">
      <div className="chat-msg__system-label">System</div>
      <p className="chat-msg__text">{message.content}</p>
    </div>
  );
}

type ThinkingBlockProps = {
  elapsedSeconds: number | null;
  interactions: ChatMessageItemInteractions;
  isStreaming: boolean;
  isStreamingMessage: boolean;
  message: ChatMessage;
};

function ThinkingBlock({
  elapsedSeconds,
  interactions,
  isStreaming,
  isStreamingMessage,
  message,
}: ThinkingBlockProps) {
  const { states, setExpanded, thinkingOffset, allowAutomaticCollapse } = useChatProcessFolds();
  const automaticExpanded = useAutomaticProcessFolds(
    `legacy-thinking:${thinkingOffset}`, message.isThinkingExpanded ? "expanded" : null,
    isStreamingMessage, allowAutomaticCollapse,
  ).has("expanded");
  const foldKey = `thinking:${thinkingOffset}`;
  const expanded = states[foldKey] ?? automaticExpanded;
  return (
    <section className="chat-msg__thinking">
      <div className="chat-msg__thinking-head">
        <button
          className="chat-msg__thinking-toggle"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded(foldKey, !expanded)}
        >
          <span aria-hidden="true">
            {expanded ? (
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
      <ChatThinkingContent content={message.thinkingContent} foldKey={foldKey} interactions={interactions}
        isExpanded={expanded} isLiveSegment={isStreamingMessage} isStreaming={isStreaming} messageId={message.id} />
    </section>
  );
}

type MessageBodyProps = {
  interactions: ChatMessageItemInteractions;
  isBodyStreaming: boolean;
  isSessionStreaming: boolean;
  isUserMessageExpanded: boolean;
  message: ChatMessage;
  referencedUserMessage: ReferencedUserMessage | null;
};

function MessageBody({
  interactions,
  isBodyStreaming,
  isSessionStreaming,
  isUserMessageExpanded,
  message,
  referencedUserMessage,
}: MessageBodyProps) {
  if (message.role === "assistant" || message.role === "error") {
    const bodyContent = resolveAssistantBodyContent(message);
    const generatedImages = (message.contentParts ?? []).filter(
      (part) => part.type === "image_ref" || part.type === "image_url",
    );
    if (!bodyContent.trim() && generatedImages.length === 0) return null;
    return (
      <>
        {bodyContent.trim() ? (
          <div
            className={
              isBodyStreaming
                ? "chat-msg__markdown chat-msg__markdown--streaming"
                : "chat-msg__markdown"
            }
          >
            <LazyMarkdownPreview
              content={bodyContent}
              isStreaming={isBodyStreaming}
              renderStrategy="responsive"
              mathErrorMode="neutral"
              localFileActions={interactions.localFileActions}
              onPreviewHtmlCode={interactions.onPreviewHtmlCode}
              onSaveCodeBlock={interactions.onSaveCodeBlock}
              resolveLocalFileReference={interactions.resolveLocalFileReference}
            />
          </div>
        ) : null}
        {generatedImages.length > 0 ? (
          <div className="chat-msg__generated-images">
            {generatedImages.map((part, index) => {
              const source = resolveMessageImageSource(part, interactions.projectId);
              return source ? (
                <img
                  alt={part.type === "image_ref" ? part.image_ref.name ?? "生成图片" : "生成图片"}
                  className="chat-msg__generated-image"
                  key={`${message.id}-generated-image-${index}`}
                  loading="lazy"
                  src={source}
                />
              ) : null;
            })}
          </div>
        ) : null}
      </>
    );
  }

  if (message.role === "tool") {
    return <ToolMessageBody message={message} />;
  }

  return message.role === "user" ? (
    <UserMessageBody
      isExpanded={isUserMessageExpanded}
      isSessionStreaming={isSessionStreaming}
      interactions={interactions}
      message={message}
      onOpenReference={interactions.onOpenReference
        ? (reference) => {
          interactions.onOpenReference?.(reference.viewerPayload);
        }
        : undefined}
      referencedMessage={referencedUserMessage}
    />
  ) : null;
}

function resolveMessageImageSource(
  part: NonNullable<ChatMessage["contentParts"]>[number],
  projectId: string | null,
) {
  if (part.type === "image_url") return part.image_url.url;
  if (part.type !== "image_ref" || !projectId) return null;
  return createWorkspaceAssetUrl(
    { key: `project:${projectId}`, kind: "project", id: projectId },
    part.image_ref.path,
  );
}

function messageHasActiveToolTimer(message: ChatMessage) {
  const processItems = message.processItems ?? [];
  if (processItems.some((item) => {
    if (item.type === "tool_preparing") return true;
    if (item.type !== "tool") return false;
    return (
      item.tool.startedAt !== null &&
      item.tool.finishedAt === null &&
      (item.tool.status === "preparing" || item.tool.status === "running")
    );
  })) {
    return true;
  }

  return (message.toolCalls ?? []).some((item) =>
    item.startedAt !== null &&
    item.finishedAt === null &&
    (item.status === "preparing" || item.status === "running"),
  );
}

function ToolMessageBody({ message }: { message: ChatMessage }) {
  const detail = useMemo(() => readToolProcessItemFromMessage(message), [message]);
  if (!detail) return null;
  return (
    <div className="chat-msg__tool">
      <div className="chat-msg__tool-head">
        <span className="chat-msg__tool-name">{detail.name || "tool"}</span>
        <span
          className={[
            "chat-msg__tool-status",
            detail.ok === false ? "chat-msg__tool-status--error" : "",
            message.status === "running" ? "chat-msg__tool-status--running" : "",
          ].filter(Boolean).join(" ")}
        >
          {message.status === "running" ? "调用中" : detail.ok === false ? "失败" : "完成"}
        </span>
      </div>
      {detail.error ? (
        <div className="chat-msg__tool-error">{detail.error}</div>
      ) : null}
      {detail.arguments ? (
        <pre className="chat-msg__tool-pre">{formatToolPayload(detail.arguments)}</pre>
      ) : null}
    </div>
  );
}

type UserMessageBodyProps = {
  interactions: ChatMessageItemInteractions;
  isExpanded: boolean;
  isSessionStreaming: boolean;
  message: ChatMessage;
  onOpenReference?: (reference: UserMessageReferenceDisplay) => void;
  referencedMessage: ReferencedUserMessage | null;
};

function UserMessageBody({
  interactions,
  isExpanded,
  isSessionStreaming,
  message,
  onOpenReference,
  referencedMessage,
}: UserMessageBodyProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [canExpand, setCanExpand] = useState(false);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (!container || !content) return;
    // Measure natural content height independently of the expanded state.
    // Wrapping, references and font changes all affect this.
    const measure = () => {
      const limit = Number.parseFloat(getComputedStyle(container).getPropertyValue("--chat-user-message-preview-height"));
      setCanExpand(Number.isFinite(limit) && content.scrollHeight > limit);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(content);
    return () => observer.disconnect();
  }, [message.content, referencedMessage]);

  return (
    <>
      <SlidingContent expanded={isExpanded} collapsedHeight={112}
        ref={containerRef}
        className={[
          "chat-msg__user-content",
          isExpanded ? "chat-msg__user-content--expanded" : "",
        ].filter(Boolean).join(" ")}
      >
        <div ref={contentRef} className="chat-msg__user-content-inner">
          {referencedMessage ? (
            <ReferencedUserMessageView
              onOpenReference={onOpenReference}
              references={referencedMessage.references}
              userContent={referencedMessage.userContent}
            />
          ) : (
            <p className="chat-msg__text">{resolveUserMessageContent(message)}</p>
          )}
        </div>
      </SlidingContent>
      <UserActions canExpand={canExpand} interactions={interactions} isExpanded={isExpanded}
        isSessionStreaming={isSessionStreaming} message={message} />
    </>
  );
}

function UserMessageExpandButton({ isExpanded, onClick }: { isExpanded: boolean; onClick: () => void }) {
  return (
    <button
      className="chat-msg__expand-toggle"
      type="button"
      aria-label={isExpanded ? "收起用户消息" : "展开完整用户消息"}
      aria-expanded={isExpanded}
      title={isExpanded ? "收起" : "展开"}
      onClick={onClick}
    >
      <span
        className={isExpanded ? "chat-msg__expand-caret chat-msg__expand-caret--collapse" : "chat-msg__expand-caret"}
        aria-hidden="true"
      />
    </button>
  );
}


function AssistantActions({
  interactions,
  message,
}: {
  interactions: ChatMessageItemInteractions;
  message: ChatMessage;
}) {
  if (message.role !== "assistant") return null;
  const bodyContent = resolveAssistantBodyContent(message);
  const hasBodyContent = bodyContent.trim().length > 0;
  const hasExportContent = hasBodyContent || message.thinkingContent.trim().length > 0
    || Boolean(message.processItems?.length || message.toolCalls?.length || message.usage);

  return hasExportContent ? (
    <div className="chat-msg__actions" aria-label="消息操作">
      {hasBodyContent ? <CopyMessageButton label="复制回复" text={bodyContent} /> : null}
      <button
        className="chat-msg__action"
        type="button"
        aria-label="导出回复"
        title="导出回复"
        onClick={() => interactions.onExportAssistantMessage?.(message)}
      >
        <DownloadSimple size={14} weight="regular" aria-hidden="true" />
      </button>
    </div>
  ) : null;
}

function UserActions({
  canExpand,
  interactions,
  isExpanded,
  isSessionStreaming,
  message,
}: {
  canExpand: boolean;
  interactions: ChatMessageItemInteractions;
  isExpanded: boolean;
  isSessionStreaming: boolean;
  message: ChatMessage;
}) {
  if (message.role !== "user") return null;
  const sentAt = formatChatMessageTimestamp(message.createdAt);
  const showActions = message.status === "done";
  const variantNavigation = showActions ? interactions.getVariantNavigation?.(message) ?? null : null;
  if (!showActions && !sentAt && !canExpand) return null;
  return (
    <div className="chat-msg__user-actions" aria-label="用户消息操作">
      {sentAt ? <time className="chat-msg__timestamp" dateTime={sentAt.dateTime} title={`发送时间：${sentAt.label}`}>
        {sentAt.label}
      </time> : null}
      {canExpand ? <UserMessageExpandButton isExpanded={isExpanded}
        onClick={() => interactions.onToggleUserMessageExpanded(message.id)} /> : null}
      {showActions ? <div className="chat-msg__user-actions-end">
        <CopyMessageButton label="复制用户消息" text={resolveUserMessageContent(message)} />
        {interactions.onForkUserMessage ? (
          <Tooltip
            content={isSessionStreaming
              ? "当前会话正在执行任务，请等待任务完成或停止任务后，再编辑并创建分支。"
              : "编辑并创建分支"}
          >
            <span className="chat-msg__fork-action" data-disabled={isSessionStreaming}>
              <button
                className="chat-msg__action"
                type="button"
                aria-label="编辑并创建分支"
                disabled={isSessionStreaming}
                onClick={() => interactions.onForkUserMessage?.(message)}
              >
                <PencilSimple size={14} weight="regular" aria-hidden="true" />
              </button>
            </span>
          </Tooltip>
        ) : null}
        {variantNavigation ? (
          <div className="chat-msg__variant-switcher" aria-label="消息版本">
            <button className="chat-msg__variant-button" type="button" aria-label="上一个版本"
              title="上一个版本" onClick={variantNavigation.onPrevious}>
              <CaretLeft size={14} weight="bold" aria-hidden="true" />
            </button>
            <span>{variantNavigation.currentPosition}/{variantNavigation.count}</span>
            <button className="chat-msg__variant-button" type="button" aria-label="下一个版本"
              title="下一个版本" onClick={variantNavigation.onNext}>
              <CaretRight size={14} weight="bold" aria-hidden="true" />
            </button>
          </div>
        ) : null}
      </div> : null}
    </div>
  );
}

function CopyMessageButton({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
  }, []);

  const handleCopy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = window.setTimeout(() => {
        resetTimerRef.current = null;
        setCopied(false);
      }, 1200);
    }).catch(() => undefined);
  };

  return (
    <button
      className="chat-msg__action"
      type="button"
      aria-label={copied ? "已复制" : label}
      title={copied ? "已复制" : label}
      onClick={handleCopy}
    >
      {copied ? (
        <Check size={14} weight="bold" aria-hidden="true" />
      ) : (
        <Copy size={14} weight="regular" aria-hidden="true" />
      )}
    </button>
  );
}

function formatChatUsage(usage: ChatUsage) {
  const parts = [
    `Tokens ${formatTokenCount(usage.total_tokens)}`,
    `输入 ${formatTokenCount(usage.prompt_tokens)}`,
    `输出 ${formatTokenCount(usage.completion_tokens)}`,
  ];
  if (
    usage.prompt_cache_hit_tokens !== null &&
    usage.prompt_cache_hit_tokens !== undefined
  ) {
    parts.push(`命中 ${formatTokenCount(usage.prompt_cache_hit_tokens)}`);
  }
  if (
    usage.prompt_cache_miss_tokens !== null &&
    usage.prompt_cache_miss_tokens !== undefined
  ) {
    parts.push(`未命中 ${formatTokenCount(usage.prompt_cache_miss_tokens)}`);
  }
  return parts.join(" · ");
}

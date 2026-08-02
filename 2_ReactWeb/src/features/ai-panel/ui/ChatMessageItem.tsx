import {
  CaretDown,
  CaretLeft,
  CaretRight,
  Check,
  CheckCircle,
  Copy,
  DownloadSimple,
  File,
  Folder,
  ImageSquare,
  ArrowsLeftRight,
  ArrowsClockwise,
  PencilSimple,
  Quotes,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { resolveAssistantBodyContent } from "../model/chatDisplayMessages";
import { createWorkspaceAssetUrl } from "../../document-editor-canvas/model/documentAssetUrls";
import {
  buildChatMessageClass,
  readToolProcessItemFromMessage,
  resolveThinkingElapsedSeconds,
  shouldOfferUserMessageExpand,
  shouldOfferUserMessageExpandFromParts,
  type ChatMessage,
} from "../model/chatMessage";
import {
  buildReferencedUserMessage,
  resolveUserMessageContent,
  type ReferencedUserMessage,
  type UserMessageReferenceDisplay,
} from "../model/userMessageReferences";
import { formatTokenCount } from "../model/usageSummary";
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
};

export const ChatMessageItem = memo(function ChatMessageItem({
  autoCollapseAssistantProcess,
  clockTick,
  expandedUserMessageIds,
  interactions,
  isLastMessage,
  isSessionStreaming,
  message,
  modelSwitchModelId,
}: ChatMessageItemProps) {
  const isStreamingMessage =
    isSessionStreaming &&
    isLastMessage &&
    message.role === "assistant" &&
    message.status === "running";
  const referencedUserMessage = useMemo(
    () => message.role === "user" ? buildReferencedUserMessage(message) : null,
    [message.content, message.references, message.role],
  );
  const canExpandUserMessage = useMemo(() => (
    message.role === "user" && (
      referencedUserMessage
        ? shouldOfferReferencedUserMessageExpand(referencedUserMessage)
        : shouldOfferUserMessageExpand(message.content)
    )
  ), [message.content, message.role, referencedUserMessage]);
  const isUserMessageExpanded = expandedUserMessageIds.has(message.id);
  const isBodyStreaming =
    isStreamingMessage && message.content.trim().length > 0;
  const shouldRenderThinking =
    message.thinkingContent.trim().length > 0 ||
    (isStreamingMessage && !isBodyStreaming);
  const shouldRenderProcessTimeline =
    message.processItems !== undefined && message.processItems.length > 0;
  const isThinkingStreaming =
    isStreamingMessage &&
    !isBodyStreaming &&
    message.isThinkingExpanded &&
    shouldRenderThinking;
  const thinkingElapsedSeconds = resolveThinkingElapsedSeconds(
    message,
    clockTick,
  );
  const usageToRender = !isStreamingMessage ? message.usage : null;
  const isMemoryCompactionStatus =
    message.role === "system" && message.name === "memory_compaction";

  return (
    <>
      {modelSwitchModelId ? <ModelSwitchNotice modelId={modelSwitchModelId} /> : null}
      {isMemoryCompactionStatus ? (
        <MemoryCompactionNotice message={message} />
      ) : (
        <div
          className={buildChatMessageClass(message)}
          data-chat-message-id={message.id}
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
            canExpandUserMessage={canExpandUserMessage}
            interactions={interactions}
            isBodyStreaming={isBodyStreaming}
            isUserMessageExpanded={isUserMessageExpanded}
            message={message}
            referencedUserMessage={referencedUserMessage}
          />
          <AssistantActions
            interactions={interactions}
            isStreamingMessage={isStreamingMessage}
            message={message}
          />
          <UserActions
            interactions={interactions}
            isSessionStreaming={isSessionStreaming}
            message={message}
          />
          {usageToRender ? (
            <div className="chat-msg__usage">{formatChatUsage(usageToRender)}</div>
          ) : null}
        </div>
      )}
    </>
  );
}, areChatMessageItemPropsEqual);

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

function MemoryCompactionNotice({ message }: { message: ChatMessage }) {
  const variant = message.status === "error"
    ? "error"
    : message.status === "done"
      ? "done"
      : "running";
  const icon = variant === "error"
    ? <WarningCircle size={12} weight="fill" aria-hidden="true" />
    : variant === "done"
      ? <CheckCircle size={12} weight="fill" aria-hidden="true" />
      : <ArrowsClockwise size={12} weight="bold" aria-hidden="true" />;

  return (
    <ConversationEventNotice
      className={`chat-msg__memory-compaction chat-msg__memory-compaction--${variant}`}
      icon={icon}
      messageId={message.id}
      text={message.content}
    />
  );
}

type ConversationEventNoticeProps = {
  className?: string;
  icon: ReactNode;
  messageId?: string;
  text: string;
  title?: string;
};

function ConversationEventNotice({
  className = "",
  icon,
  messageId,
  text,
  title,
}: ConversationEventNoticeProps) {
  return (
    <div
      className={["chat-msg__event", className].filter(Boolean).join(" ")}
      data-chat-message-id={messageId}
      role="note"
      title={title}
    >
      <span className="chat-msg__event-label">
        {icon}
        <span>{text}</span>
      </span>
    </div>
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
    previous.isLastMessage &&
    previous.message.role === "assistant" &&
    previous.message.status === "running";
  const nextIsStreamingMessage =
    next.isSessionStreaming &&
    next.isLastMessage &&
    next.message.role === "assistant" &&
    next.message.status === "running";
  const needsClockTick =
    (
      next.message.thinkingStartedAt !== null &&
      next.message.thinkingFinishedAt === null &&
      next.message.isThinkingExpanded
    ) ||
    messageHasActiveToolTimer(next.message);

  return (
    previous.message === next.message &&
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
  message: ChatMessage;
};

function ThinkingBlock({
  elapsedSeconds,
  interactions,
  isStreaming,
  message,
}: ThinkingBlockProps) {
  return (
    <section className="chat-msg__thinking">
      <div className="chat-msg__thinking-head">
        <button
          className="chat-msg__thinking-toggle"
          type="button"
          onClick={() => interactions.onToggleThinking(message.id)}
        >
          <span aria-hidden="true">
            {message.isThinkingExpanded ? (
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
      <div
        ref={(node) => interactions.setThinkingContentRef(message.id, node)}
        className={[
          "chat-msg__thinking-content",
          isStreaming ? "chat-msg__thinking-content--streaming" : "",
          message.isThinkingExpanded ? "" : "chat-msg__thinking-content--collapsed",
        ].filter(Boolean).join(" ")}
        aria-hidden={!message.isThinkingExpanded}
        onScroll={() => interactions.onThinkingContentScroll(message.id)}
        onWheel={(event) =>
          interactions.onThinkingContentWheel(message.id, event)
        }
        onTouchMove={() => interactions.onTouchMoveThinkingContent(message.id)}
      >
        <LazyMarkdownPreview
          content={message.thinkingContent}
          isStreaming={isStreaming}
          onPreviewHtmlCode={interactions.onPreviewHtmlCode}
          onSaveCodeBlock={interactions.onSaveCodeBlock}
        />
      </div>
    </section>
  );
}

type MessageBodyProps = {
  canExpandUserMessage: boolean;
  interactions: ChatMessageItemInteractions;
  isBodyStreaming: boolean;
  isUserMessageExpanded: boolean;
  message: ChatMessage;
  referencedUserMessage: ReferencedUserMessage | null;
};

function MessageBody({
  canExpandUserMessage,
  interactions,
  isBodyStreaming,
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
              onPreviewHtmlCode={interactions.onPreviewHtmlCode}
              onSaveCodeBlock={interactions.onSaveCodeBlock}
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
      canExpand={canExpandUserMessage}
      isExpanded={isUserMessageExpanded}
      message={message}
      onToggleExpanded={interactions.onToggleUserMessageExpanded}
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
  canExpand: boolean;
  isExpanded: boolean;
  message: ChatMessage;
  onOpenReference?: (reference: UserMessageReferenceDisplay) => void;
  onToggleExpanded: (messageId: string) => void;
  referencedMessage: ReferencedUserMessage | null;
};

function UserMessageBody({
  canExpand,
  isExpanded,
  message,
  onOpenReference,
  onToggleExpanded,
  referencedMessage,
}: UserMessageBodyProps) {
  return (
    <div
      className={[
        "chat-msg__user-content",
        canExpand ? "chat-msg__user-content--limited" : "",
        isExpanded ? "chat-msg__user-content--expanded" : "",
      ].filter(Boolean).join(" ")}
    >
      {referencedMessage ? (
        <ReferencedUserMessageView
          onOpenReference={onOpenReference}
          references={referencedMessage.references}
          userContent={referencedMessage.userContent}
        />
      ) : (
        <p className="chat-msg__text">{resolveUserMessageContent(message)}</p>
      )}
      {canExpand ? (
        <button
          className="chat-msg__expand-overlay"
          type="button"
          aria-label={isExpanded ? "收起用户消息" : "展开完整用户消息"}
          title={isExpanded ? "收起" : "展开"}
          onClick={() => onToggleExpanded(message.id)}
        >
          <span
            className={
              isExpanded
                ? "chat-msg__expand-caret chat-msg__expand-caret--collapse"
                : "chat-msg__expand-caret"
            }
            aria-hidden="true"
          />
        </button>
      ) : null}
    </div>
  );
}

function shouldOfferReferencedUserMessageExpand(message: ReferencedUserMessage) {
  return shouldOfferUserMessageExpandFromParts([
    ...message.references.map((reference) =>
      [reference.title, reference.meta, reference.detail].filter(Boolean).join(" "),
    ),
    message.userContent,
  ]);
}

function ReferencedUserMessageView({
  onOpenReference,
  references,
  userContent,
}: {
  onOpenReference?: (reference: UserMessageReferenceDisplay) => void;
  references: UserMessageReferenceDisplay[];
  userContent: string;
}) {
  return (
    <>
      <section className="chat-msg__user-reference-panel" aria-label="用户引用内容">
        <div className="chat-msg__user-reference-head">引用 {references.length}</div>
        <div className="chat-msg__user-reference-list">
          {references.map((reference) => (
            <div className="chat-msg__user-reference" key={`${reference.index}-${reference.title}-${reference.meta}`}>
              <button
                className={onOpenReference
                  ? "chat-msg__user-reference-open"
                  : "chat-msg__user-reference-open chat-msg__user-reference-open--static"}
                disabled={!onOpenReference}
                title={onOpenReference ? "查看引用内容" : undefined}
                type="button"
                onClick={() => onOpenReference?.(reference)}
              >
                <span className="chat-msg__user-reference-index">No. {reference.index}</span>
                <span className="chat-msg__user-reference-icon" aria-hidden="true">
                  <UserReferenceIcon reference={reference} />
                </span>
                <div className="chat-msg__user-reference-body">
                  <div className="chat-msg__user-reference-main">
                    <strong title={reference.title}>{reference.title}</strong>
                    <span>{reference.meta}</span>
                  </div>
                  {reference.detail ? (
                    <div className="chat-msg__user-reference-detail" title={reference.detail}>
                      {reference.detail}
                    </div>
                  ) : null}
                </div>
              </button>
            </div>
          ))}
        </div>
      </section>
      {userContent.trim() ? (
        <p className="chat-msg__text chat-msg__user-reference-message">{userContent}</p>
      ) : null}
    </>
  );
}

function UserReferenceIcon({ reference }: { reference: UserMessageReferenceDisplay }) {
  if (reference.kind === "folder") return <Folder size={15} weight="bold" />;
  if (reference.kind === "text") return <Quotes size={15} weight="bold" />;
  if (reference.kind === "image" || reference.kind === "pdf" || reference.kind === "ppt" || reference.kind === "excel") {
    return <ImageSquare size={15} weight="bold" />;
  }
  return <File size={15} weight="bold" />;
}

function AssistantActions({
  interactions,
  isStreamingMessage,
  message,
}: {
  interactions: ChatMessageItemInteractions;
  isStreamingMessage: boolean;
  message: ChatMessage;
}) {
  return (message.role === "assistant" || message.role === "error") &&
    !isStreamingMessage &&
    message.content.trim().length > 0 ? (
    <div className="chat-msg__actions" aria-label="消息操作">
      <CopyMessageButton label="复制回复" text={message.content} />
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
  interactions,
  isSessionStreaming,
  message,
}: {
  interactions: ChatMessageItemInteractions;
  isSessionStreaming: boolean;
  message: ChatMessage;
}) {
  if (message.role !== "user" || message.status !== "done") return null;
  const variantNavigation = interactions.getVariantNavigation?.(message) ?? null;
  return (
    <div className="chat-msg__user-actions" aria-label="用户消息操作">
      <CopyMessageButton
        label="复制用户消息"
        text={resolveUserMessageContent(message)}
      />
      {interactions.onForkUserMessage ? (
        <button
          className="chat-msg__action"
          type="button"
          aria-label="编辑并创建分支"
          title="编辑并创建分支"
          disabled={isSessionStreaming}
          onClick={() => interactions.onForkUserMessage?.(message)}
        >
          <PencilSimple size={14} weight="regular" aria-hidden="true" />
        </button>
      ) : null}
      {variantNavigation ? (
        <div className="chat-msg__variant-switcher" aria-label="消息版本">
          <button
            className="chat-msg__variant-button"
            type="button"
            aria-label="上一个版本"
            title="上一个版本"
            onClick={variantNavigation.onPrevious}
          >
            <CaretLeft size={14} weight="bold" aria-hidden="true" />
          </button>
          <span>{variantNavigation.currentPosition}/{variantNavigation.count}</span>
          <button
            className="chat-msg__variant-button"
            type="button"
            aria-label="下一个版本"
            title="下一个版本"
            onClick={variantNavigation.onNext}
          >
            <CaretRight size={14} weight="bold" aria-hidden="true" />
          </button>
        </div>
      ) : null}
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

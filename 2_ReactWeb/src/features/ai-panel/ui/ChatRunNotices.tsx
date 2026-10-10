import type { ReactNode } from "react";
import { WarningCircle, CheckCircle, ArrowsClockwise } from "@phosphor-icons/react";
import { formatChatRunFailureNotice, type ChatMessage } from "../model/chatMessage";

export function RunFailureNotice({ message }: { message: ChatMessage }) {
  return (
    <ConversationEventNotice
      className="chat-msg__run-failure"
      icon={<WarningCircle size={12} weight="fill" aria-hidden="true" />}
      messageId={message.id}
      text={formatChatRunFailureNotice(message)}
    />
  );
}

export function ConversationEventNotice({
  className = "",
  icon,
  messageId,
  text,
  title,
}: {
  className?: string;
  icon: ReactNode;
  messageId?: string;
  text: string;
  title?: string;
}) {
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

export function MemoryCompactionNotice({ message }: { message: ChatMessage }) {
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


export function ChatNotificationNotice({ message }: { message: ChatMessage }) {
  return message.role === "error" ? <RunFailureNotice message={message} /> : <MemoryCompactionNotice message={message} />;
}

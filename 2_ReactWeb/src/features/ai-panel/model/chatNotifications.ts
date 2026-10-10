import { isChatNotificationMessage, type ChatMessage } from "./chatMessage";

/** Refresh persisted notices without replacing an in-progress stream snapshot. */
export function mergeLiveChatNotifications(current: ChatMessage[], persisted: ChatMessage[]) {
  const knownIds = new Set(current.map((message) => message.id));
  for (const message of current) {
    for (const item of message.processItems ?? []) {
      if (item.type === "notification" || item.type === "attempt_failure") knownIds.add(item.message.id);
    }
  }
  const active = [...current].reverse().find((message) => message.role === "assistant" && message.status === "running");
  const lastUser = [...current].reverse().find((message) => message.role === "user");
  const notices = persisted.filter((message) => {
    if (!isChatNotificationMessage(message) || knownIds.has(message.id)) return false;
    const userId = message.runAttemptFailure?.user_message_id ?? message.runOutcome?.user_message_id;
    // The active socket owns its attempt events. Their persisted IDs differ from
    // optimistic display IDs; merging them would show every failure twice.
    return !(active && userId && userId === lastUser?.id);
  });
  if (!notices.length) return current;
  const result = [...current];
  for (const notice of notices) {
    const sourceIndex = persisted.indexOf(notice);
    // Existing user boundaries are authoritative even if an async task finishes later.
    const nextUser = persisted.slice(sourceIndex + 1).find((message) => message.role === "user" && knownIds.has(message.id));
    const insertIndex = nextUser ? result.findIndex((message) => message.id === nextUser.id) : result.length;
    result.splice(insertIndex, 0, {
      ...notice,
      notificationPending: !nextUser && Boolean(active?.modelResponseInFlight),
    });
  }
  return result;
}

export function reuseChatMessageRevisions(current: ChatMessage[], persisted: ChatMessage[]) {
  const byId = new Map(current.map((message) => [message.id, message]));
  return persisted.map((message) => {
    const previous = byId.get(message.id);
    if (!previous || previous.notificationPending || previous.modelResponseInFlight) return message;
    return previous.updatedAt === message.updatedAt && previous.status === message.status
      && previous.role === message.role && previous.content === message.content
      && previous.thinkingContent === message.thinkingContent
      && JSON.stringify(previous.runOutcome) === JSON.stringify(message.runOutcome)
      ? previous : message;
  });
}

export function releasePendingChatNotifications(messages: ChatMessage[]) {
  let changed = false;
  const next = messages.map((message) => {
    if (!message.notificationPending) return message;
    changed = true;
    return { ...message, notificationPending: false };
  });
  return changed ? next : messages;
}

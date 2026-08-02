import type {
  ConversationMessageListResponse,
} from "../../../entities/llm-chat/model/conversation";

export type ConversationMessagePageLoader = (
  beforeMessageId: string | null,
) => Promise<ConversationMessageListResponse>;

/**
 * Iterates from the newest page towards older history. Every response is
 * validated before it is yielded, so consumers cannot satisfy a stop
 * condition with a repeated page or cursor.
 */
export async function* iterateBackwardConversationMessagePages(
  loadPage: ConversationMessagePageLoader,
): AsyncGenerator<ConversationMessageListResponse> {
  const guard = new BackwardMessagePageGuard();
  let beforeMessageId: string | null = null;

  while (true) {
    guard.startRequest(beforeMessageId);
    const page = await loadPage(beforeMessageId);
    guard.validateResponse(page, beforeMessageId);
    yield page;

    if (!page.has_more) return;
    beforeMessageId = page.next_before_message_id;
  }
}

class BackwardMessagePageGuard {
  private readonly messageIds = new Set<string>();
  private readonly pageFingerprints = new Set<string>();
  private readonly requestedCursors = new Set<string>();
  private readonly returnedCursors = new Set<string>();

  startRequest(cursor: string | null) {
    if (cursor === null) return;
    if (this.requestedCursors.has(cursor)) {
      throw new Error("会话消息分页返回了重复游标，已停止读取。");
    }
    this.requestedCursors.add(cursor);
  }

  validateResponse(
    page: ConversationMessageListResponse,
    requestCursor: string | null,
  ) {
    const pageMessageIds = page.items.map((message) => message.message_id);
    const fingerprint = JSON.stringify(pageMessageIds);
    if (this.pageFingerprints.has(fingerprint)) {
      throw new Error("会话消息分页返回了重复页面，已停止读取。");
    }
    this.pageFingerprints.add(fingerprint);

    const nextCursor = page.next_before_message_id;
    if (!page.has_more) {
      if (nextCursor !== null) {
        throw new Error("会话消息分页结束页携带了无效的后续游标。");
      }
    } else {
      if (page.items.length === 0 || !nextCursor) {
        throw new Error("会话消息分页声明仍有历史，但未返回可用游标。");
      }
      if (nextCursor !== page.items[0].message_id) {
        throw new Error("会话消息分页游标与页面边界不一致。");
      }
      if (
        nextCursor === requestCursor
        || this.requestedCursors.has(nextCursor)
        || this.returnedCursors.has(nextCursor)
      ) {
        throw new Error("会话消息分页返回了重复游标，已停止读取。");
      }
      this.returnedCursors.add(nextCursor);
    }

    for (const messageId of pageMessageIds) {
      if (!messageId || this.messageIds.has(messageId)) {
        throw new Error("会话消息分页返回了重复或无效的 message_id，已停止读取。");
      }
      this.messageIds.add(messageId);
    }
  }
}

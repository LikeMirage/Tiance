import type { ConversationMessageListResponse } from "../../../entities/llm-chat/model/conversation";

export class HistorySnapshotChangedError extends Error {}

/** Join a bounded tail to the last durable checkpoint before publishing it.
 * A long tool loop can span many pages; its live view is not a saved row.
 * Keep the tail's revision: an older-page read cannot acknowledge newer appends.
 */
export async function completeHistoryTail(
  tail: ConversationMessageListResponse,
  checkpointId: string | null,
  readOlder: (before: string) => Promise<ConversationMessageListResponse>,
  includeUser = false,
): Promise<ConversationMessageListResponse> {
  const pages = [tail];
  const cursors = new Set<string>();
  let oldest = tail;
  while ((checkpointId || includeUser) && oldest.has_more
    && !oldest.items.some((message) => checkpointId
      ? message.message_id === checkpointId : message.role === "user")) {
    const before = oldest.next_before_message_id;
    if (!before || cursors.has(before)) throw new Error("History cursor did not advance");
    cursors.add(before);
    const page = await readOlder(before);
    if ((page.reset_revision ?? 0) !== (tail.reset_revision ?? 0)) {
      throw new HistorySnapshotChangedError();
    }
    pages.push(page);
    oldest = page;
  }
  if (pages.length === 1) return tail;
  const chronological = pages.reverse();
  const items = [...new Map(chronological.flatMap((page) => page.items)
    .map((message) => [message.message_id, message])).values()];
  return {
    ...tail, items, count: items.length,
    has_more: oldest.has_more,
    next_before_message_id: oldest.next_before_message_id,
    run_outcomes: [...new Map(chronological.flatMap((page) => page.run_outcomes)
      .map((outcome) => [outcome.run_id, outcome])).values()],
    run_attempt_failures: [...new Map(chronological.flatMap((page) => page.run_attempt_failures)
      .map((failure) => [failure.event_id, failure])).values()],
  };
}

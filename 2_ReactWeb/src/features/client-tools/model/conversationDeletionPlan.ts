import { collectSessionAncestorIds } from "../../../entities/llm-chat/model/conversationSessionTree";
import {
  buildConversationSessionIndex, collectConversationDescendantIds, conversationSessionLocation,
  type ConversationSessionListData,
} from "./conversationSessionScope";

export function buildConversationDeletionPlan(
  response: ConversationSessionListData, args: Record<string, unknown>, callerSessionId: string | null,
) {
  const hasSingle = args.session_id !== undefined;
  const hasMultiple = args.session_ids !== undefined;
  if (hasSingle === hasMultiple) throw new Error("删除时 session_id 与 session_ids 必须且只能提供一个。");
  const raw = hasSingle ? [args.session_id] : args.session_ids;
  if (!Array.isArray(raw) || raw.length === 0 || raw.some((id) => typeof id !== "string" || !id.trim())) {
    throw new Error("删除目标必须是非空的会话 ID 或会话 ID 数组。");
  }
  if (args.include_descendants !== undefined && typeof args.include_descendants !== "boolean") {
    throw new Error("include_descendants 必须是布尔值。");
  }
  const targetIds = [...new Set((raw as string[]).map((id) => id.trim()))];
  const index = buildConversationSessionIndex(response);
  for (const id of targetIds) {
    if (!index.sessions.has(id)) throw new Error(`会话不存在：${id}`);
  }
  if (!callerSessionId || !index.sessions.has(callerSessionId)) {
    throw new Error("删除需要有效的调用会话，用于检查是否会中断本次工具调用。");
  }
  const includeDescendants = args.include_descendants === true;
  const selectedIds = new Set(targetIds);
  if (includeDescendants) {
    for (const id of collectConversationDescendantIds(index, targetIds)) selectedIds.add(id);
  }
  const protectedIds = [callerSessionId, ...collectSessionAncestorIds(callerSessionId, index.parentSessionIdBySession)];
  if (protectedIds.some((id) => selectedIds.has(id))) {
    throw new Error("不能删除当前调用会话或它的祖先会话，以免中断本次工具调用。");
  }
  const sessions = response.items.filter((session) => selectedIds.has(session.session_id)).map((session) => ({
    session_id: session.session_id, title: session.title,
    runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
    ...conversationSessionLocation(index, session.session_id),
  }));
  const reparented = [];
  for (const [id, previousParent] of index.parentSessionIdBySession) {
    if (selectedIds.has(id) || !selectedIds.has(previousParent)) continue;
    let parent: string | null = previousParent;
    while (parent && selectedIds.has(parent)) parent = index.parentSessionIdBySession.get(parent) ?? null;
    reparented.push({ session_id: id, title: index.sessions.get(id)!.title,
      previous_parent_session_id: previousParent, parent_session_id: parent });
  }
  return {
    target_session_ids: targetIds,
    include_descendants: includeDescendants,
    session_ids: sessions.map((session) => session.session_id),
    count: sessions.length, sessions,
    reparented_sessions: reparented,
  };
}

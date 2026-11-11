import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import {
  buildConversationSessionTree,
  collectSessionAncestorIds,
  type ConversationSessionLeafGroup,
} from "../../../entities/llm-chat/model/conversationSessionTree";
import type { ConversationSummaries } from "../../../services/project/getProjectConversationSummaries";

export type ConversationSessionListScope = "related" | "all" | "roots" | "children" | "descendants";
export type ConversationSessionListData = Pick<ConversationSummaries, "items" | "branch_nodes" | "session_states">;
const GROUP_NAMES: Record<ConversationSessionLeafGroup, string> = {
  child: "child", branch: "fork", automaticNaming: "automatic_naming",
  memoryCompaction: "memory_compaction", projectMemoryManagement: "project_memory_management",
  globalMemoryManagement: "global_memory_management",
};
export const SESSION_GROUPS = ["root", "child", "fork", "functional",
  "automatic_naming", "memory_compaction", "project_memory_management", "global_memory_management"] as const;

export function buildConversationSessionIndex(response: ConversationSessionListData) {
  // Use the same surviving parents, categories and sibling numbers as the UI.
  const tree = buildConversationSessionTree(response.items, response.branch_nodes);
  const children = new Map<string, string[]>();
  for (const [id, parent] of tree.parentSessionIdBySession) {
    const siblings = children.get(parent) ?? [];
    siblings.push(id);
    children.set(parent, siblings);
  }
  const depths = new Map<string, number>();
  const queue = tree.roots.map((node) => node.session.session_id);
  for (const id of queue) depths.set(id, 0);
  for (let i = 0; i < queue.length; i += 1) {
    for (const child of children.get(queue[i]) ?? []) {
      depths.set(child, (depths.get(queue[i]) ?? 0) + 1);
      queue.push(child);
    }
  }
  return {
    ...tree, children, depths,
    sessions: new Map(response.items.map((session) => [session.session_id, session])),
    relations: new Map(response.branch_nodes.filter((node) => node.deleted_at === null)
      .map((node) => [node.session_id, node])),
  };
}

export type ConversationSessionIndex = ReturnType<typeof buildConversationSessionIndex>;

export function conversationSessionLocation(index: ConversationSessionIndex, sessionId: string) {
  const relation = index.relations.get(sessionId);
  const group = index.parentGroupBySession.get(sessionId);
  return {
    parent_session_id: index.parentSessionIdBySession.get(sessionId) ?? null,
    group: group ? GROUP_NAMES[group] : "root",
    depth: index.depths.get(sessionId) ?? 0,
    display_number: index.displaySequenceBySession.get(sessionId) ?? null,
    relation_kind: relation?.relation_kind ?? "root",
    function_type: relation?.function_type ?? null,
    created_by: relation?.created_by ?? null,
    child_count: index.children.get(sessionId)?.length ?? 0,
  };
}

export function collectConversationDescendantIds(
  index: ConversationSessionIndex, sessionIds: readonly string[], maxDepth: number | null = null,
) {
  const visited = new Set(sessionIds);
  const descendants = new Set<string>();
  const queue = sessionIds.map((id) => ({ id, depth: 0 }));
  for (let i = 0; i < queue.length; i += 1) {
    const current = queue[i];
    if (maxDepth !== null && current.depth >= maxDepth) continue;
    for (const id of index.children.get(current.id) ?? []) {
      if (visited.has(id)) continue;
      visited.add(id);
      descendants.add(id);
      queue.push({ id, depth: current.depth + 1 });
    }
  }
  return descendants;
}

export function selectConversationSessions(
  response: ConversationSessionListData,
  anchorSessionId: string | null,
  scope: ConversationSessionListScope,
  relationDepth: number | null,
  index = buildConversationSessionIndex(response),
): ConversationSession[] {
  if (scope === "all") return response.items;
  if (scope === "roots") return response.items.filter((item) => !index.parentSessionIdBySession.has(item.session_id));
  if (!anchorSessionId || !index.sessions.has(anchorSessionId)) {
    throw new Error("需要当前项目内有效的会话 ID；可传 scope=all 查看项目全部会话。");
  }
  const ids = collectConversationDescendantIds(index, [anchorSessionId], scope === "children" ? 1 : relationDepth);
  if (scope === "related") {
    const ancestors = collectSessionAncestorIds(anchorSessionId, index.parentSessionIdBySession);
    for (const id of relationDepth === null ? ancestors : ancestors.slice(0, relationDepth)) ids.add(id);
  }
  return response.items.filter((session) => ids.has(session.session_id));
}

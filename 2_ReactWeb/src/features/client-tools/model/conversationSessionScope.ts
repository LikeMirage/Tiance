import type {
  ConversationBranchNode,
  ConversationSession,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";

export type ConversationSessionListScope = "related" | "all";

export function selectConversationSessions(
  response: ConversationSessionListResponse,
  callerSessionId: string | null,
  scope: ConversationSessionListScope,
  relationDepth: number | null,
): ConversationSession[] {
  if (scope === "all") return response.items;
  if (!callerSessionId) {
    throw new Error("按关联关系查看会话需要调用会话；可传 scope=all 查看项目全部会话。");
  }
  if (!response.items.some((session) => session.session_id === callerSessionId)) {
    throw new Error(`调用会话不存在：${callerSessionId}`);
  }

  const parentBySessionId = buildLiveParentMap(response);
  const childrenBySessionId = buildChildrenMap(parentBySessionId);
  const relatedIds = new Set<string>();

  collectAncestors(callerSessionId, relationDepth, parentBySessionId, relatedIds);
  collectDescendants(callerSessionId, relationDepth, childrenBySessionId, relatedIds);
  relatedIds.delete(callerSessionId);

  return response.items.filter((session) => relatedIds.has(session.session_id));
}

function buildLiveParentMap(
  response: ConversationSessionListResponse,
): ReadonlyMap<string, string> {
  const liveSessionIds = new Set(response.items.map((session) => session.session_id));
  const relationBySessionId = new Map(
    response.branch_nodes.map((relation) => [relation.session_id, relation]),
  );
  const parentBySessionId = new Map<string, string>();

  response.items.forEach((session) => {
    const relation = relationBySessionId.get(session.session_id);
    if (!relation || relation.deleted_at !== null) return;
    const parentSessionId = resolveNearestLiveParent(
      relation,
      relationBySessionId,
      liveSessionIds,
    );
    if (parentSessionId && parentSessionId !== session.session_id) {
      parentBySessionId.set(session.session_id, parentSessionId);
    }
  });

  return parentBySessionId;
}

function resolveNearestLiveParent(
  relation: ConversationBranchNode,
  relationBySessionId: ReadonlyMap<string, ConversationBranchNode>,
  liveSessionIds: ReadonlySet<string>,
): string | null {
  const visited = new Set<string>([relation.session_id]);
  let parentSessionId = relation.parent_session_id;

  while (parentSessionId && !visited.has(parentSessionId)) {
    visited.add(parentSessionId);
    const parentRelation = relationBySessionId.get(parentSessionId);
    if (liveSessionIds.has(parentSessionId) && parentRelation?.deleted_at === null) {
      return parentSessionId;
    }
    if (!parentRelation) return null;
    parentSessionId = parentRelation.parent_session_id;
  }

  return null;
}

function buildChildrenMap(
  parentBySessionId: ReadonlyMap<string, string>,
): ReadonlyMap<string, string[]> {
  const childrenBySessionId = new Map<string, string[]>();
  parentBySessionId.forEach((parentSessionId, sessionId) => {
    const children = childrenBySessionId.get(parentSessionId) ?? [];
    children.push(sessionId);
    childrenBySessionId.set(parentSessionId, children);
  });
  return childrenBySessionId;
}

function collectAncestors(
  callerSessionId: string,
  relationDepth: number | null,
  parentBySessionId: ReadonlyMap<string, string>,
  relatedIds: Set<string>,
) {
  const visited = new Set<string>([callerSessionId]);
  let currentSessionId = callerSessionId;
  let depth = 0;

  while (relationDepth === null || depth < relationDepth) {
    const parentSessionId = parentBySessionId.get(currentSessionId);
    if (!parentSessionId || visited.has(parentSessionId)) break;
    relatedIds.add(parentSessionId);
    visited.add(parentSessionId);
    currentSessionId = parentSessionId;
    depth += 1;
  }
}

function collectDescendants(
  callerSessionId: string,
  relationDepth: number | null,
  childrenBySessionId: ReadonlyMap<string, string[]>,
  relatedIds: Set<string>,
) {
  const visited = new Set<string>([callerSessionId]);
  const queue: Array<{ depth: number; sessionId: string }> = [
    { depth: 0, sessionId: callerSessionId },
  ];

  for (let queueIndex = 0; queueIndex < queue.length; queueIndex += 1) {
    const current = queue[queueIndex];
    if (relationDepth !== null && current.depth >= relationDepth) continue;
    for (const childSessionId of childrenBySessionId.get(current.sessionId) ?? []) {
      if (visited.has(childSessionId)) continue;
      visited.add(childSessionId);
      relatedIds.add(childSessionId);
      queue.push({ depth: current.depth + 1, sessionId: childSessionId });
    }
  }
}

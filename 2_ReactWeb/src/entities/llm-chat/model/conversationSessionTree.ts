import type { ConversationBranchNode, ConversationSession } from "./conversation";

// Display grouping is shared by the tree, chat header and usage list. It never
// writes to the API session object or uses expansion/pinning as an identity.
type SessionIdentity = Pick<ConversationSession, "session_id" | "created_at" | "sequence_number">;

export type ConversationSessionTreeNode<T extends SessionIdentity> = {
  session: T;
  displaySequence: number;
  childrenByGroup: Record<
    ConversationSessionLeafGroup,
    ConversationSessionTreeNode<T>[]
  >;
};

export type ConversationSessionTree<T extends SessionIdentity> = {
  roots: ConversationSessionTreeNode<T>[];
  displaySequenceBySession: ReadonlyMap<string, number>;
  parentSessionIdBySession: ReadonlyMap<string, string>;
  parentGroupBySession: ReadonlyMap<string, ConversationSessionLeafGroup>;
};

export type ConversationSessionGroup =
  | "branch"
  | "child"
  | "functional"
  | "automaticNaming"
  | "memoryCompaction"
  | "projectMemoryManagement"
  | "globalMemoryManagement";
export type ConversationSessionLeafGroup = Exclude<
  ConversationSessionGroup,
  "functional"
>;

export const CONVERSATION_SESSION_GROUPS = [
  "child",
  "branch",
] as const satisfies readonly ConversationSessionLeafGroup[];

export const CONVERSATION_FUNCTION_SESSION_GROUPS = [
  "automaticNaming",
  "memoryCompaction",
  "projectMemoryManagement",
  "globalMemoryManagement",
] as const satisfies readonly ConversationSessionLeafGroup[];

export function buildConversationSessionTree<T extends SessionIdentity>(
  sessions: readonly T[],
  relations: readonly ConversationBranchNode[],
): ConversationSessionTree<T> {
  const liveSessionIds = new Set(sessions.map((session) => session.session_id));
  const allRelationsBySessionId = new Map(
    relations.map((relation) => [relation.session_id, relation]),
  );
  const liveRelationsBySessionId = new Map(
    relations
      .filter((relation) => relation.deleted_at === null)
      .map((relation) => [relation.session_id, relation]),
  );
  const parentSessionIdBySession = new Map<string, string>();
  const parentGroupBySession = new Map<string, ConversationSessionLeafGroup>();

  sessions.forEach((session) => {
    const relation = liveRelationsBySessionId.get(session.session_id);
    const group = relation ? relationGroup(relation) : null;
    const parentSessionId = relation && group
      ? resolveNearestLiveParentSessionId(
          relation,
          allRelationsBySessionId,
          liveSessionIds,
        )
      : null;
    if (
      parentSessionId &&
      parentSessionId !== session.session_id &&
      group
    ) {
      parentSessionIdBySession.set(session.session_id, parentSessionId);
      parentGroupBySession.set(session.session_id, group);
    }
  });

  removeCyclicParentLinks(parentSessionIdBySession);

  const nodeBySessionId = new Map<string, ConversationSessionTreeNode<T>>(
    sessions.map((session) => [
      session.session_id,
      {
        session,
        displaySequence: 0,
        childrenByGroup: {
          branch: [],
          child: [],
          automaticNaming: [],
          globalMemoryManagement: [],
          memoryCompaction: [],
          projectMemoryManagement: [],
        },
      },
    ]),
  );
  const roots: ConversationSessionTreeNode<T>[] = [];

  sessions.forEach((session) => {
    const node = nodeBySessionId.get(session.session_id);
    if (!node) return;
    const parentSessionId = parentSessionIdBySession.get(session.session_id);
    const parent = parentSessionId
      ? nodeBySessionId.get(parentSessionId)
      : null;
    if (!parent) {
      roots.push(node);
      return;
    }
    const group = parentGroupBySession.get(session.session_id);
    if (!group) {
      roots.push(node);
      parentSessionIdBySession.delete(session.session_id);
      return;
    }
    parent.childrenByGroup[group].push(node);
  });

  // Each array is exactly one visible sibling group. Number chronologically,
  // but leave the supplied display order (newest first / pinned first) intact.
  const displaySequenceBySession = new Map<string, number>();
  const groups = [roots];
  for (const node of nodeBySessionId.values()) {
    groups.push(...Object.values(node.childrenByGroup));
  }
  for (const siblings of groups) {
    [...siblings].sort((left, right) =>
      Date.parse(left.session.created_at) - Date.parse(right.session.created_at)
      || left.session.sequence_number - right.session.sequence_number
      || left.session.session_id.localeCompare(right.session.session_id),
    ).forEach((node, index) => {
      node.displaySequence = index + 1;
      displaySequenceBySession.set(node.session.session_id, node.displaySequence);
    });
  }

  return {
    roots,
    displaySequenceBySession,
    parentSessionIdBySession,
    parentGroupBySession,
  };
}

export function collectSessionAncestorIds(
  sessionId: string,
  parentSessionIdBySession: ReadonlyMap<string, string>,
) {
  const ancestors: string[] = [];
  const visited = new Set([sessionId]);
  let current = parentSessionIdBySession.get(sessionId);
  while (current && !visited.has(current)) {
    ancestors.push(current);
    visited.add(current);
    current = parentSessionIdBySession.get(current);
  }
  return ancestors;
}

function resolveNearestLiveParentSessionId(
  relation: ConversationBranchNode,
  relationBySessionId: ReadonlyMap<string, ConversationBranchNode>,
  liveSessionIds: ReadonlySet<string>,
) {
  const visited = new Set<string>();
  let parentSessionId = relation.parent_session_id;
  while (parentSessionId && !visited.has(parentSessionId)) {
    visited.add(parentSessionId);
    const parent = relationBySessionId.get(parentSessionId);
    if (!parent) return null;
    if (parent.deleted_at === null && liveSessionIds.has(parent.session_id)) {
      return parent.session_id;
    }
    parentSessionId = parent.parent_session_id;
  }
  return null;
}

function relationGroup(
  relation: ConversationBranchNode,
): ConversationSessionLeafGroup | null {
  if (relation.relation_kind === "child") return "child";
  if (relation.relation_kind === "fork") return "branch";
  if (relation.relation_kind === "functional") {
    if (relation.function_type === "automatic_naming") {
      return "automaticNaming";
    }
    if (relation.function_type === "memory_compaction") {
      return "memoryCompaction";
    }
    if (relation.function_type === "project_memory_management") {
      return "projectMemoryManagement";
    }
    if (relation.function_type === "global_memory_management") {
      return "globalMemoryManagement";
    }
  }
  return null;
}

function removeCyclicParentLinks(parentSessionIdBySession: Map<string, string>) {
  for (const sessionId of parentSessionIdBySession.keys()) {
    const visited = new Set([sessionId]);
    let current = parentSessionIdBySession.get(sessionId);
    while (current) {
      if (visited.has(current)) {
        parentSessionIdBySession.delete(sessionId);
        break;
      }
      visited.add(current);
      current = parentSessionIdBySession.get(current);
    }
  }
}

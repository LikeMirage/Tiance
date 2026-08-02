import type { ConversationBranchNode } from "../../../entities/llm-chat/model/conversation";
import type { ProjectOverviewSessionWithDisplayUsage } from "./projectOverviewUsage";

export type ProjectOverviewSessionTreeNode = {
  session: ProjectOverviewSessionWithDisplayUsage;
  childrenByGroup: Record<
    ProjectOverviewSessionLeafGroup,
    ProjectOverviewSessionTreeNode[]
  >;
};

export type ProjectOverviewSessionTree = {
  roots: ProjectOverviewSessionTreeNode[];
  parentSessionIdBySession: ReadonlyMap<string, string>;
  parentGroupBySession: ReadonlyMap<string, ProjectOverviewSessionLeafGroup>;
};

export type ProjectOverviewSessionGroup =
  | "branch"
  | "child"
  | "functional"
  | "automaticNaming"
  | "memoryCompaction"
  | "projectMemoryManagement"
  | "globalMemoryManagement";
export type ProjectOverviewSessionLeafGroup = Exclude<
  ProjectOverviewSessionGroup,
  "functional"
>;

export const PROJECT_OVERVIEW_SESSION_GROUPS = [
  "child",
  "branch",
] as const satisfies readonly ProjectOverviewSessionLeafGroup[];

export const PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS = [
  "automaticNaming",
  "memoryCompaction",
  "projectMemoryManagement",
  "globalMemoryManagement",
] as const satisfies readonly ProjectOverviewSessionLeafGroup[];

export function buildProjectOverviewSessionTree(
  sessions: ProjectOverviewSessionWithDisplayUsage[],
  relations: ConversationBranchNode[],
): ProjectOverviewSessionTree {
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
  const parentGroupBySession = new Map<string, ProjectOverviewSessionLeafGroup>();

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

  const nodeBySessionId = new Map<string, ProjectOverviewSessionTreeNode>(
    sessions.map((session) => [
      session.session_id,
      {
        session,
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
  const roots: ProjectOverviewSessionTreeNode[] = [];

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

  return {
    roots,
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
): ProjectOverviewSessionLeafGroup | null {
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

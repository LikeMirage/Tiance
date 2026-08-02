import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

import type {
  ConversationBranchTurnEdge,
  ConversationBranchTurnNode,
} from "../../../entities/llm-chat/model/conversation";

export const BRANCH_NODE_WIDTH = 260;
export const BRANCH_NODE_HEIGHT = 118;

export type ConversationBranchFlowNodeData = {
  activeSessionId: string | null;
  insight: ConversationBranchNodeInsight;
  isSelected: boolean;
  onExport: (turn: ConversationBranchTurnNode) => void;
  onFocusBranchPoint: (point: ConversationBranchPoint) => void;
  onSelect: (turn: ConversationBranchTurnNode) => void;
  turn: ConversationBranchTurnNode;
};

export type ConversationBranchFlowNode = Node<ConversationBranchFlowNodeData, "conversationTurn">;

export type ConversationBranchPoint = {
  id: string;
  nodeIds: string[];
  preview: string;
  variantCount: number;
};

export type ConversationBranchNodeInsight = {
  depth: number;
  downstreamBranchPoints: ConversationBranchPoint[];
};

export function resolveConversationBranchTarget(
  turn: ConversationBranchTurnNode,
  activeSessionId: string | null,
) {
  return turn.targets.find((target) => target.session_id === activeSessionId)
    ?? turn.targets[0]
    ?? null;
}

type ConversationBranchLayoutOptions = {
  insights?: ReadonlyMap<string, ConversationBranchNodeInsight>;
  onExport?: (turn: ConversationBranchTurnNode) => void;
  onFocusBranchPoint?: (point: ConversationBranchPoint) => void;
  selectedTurnNodeId?: string | null;
};

export function getConversationBranchPoints(
  turns: ConversationBranchTurnNode[],
): ConversationBranchPoint[] {
  const groups = new Map<string, ConversationBranchTurnNode[]>();
  turns.forEach((turn) => {
    const group = groups.get(turn.variant_group_id) ?? [];
    group.push(turn);
    groups.set(turn.variant_group_id, group);
  });

  return [...groups.entries()]
    .filter(([, variants]) => variants.length > 1)
    .map(([id, variants]) => ({
      id,
      nodeIds: variants.map((variant) => variant.node_id),
      preview: variants.find((variant) => variant.variant_index === 1)?.user_preview
        ?? variants[0]?.user_preview
        ?? "空消息",
      variantCount: variants.length,
    }));
}

export function buildConversationBranchNodeInsights(
  turns: ConversationBranchTurnNode[],
  turnEdges: ConversationBranchTurnEdge[],
): Map<string, ConversationBranchNodeInsight> {
  const turnsById = new Map(turns.map((turn) => [turn.node_id, turn]));
  const outgoing = new Map(turns.map((turn) => [turn.node_id, [] as string[]]));
  const indegree = new Map(turns.map((turn) => [turn.node_id, 0]));
  turnEdges.forEach((edge) => {
    if (!turnsById.has(edge.source_node_id) || !turnsById.has(edge.target_node_id)) return;
    outgoing.get(edge.source_node_id)?.push(edge.target_node_id);
    indegree.set(edge.target_node_id, (indegree.get(edge.target_node_id) ?? 0) + 1);
  });

  const depth = new Map(turns.map((turn) => [turn.node_id, 1]));
  const queue = turns
    .filter((turn) => (indegree.get(turn.node_id) ?? 0) === 0)
    .map((turn) => turn.node_id);
  const topologicalOrder: string[] = [];
  for (let queueIndex = 0; queueIndex < queue.length; queueIndex += 1) {
    const nodeId = queue[queueIndex];
    topologicalOrder.push(nodeId);
    for (const childId of outgoing.get(nodeId) ?? []) {
      depth.set(childId, Math.max(depth.get(childId) ?? 1, (depth.get(nodeId) ?? 1) + 1));
      const nextIndegree = (indegree.get(childId) ?? 1) - 1;
      indegree.set(childId, nextIndegree);
      if (nextIndegree === 0) queue.push(childId);
    }
  }
  const orderedNodeIds = new Set(topologicalOrder);
  turns.forEach((turn) => {
    if (!orderedNodeIds.has(turn.node_id)) topologicalOrder.push(turn.node_id);
  });

  const branchPoints = getConversationBranchPoints(turns);
  const branchPointById = new Map(branchPoints.map((point) => [point.id, point]));
  const branchPointOrder = new Map(branchPoints.map((point, index) => [point.id, index]));
  const downstreamPointIds = new Map<string, Set<string>>();
  [...topologicalOrder].reverse().forEach((nodeId) => {
    const pointIds = new Set<string>();
    for (const childId of outgoing.get(nodeId) ?? []) {
      const child = turnsById.get(childId);
      if (child && branchPointById.has(child.variant_group_id)) {
        pointIds.add(child.variant_group_id);
      }
      downstreamPointIds.get(childId)?.forEach((pointId) => pointIds.add(pointId));
    }
    downstreamPointIds.set(nodeId, pointIds);
  });

  return new Map(turns.map((turn) => [
    turn.node_id,
    {
      depth: depth.get(turn.node_id) ?? 1,
      downstreamBranchPoints: [...(downstreamPointIds.get(turn.node_id) ?? [])]
        .sort((left, right) => (
          (branchPointOrder.get(left) ?? Number.MAX_SAFE_INTEGER) -
          (branchPointOrder.get(right) ?? Number.MAX_SAFE_INTEGER)
        ))
        .map((pointId) => branchPointById.get(pointId))
        .filter((point): point is ConversationBranchPoint => point !== undefined),
    },
  ]));
}

export function layoutConversationBranchGraph(
  turns: ConversationBranchTurnNode[],
  turnEdges: ConversationBranchTurnEdge[],
  activeSessionId: string | null,
  onSelect: (turn: ConversationBranchTurnNode) => void,
  options: ConversationBranchLayoutOptions = {},
): { nodes: ConversationBranchFlowNode[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: "LR",
    ranksep: 86,
    nodesep: 32,
    marginx: 34,
    marginy: 34,
  });
  turns.forEach((turn) => {
    graph.setNode(turn.node_id, { width: BRANCH_NODE_WIDTH, height: BRANCH_NODE_HEIGHT });
  });
  turnEdges.forEach((edge) => graph.setEdge(edge.source_node_id, edge.target_node_id));
  dagre.layout(graph);
  const activePathNodeIds = new Set(
    turns
      .filter((turn) => turn.targets.some((target) => target.session_id === activeSessionId))
      .map((turn) => turn.node_id),
  );

  return {
    nodes: turns.map((turn) => {
      const point = graph.node(turn.node_id) as { x: number; y: number };
      return {
        id: turn.node_id,
        type: "conversationTurn",
        position: {
          x: point.x - BRANCH_NODE_WIDTH / 2,
          y: point.y - BRANCH_NODE_HEIGHT / 2,
        },
        data: {
          activeSessionId,
          insight: options.insights?.get(turn.node_id) ?? {
            depth: 1,
            downstreamBranchPoints: [],
          },
          isSelected: options.selectedTurnNodeId === turn.node_id,
          onExport: options.onExport ?? (() => undefined),
          onFocusBranchPoint: options.onFocusBranchPoint ?? (() => undefined),
          onSelect,
          turn,
        },
        selectable: true,
        draggable: false,
      };
    }),
    edges: turnEdges.map((edge) => ({
      id: `${edge.source_node_id}:${edge.target_node_id}`,
      source: edge.source_node_id,
      target: edge.target_node_id,
      type: "smoothstep",
      className: activePathNodeIds.has(edge.source_node_id) && activePathNodeIds.has(edge.target_node_id)
        ? "conversation-branch-edge--active-path"
        : undefined,
    })),
  };
}

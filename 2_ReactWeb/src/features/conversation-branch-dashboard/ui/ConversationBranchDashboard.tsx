import { ArrowClockwise, GitBranch, ListDashes } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { ConversationBranchTurnNode } from "../../../entities/llm-chat/model/conversation";
import type { ConversationExportRequest } from "../../conversation-export/model/conversationExport";
import { ConversationExportDialog } from "../../conversation-export/ui/ConversationExportDialog";
import {
  BRANCH_NODE_HEIGHT,
  BRANCH_NODE_WIDTH,
  buildConversationBranchNodeInsights,
  getConversationBranchPoints,
  layoutConversationBranchGraph,
  resolveConversationBranchTarget,
  type ConversationBranchPoint,
  type ConversationBranchFlowNode,
} from "../model/conversationBranchLayout";
import { useConversationBranchDashboard } from "../model/useConversationBranchDashboard";
import { ConversationBranchPointList } from "./ConversationBranchPointList";
import { ConversationBranchTurnCard } from "./ConversationBranchTurnCard";
import { ConversationBranchZoomControl } from "./ConversationBranchZoomControl";
import "./conversation-branch-dashboard.css";

const nodeTypes: NodeTypes = {
  conversationTurn: ConversationBranchTurnCard,
};

type ConversationBranchDashboardProps = {
  activeMessageId: string | null;
  activeSessionId: string | null;
  isActive?: boolean;
  onSelectMessage?: (sessionId: string, messageId: string) => void;
  onSelectExportDirectory?: () => Promise<string | null>;
  projectId: string | null;
  projectRootPath: string;
};

export function ConversationBranchDashboard({
  activeMessageId,
  activeSessionId,
  isActive = true,
  onSelectMessage,
  onSelectExportDirectory,
  projectId,
  projectRootPath,
}: ConversationBranchDashboardProps) {
  const flowInstanceRef = useRef<ReactFlowInstance<ConversationBranchFlowNode> | null>(null);
  const [activePointId, setActivePointId] = useState<string | null>(null);
  const [exportRequest, setExportRequest] = useState<ConversationExportRequest | null>(null);
  const [pendingTurnSelection, setPendingTurnSelection] = useState<{
    messageId: string;
    nodeId: string;
    sessionId: string;
  } | null>(null);
  const {
    detail,
    detailError,
    groups,
    groupsError,
    isLoadingDetail,
    isLoadingGroups,
    refresh,
    selectedGroupId,
    selectGroup,
  } = useConversationBranchDashboard(projectId, activeSessionId, isActive);

  const branchPoints = useMemo(
    () => getConversationBranchPoints(detail?.nodes ?? []),
    [detail?.nodes],
  );
  const branchInsights = useMemo(
    () => buildConversationBranchNodeInsights(detail?.nodes ?? [], detail?.edges ?? []),
    [detail?.edges, detail?.nodes],
  );
  const activeTurnNodeId = useMemo(() => detail?.nodes.find((turn) =>
    turn.targets.some((target) => target.message_id === activeMessageId)
  )?.node_id ?? null, [activeMessageId, detail?.nodes]);
  useEffect(() => {
    if (!pendingTurnSelection) return;
    if (
      activeSessionId === pendingTurnSelection.sessionId &&
      activeMessageId === pendingTurnSelection.messageId
    ) {
      setPendingTurnSelection(null);
    }
  }, [activeMessageId, activeSessionId, pendingTurnSelection]);
  useEffect(() => {
    if (
      pendingTurnSelection &&
      detail &&
      !detail.nodes.some((turn) => turn.node_id === pendingTurnSelection.nodeId)
    ) {
      setPendingTurnSelection(null);
    }
  }, [detail, pendingTurnSelection]);
  const focusBranchPoint = useCallback((point: ConversationBranchPoint) => {
    const instance = flowInstanceRef.current;
    if (!instance) return;
    const pointNodes = point.nodeIds.flatMap((nodeId) => {
      const node = instance.getNode(nodeId);
      return node ? [node] : [];
    });
    if (pointNodes.length === 0) return;
    const left = Math.min(...pointNodes.map((node) => node.position.x));
    const right = Math.max(...pointNodes.map((node) => node.position.x + BRANCH_NODE_WIDTH));
    const top = Math.min(...pointNodes.map((node) => node.position.y));
    const bottom = Math.max(...pointNodes.map((node) => node.position.y + BRANCH_NODE_HEIGHT));
    setActivePointId(point.id);
    void instance.setCenter((left + right) / 2, (top + bottom) / 2, {
      zoom: Math.max(instance.getZoom(), 0.72),
      duration: 320,
    });
  }, []);
  const selectTurn = useCallback((turn: ConversationBranchTurnNode) => {
    const target = resolveConversationBranchTarget(turn, activeSessionId);
    if (!target) return;
    setPendingTurnSelection({
      messageId: target.message_id,
      nodeId: turn.node_id,
      sessionId: target.session_id,
    });
    onSelectMessage?.(target.session_id, target.message_id);
  }, [activeSessionId, onSelectMessage]);
  const exportTurn = useCallback((turn: ConversationBranchTurnNode) => {
    const target = resolveConversationBranchTarget(turn, activeSessionId);
    if (!detail || !projectId || !target) return;
    setExportRequest({
      initialDirectory: projectRootPath,
      messageId: target.message_id,
      projectId,
      scope: "message",
      sessionId: target.session_id,
      sessionTitle: detail.group.title,
    });
  }, [activeSessionId, detail, projectId, projectRootPath]);
  const graph = useMemo(() => layoutConversationBranchGraph(
    detail?.nodes ?? [],
    detail?.edges ?? [],
    activeSessionId,
    selectTurn,
    {
      insights: branchInsights,
      onExport: exportTurn,
      onFocusBranchPoint: focusBranchPoint,
      selectedTurnNodeId: pendingTurnSelection?.nodeId ?? activeTurnNodeId,
    },
  ), [
    activeSessionId,
    activeTurnNodeId,
    branchInsights,
    detail?.edges,
    detail?.nodes,
    exportTurn,
    focusBranchPoint,
    pendingTurnSelection?.nodeId,
    selectTurn,
  ]);

  if (!projectId) {
    return <div className="conversation-branch-dashboard__empty">当前没有可查看的项目。</div>;
  }

  return (
    <section className="conversation-branch-dashboard" aria-label="会话分支">
      <header className="conversation-branch-dashboard__header">
        <div className="conversation-branch-dashboard__tabs" role="tablist" aria-label="分支组">
          {groups.map((group) => (
            <button
              className={group.group_id === selectedGroupId
                ? "conversation-branch-dashboard__tab conversation-branch-dashboard__tab--active"
                : "conversation-branch-dashboard__tab"}
              type="button"
              role="tab"
              aria-selected={group.group_id === selectedGroupId}
              title={group.title}
              onClick={() => selectGroup(group.group_id)}
              key={group.group_id}
            >
              {group.is_branched
                ? <GitBranch size={14} weight="regular" aria-hidden="true" />
                : <ListDashes size={14} weight="regular" aria-hidden="true" />}
              <span>{group.title}</span>
              {group.session_ids.length > 1 ? <small>{group.session_ids.length}</small> : null}
            </button>
          ))}
        </div>
        <button
          className="conversation-branch-dashboard__refresh"
          type="button"
          aria-label="刷新会话分支"
          title="刷新会话分支"
          disabled={isLoadingGroups || isLoadingDetail}
          onClick={refresh}
        >
          <ArrowClockwise size={16} weight="regular" aria-hidden="true" />
        </button>
      </header>

      {groupsError || detailError ? (
        <div className="conversation-branch-dashboard__state conversation-branch-dashboard__state--error" role="status">
          <span>{groupsError || detailError}</span>
          <button type="button" onClick={refresh}>重试</button>
        </div>
      ) : isLoadingGroups || (isLoadingDetail && !detail) ? (
        <div className="conversation-branch-dashboard__state">正在加载会话分支...</div>
      ) : groups.length === 0 ? (
        <div className="conversation-branch-dashboard__state">当前项目还没有会话。</div>
      ) : !detail || detail.nodes.length === 0 ? (
        <div className="conversation-branch-dashboard__state">这个会话还没有已发送的用户消息。</div>
      ) : (
        <div className="conversation-branch-dashboard__canvas">
          <ReactFlow
            edges={graph.edges}
            fitView
            fitViewOptions={{ maxZoom: 1, minZoom: 0.15, padding: 0.18 }}
            maxZoom={1.5}
            minZoom={0.15}
            nodes={graph.nodes}
            nodeTypes={nodeTypes}
            nodesConnectable={false}
            nodesDraggable={false}
            onInit={(instance) => {
              flowInstanceRef.current = instance;
            }}
            onlyRenderVisibleElements
            panOnScroll
            proOptions={{ hideAttribution: true }}
            zoomActivationKeyCode="Control"
            zoomOnDoubleClick={false}
          >
            <ConversationBranchZoomControl minZoom={0.15} maxZoom={1.5} />
          </ReactFlow>
          <ConversationBranchPointList
            activePointId={activePointId}
            onSelect={focusBranchPoint}
            points={branchPoints}
          />
        </div>
      )}
      {exportRequest ? (
        <ConversationExportDialog
          key={`${exportRequest.sessionId}:${exportRequest.messageId}`}
          request={exportRequest}
          onClose={() => setExportRequest(null)}
          onSelectDirectory={onSelectExportDirectory ?? (async () => null)}
        />
      ) : null}
    </section>
  );
}

import { useCallback, useRef, useState } from "react";

export function useFileWorkspaceBrowserSelection() {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const selectedNodeIdsRef = useRef<Set<string>>(new Set());

  const commitSelection = useCallback((
    nextSelectedNodeId: string | null,
    nextSelectedNodeIds: Set<string>,
  ) => {
    selectedNodeIdsRef.current = nextSelectedNodeIds;
    setSelectedNodeId(nextSelectedNodeId);
    setSelectedNodeIds(new Set(nextSelectedNodeIds));
  }, []);

  const resetSelection = useCallback(() => {
    commitSelection(null, new Set());
  }, [commitSelection]);

  const selectRoot = useCallback(() => {
    commitSelection(null, new Set());
  }, [commitSelection]);

  const selectNode = useCallback((nodeId: string, options: { toggle?: boolean } = {}) => {
    if (!options.toggle) {
      commitSelection(nodeId, new Set([nodeId]));
      return;
    }

    const nextSelectedNodeIds = new Set(selectedNodeIdsRef.current);
    if (nextSelectedNodeIds.has(nodeId)) {
      nextSelectedNodeIds.delete(nodeId);
    } else {
      nextSelectedNodeIds.add(nodeId);
    }

    const nextSelectedNodeId = nextSelectedNodeIds.has(nodeId)
      ? nodeId
      : nextSelectedNodeIds.values().next().value ?? null;
    commitSelection(nextSelectedNodeId, nextSelectedNodeIds);
  }, [commitSelection]);

  return {
    commitSelection,
    resetSelection,
    selectRoot,
    selectedNodeId,
    selectedNodeIds,
    selectedNodeIdsRef,
    selectNode,
  };
}

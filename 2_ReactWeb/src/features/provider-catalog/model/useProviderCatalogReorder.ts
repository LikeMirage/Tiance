import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";

import { useReorderListAnimation } from "../../../shared/model/reorder-list-animation/useReorderListAnimation";
import type { ProviderInsertPosition, UseProviderCatalogResult } from "./useProviderCatalog";

type DragHoverTarget = {
  position: ProviderInsertPosition;
  providerId: string;
};

export function useProviderCatalogReorder(
  providerCatalog: UseProviderCatalogResult,
  visibleProviderIds: readonly string[],
) {
  const [draggingProviderId, setDraggingProviderId] = useState<string | null>(null);
  const [dragHoverTarget, setDragHoverTarget] =
    useState<DragHoverTarget | null>(null);
  const dragStartProviderIdsRef = useRef<string[] | null>(null);
  const dragPreviewProviderIdsRef = useRef<string[] | null>(null);
  const isDropCommittedRef = useRef(false);
  const providerListAnimation = useReorderListAnimation(
    visibleProviderIds,
    draggingProviderId,
  );

  const resetDragState = useCallback(() => {
    setDraggingProviderId(null);
    setDragHoverTarget(null);
    dragStartProviderIdsRef.current = null;
    dragPreviewProviderIdsRef.current = null;
    isDropCommittedRef.current = false;
    providerListAnimation.clearAnimationSnapshot();
  }, [providerListAnimation]);

  const restoreDragStartOrder = useCallback(() => {
    const dragStartProviderIds = dragStartProviderIdsRef.current;
    if (!dragStartProviderIds) {
      return;
    }

    providerListAnimation.captureAnimationSnapshot();
    providerCatalog.previewProviderOrder(dragStartProviderIds);
  }, [providerCatalog, providerListAnimation]);

  const commitPreviewOrder = useCallback(() => {
    if (draggingProviderId === null) {
      return;
    }

    const dragStartProviderIds = dragStartProviderIdsRef.current;
    const nextProviderIds = dragPreviewProviderIdsRef.current;
    setDragHoverTarget(null);

    if (!nextProviderIds) {
      resetDragState();
      return;
    }

    if (
      dragStartProviderIds &&
      dragStartProviderIds.length === nextProviderIds.length &&
      dragStartProviderIds.every(
        (providerId, index) => providerId === nextProviderIds[index],
      )
    ) {
      resetDragState();
      return;
    }

    isDropCommittedRef.current = true;
    void (async () => {
      try {
        await providerCatalog.persistProviderOrder(nextProviderIds);
      } catch {
        restoreDragStartOrder();
      } finally {
        resetDragState();
      }
    })();
  }, [
    draggingProviderId,
    providerCatalog,
    resetDragState,
    restoreDragStartOrder,
  ]);

  const handleListDragOver = useCallback((
    event: DragEvent<HTMLDivElement>,
  ) => {
    if (draggingProviderId === null) {
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, [draggingProviderId]);

  const handleListDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (draggingProviderId === null) {
      return;
    }

    event.preventDefault();
    commitPreviewOrder();
  }, [commitPreviewOrder, draggingProviderId]);

  const handleProviderDragStart = useCallback((
    event: DragEvent<HTMLDivElement>,
    providerId: string,
  ) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", providerId);
    setDraggingProviderId(providerId);
    setDragHoverTarget(null);
    dragStartProviderIdsRef.current = providerCatalog.items.map(
      (item) => item.provider_id,
    );
    dragPreviewProviderIdsRef.current = dragStartProviderIdsRef.current;
    isDropCommittedRef.current = false;
  }, [providerCatalog.items]);

  const handleProviderDragOver = useCallback((
    event: DragEvent<HTMLDivElement>,
    targetProviderId: string,
  ) => {
    if (
      draggingProviderId === null ||
      draggingProviderId === targetProviderId
    ) {
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const nextDropPosition = getDropPosition(event);
    setDragHoverTarget({
      position: nextDropPosition,
      providerId: targetProviderId,
    });

    const nextProviderIds = providerCatalog.getReorderedProviderIds(
      draggingProviderId,
      targetProviderId,
      nextDropPosition,
    );
    const currentPreviewProviderIds = dragPreviewProviderIdsRef.current;
    if (
      currentPreviewProviderIds &&
      currentPreviewProviderIds.length === nextProviderIds.length &&
      currentPreviewProviderIds.every(
        (providerId, index) => providerId === nextProviderIds[index],
      )
    ) {
      return;
    }

    providerListAnimation.captureAnimationSnapshot();
    dragPreviewProviderIdsRef.current = nextProviderIds;
    providerCatalog.previewProviderOrder(nextProviderIds);
  }, [draggingProviderId, providerCatalog, providerListAnimation]);

  const handleProviderDragEnd = useCallback(() => {
    if (!isDropCommittedRef.current) {
      restoreDragStartOrder();
      resetDragState();
    }
  }, [resetDragState, restoreDragStartOrder]);

  return {
    dragHoverTarget,
    draggingProviderId,
    handleListDragOver,
    handleListDrop,
    handleProviderDragEnd,
    handleProviderDragOver,
    handleProviderDragStart,
    registerProviderItem: providerListAnimation.registerAnimatedItem,
  };
}

function getDropPosition(
  event: DragEvent<HTMLDivElement>,
): ProviderInsertPosition {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY - rect.top <= rect.height / 2 ? "before" : "after";
}

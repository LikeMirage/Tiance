import { useEffect, useLayoutEffect, useRef } from "react";

type ListItemNode = HTMLDivElement;
type ListItemSnapshot = {
  left: number;
  top: number;
};

const DEFAULT_DURATION_MS = 220;
const DEFAULT_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

export function useReorderListAnimation(
  itemIds: readonly string[],
  activeItemId: string | null,
) {
  const itemNodesRef = useRef(new Map<string, ListItemNode>());
  const cleanupMapRef = useRef(new Map<string, () => void>());
  const snapshotRef = useRef<Map<string, ListItemSnapshot> | null>(null);

  const clearItemAnimation = (itemId: string) => {
    const cleanup = cleanupMapRef.current.get(itemId);
    if (!cleanup) {
      return;
    }

    cleanup();
    cleanupMapRef.current.delete(itemId);
  };

  const clearAllAnimations = () => {
    cleanupMapRef.current.forEach((cleanup) => cleanup());
    cleanupMapRef.current.clear();
  };

  const registerAnimatedItem = (itemId: string, node: ListItemNode | null) => {
    if (node) {
      itemNodesRef.current.set(itemId, node);
      return;
    }

    itemNodesRef.current.delete(itemId);
    clearItemAnimation(itemId);
  };

  const captureAnimationSnapshot = () => {
    const nextSnapshot = new Map<string, ListItemSnapshot>();

    itemIds.forEach((itemId) => {
      const node = itemNodesRef.current.get(itemId);
      if (!node) {
        return;
      }

      const rect = node.getBoundingClientRect();
      nextSnapshot.set(itemId, {
        left: rect.left,
        top: rect.top,
      });
    });

    snapshotRef.current = nextSnapshot;
  };

  const clearAnimationSnapshot = () => {
    snapshotRef.current = null;
  };

  useLayoutEffect(() => {
    const snapshot = snapshotRef.current;
    if (!snapshot || snapshot.size === 0) {
      return;
    }

    snapshotRef.current = null;

    itemIds.forEach((itemId) => {
      const node = itemNodesRef.current.get(itemId);
      const previousRect = snapshot.get(itemId);
      if (!node || !previousRect || itemId === activeItemId) {
        clearItemAnimation(itemId);
        return;
      }

      const nextRect = node.getBoundingClientRect();
      const deltaX = previousRect.left - nextRect.left;
      const deltaY = previousRect.top - nextRect.top;

      if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) {
        clearItemAnimation(itemId);
        return;
      }

      clearItemAnimation(itemId);

      node.style.transition = "none";
      node.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
      void node.offsetHeight;

      node.style.transition = `transform ${DEFAULT_DURATION_MS}ms ${DEFAULT_EASING}`;
      node.style.transform = "";

      const cleanup = () => {
        node.style.transition = "";
        node.style.transform = "";
      };

      const handleTransitionEnd = () => {
        window.clearTimeout(timeoutId);
        cleanup();
        cleanupMapRef.current.delete(itemId);
      };

      const timeoutId = window.setTimeout(() => {
        cleanup();
        cleanupMapRef.current.delete(itemId);
      }, DEFAULT_DURATION_MS + 80);

      node.addEventListener("transitionend", handleTransitionEnd, { once: true });
      cleanupMapRef.current.set(itemId, () => {
        window.clearTimeout(timeoutId);
        node.removeEventListener("transitionend", handleTransitionEnd);
        cleanup();
      });
    });
  }, [activeItemId, itemIds]);

  useEffect(() => clearAllAnimations, []);

  return {
    captureAnimationSnapshot,
    clearAnimationSnapshot,
    registerAnimatedItem,
  };
}

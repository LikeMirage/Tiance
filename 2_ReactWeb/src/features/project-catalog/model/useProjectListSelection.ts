import { useCallback, useRef, useState } from "react";

export function useProjectListSelection() {
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set());
  const selectedProjectIdsRef = useRef<Set<string>>(new Set());

  const replaceSelection = useCallback((projectIds: Iterable<string>) => {
    const next = new Set(projectIds);
    selectedProjectIdsRef.current = next;
    setSelectedProjectIds(new Set(next));
  }, []);

  const resetSelection = useCallback(() => {
    replaceSelection([]);
  }, [replaceSelection]);

  const toggleSelection = useCallback((projectId: string) => {
    const next = new Set(selectedProjectIdsRef.current);
    if (next.has(projectId)) {
      next.delete(projectId);
    } else {
      next.add(projectId);
    }
    replaceSelection(next);
  }, [replaceSelection]);

  const retainSelection = useCallback((validProjectIds: ReadonlySet<string>) => {
    const next = new Set(
      [...selectedProjectIdsRef.current].filter((projectId) => validProjectIds.has(projectId)),
    );
    if (
      next.size === selectedProjectIdsRef.current.size &&
      [...next].every((projectId) => selectedProjectIdsRef.current.has(projectId))
    ) {
      return;
    }
    replaceSelection(next);
  }, [replaceSelection]);

  return {
    replaceSelection,
    resetSelection,
    retainSelection,
    selectedProjectIds,
    selectedProjectIdsRef,
    toggleSelection,
  };
}

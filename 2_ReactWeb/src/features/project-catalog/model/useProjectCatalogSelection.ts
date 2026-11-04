import { useCallback, useRef, useState } from "react";

import type { Project } from "../../../entities/project/model/project";
import type { WorkspaceLastOpenedResponse } from "../../../services/workspace/workspaceLastOpened";
import { resolveSelectedProjectId } from "./projectCatalogHelpers";

export type ProjectCatalogSelection = {
  categoryId: string | null;
  projectId: string | null;
  sessionId: string | null;
};

export function useProjectCatalogSelection() {
  const [selection, setSelection] = useState<ProjectCatalogSelection>({
    categoryId: null, projectId: null, sessionId: null,
  });
  const currentRef = useRef(selection);
  const categoriesRef = useRef(new Map<string, string | null>());

  const select = useCallback((next: ProjectCatalogSelection) => {
    // Navigation is immediate, including two selections in the same render.
    // Persistence acknowledgements must not restore an older UI selection.
    currentRef.current = next;
    if (next.categoryId) categoriesRef.current.set(next.categoryId, next.projectId);
    setSelection(current => current.categoryId === next.categoryId
      && current.projectId === next.projectId && current.sessionId === next.sessionId
      ? current : next);
  }, []);

  const restoreSavedSelections = useCallback((saved: WorkspaceLastOpenedResponse | null) => {
    if (!saved) return;
    for (const item of Object.values(saved.category_selections)) {
      if (!categoriesRef.current.has(item.category_id)) {
        categoriesRef.current.set(item.category_id, item.project_id);
      }
    }
    if (saved.category_id && !categoriesRef.current.has(saved.category_id)) {
      categoriesRef.current.set(saved.category_id, saved.project_id);
    }
  }, []);

  const getCategorySelection = useCallback((items: readonly Project[], categoryId: string | null) => {
    const remembered = categoryId ? categoriesRef.current.get(categoryId) : null;
    const projectId = categoryId
      ? resolveSelectedProjectId(items, categoryId, remembered ?? null)
      : null;
    return {
      categoryId,
      projectId,
      // Ordinary navigation restores the project's own active session. Only an
      // explicit conversation click supplies a transient session target.
      sessionId: null,
    };
  }, []);

  return { currentRef, getCategorySelection, restoreSavedSelections, select, selection };
}

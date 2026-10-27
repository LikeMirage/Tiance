import { useCallback } from "react";
import type { WorkspaceLayoutPreferenceUpdate } from "../../../entities/workspace/model/workspaceLayoutPreferences";

type Options = {
  expandedProjectId: string | null;
  projectId: string | null;
  categoryId: string | null;
  openProjectOverview: (projectId: string, options: { activate: boolean }) => unknown;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
};

// The collection's existing preference adapter owns its tab selection.
// Selecting an outer overview must not enter a project or create an inner tab.
export function useConversationOverviewNavigation({
  expandedProjectId, projectId, categoryId, openProjectOverview, onLayoutPreferenceChange,
}: Options) {
  return useCallback(() => {
    if (expandedProjectId) {
      openProjectOverview(expandedProjectId, { activate: true });
    } else if (projectId && categoryId) {
      onLayoutPreferenceChange({
        projectOverviewMaximized: { categoryId, projectId },
        projectOverviewView: { categoryId, view: "conversation" },
      });
    }
  }, [expandedProjectId, projectId, categoryId, openProjectOverview, onLayoutPreferenceChange]);
}

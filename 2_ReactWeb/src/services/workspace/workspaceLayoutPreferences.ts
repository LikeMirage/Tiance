import type {
  CollectionOverviewView,
  ProjectOverviewLayoutMode,
  ProjectOverviewView,
  ToolOverviewView,
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../entities/workspace/model/workspaceLayoutPreferences";
import {
  normalizeWorkspaceLayoutPreferences,
  normalizeWorkspaceLayoutPreferenceUpdate,
} from "../../entities/workspace/model/workspaceLayoutPreferences";
import { fetchJson } from "../http/httpClient";

const WORKSPACE_LAYOUT_REQUEST_TIMEOUT_MS = 2500;

type WorkspaceLayoutPreferencesResponse = {
  ai_panel_width: number;
  composer_height: number;
  project_overview_layout_modes: Record<string, ProjectOverviewLayoutMode>;
  project_overview_maximized_project_ids: Record<string, string>;
  project_overview_views: Record<string, ProjectOverviewView>;
  side_panel_width: number;
  tool_overview_views: Record<string, ToolOverviewView>;
  collection_overview_views: Record<string, CollectionOverviewView>;
  version: number;
};

type WorkspaceLayoutPreferencesSaveRequest = {
  ai_panel_width?: number;
  composer_height?: number;
  project_overview_layout?: {
    category_id: string;
    layout_mode: ProjectOverviewLayoutMode;
  };
  project_overview_maximized?: {
    category_id: string;
    project_id: string | null;
  };
  project_overview_view?: {
    category_id: string;
    view: ProjectOverviewView;
  };
  side_panel_width?: number;
  tool_overview_view?: {
    category_id: string;
    view: ToolOverviewView;
  };
  collection_overview_view?: {
    category_id: string;
    view: CollectionOverviewView;
  };
};

export async function getWorkspaceLayoutPreferences(
  init?: RequestInit,
): Promise<WorkspaceLayoutPreferences> {
  const response = await fetchJson<WorkspaceLayoutPreferencesResponse>(
    "/api/workspace/layout-preferences",
    init,
  );
  return mapWorkspaceLayoutPreferences(response);
}

export function getWorkspaceLayoutPreferencesWithTimeout(): Promise<WorkspaceLayoutPreferences> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort();
  }, WORKSPACE_LAYOUT_REQUEST_TIMEOUT_MS);

  return getWorkspaceLayoutPreferences({ signal: controller.signal }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

export async function saveWorkspaceLayoutPreferences(
  update: WorkspaceLayoutPreferenceUpdate,
): Promise<WorkspaceLayoutPreferences> {
  const normalized = normalizeWorkspaceLayoutPreferenceUpdate(update);
  const response = await fetchJson<WorkspaceLayoutPreferencesResponse>(
    "/api/workspace/layout-preferences",
    {
      method: "PUT",
      body: JSON.stringify(mapWorkspaceLayoutPreferencesUpdate(normalized)),
    },
  );
  return mapWorkspaceLayoutPreferences(response);
}

function mapWorkspaceLayoutPreferences(
  response: WorkspaceLayoutPreferencesResponse,
): WorkspaceLayoutPreferences {
  return normalizeWorkspaceLayoutPreferences({
    aiPanelWidth: response.ai_panel_width,
    composerHeight: response.composer_height,
    projectOverviewLayoutModes: response.project_overview_layout_modes,
    projectOverviewMaximizedProjectIds:
      response.project_overview_maximized_project_ids,
    projectOverviewViews: response.project_overview_views,
    sidePanelWidth: response.side_panel_width,
    toolOverviewViews: response.tool_overview_views,
    collectionOverviewViews: response.collection_overview_views,
  });
}

function mapWorkspaceLayoutPreferencesUpdate(
  update: WorkspaceLayoutPreferenceUpdate,
): WorkspaceLayoutPreferencesSaveRequest {
  const payload: WorkspaceLayoutPreferencesSaveRequest = {};
  if (update.aiPanelWidth !== undefined) {
    payload.ai_panel_width = update.aiPanelWidth;
  }
  if (update.composerHeight !== undefined) {
    payload.composer_height = update.composerHeight;
  }
  if (update.sidePanelWidth !== undefined) {
    payload.side_panel_width = update.sidePanelWidth;
  }
  if (update.projectOverviewLayout !== undefined) {
    payload.project_overview_layout = {
      category_id: update.projectOverviewLayout.categoryId,
      layout_mode: update.projectOverviewLayout.layoutMode,
    };
  }
  if (update.projectOverviewMaximized !== undefined) {
    payload.project_overview_maximized = {
      category_id: update.projectOverviewMaximized.categoryId,
      project_id: update.projectOverviewMaximized.projectId,
    };
  }
  if (update.projectOverviewView !== undefined) {
    payload.project_overview_view = {
      category_id: update.projectOverviewView.categoryId,
      view: update.projectOverviewView.view,
    };
  }
  if (update.toolOverviewView !== undefined) {
    payload.tool_overview_view = {
      category_id: update.toolOverviewView.categoryId,
      view: update.toolOverviewView.view,
    };
  }
  if (update.collectionOverviewView !== undefined) {
    payload.collection_overview_view = {
      category_id: update.collectionOverviewView.categoryId,
      view: update.collectionOverviewView.view,
    };
  }
  return payload;
}

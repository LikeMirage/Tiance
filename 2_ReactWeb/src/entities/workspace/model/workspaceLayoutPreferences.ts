export type ProjectOverviewLayoutMode = "grid" | "wide" | "roller" | "stack";
export type ProjectOverviewView = "projects" | "online" | "conversation" | "branches";
export type ToolOverviewView = "tools" | ProjectOverviewView;
export type CollectionOverviewView = "specialized" | "online" | "projects" | "conversation";

export type WorkspaceLayoutPreferences = {
  aiPanelWidth: number;
  composerHeight: number;
  projectOverviewLayoutModes: Readonly<Record<string, ProjectOverviewLayoutMode>>;
  projectOverviewMaximizedProjectIds: Readonly<Record<string, string>>;
  projectOverviewViews: Readonly<Record<string, ProjectOverviewView>>;
  sidePanelWidth: number;
  toolOverviewViews: Readonly<Record<string, ToolOverviewView>>;
  collectionOverviewViews: Readonly<Record<string, CollectionOverviewView>>;
};

type WorkspaceLayoutPreferencesInput = Partial<WorkspaceLayoutPreferences>;

export type WorkspaceLayoutPreferenceUpdate = {
  aiPanelWidth?: number;
  composerHeight?: number;
  projectOverviewLayout?: {
    categoryId: string;
    layoutMode: ProjectOverviewLayoutMode;
  };
  projectOverviewMaximized?: {
    categoryId: string;
    projectId: string | null;
  };
  projectOverviewView?: {
    categoryId: string;
    view: ProjectOverviewView;
  };
  sidePanelWidth?: number;
  toolOverviewView?: {
    categoryId: string;
    view: ToolOverviewView;
  };
  collectionOverviewView?: {
    categoryId: string;
    view: CollectionOverviewView;
  };
};

export const WORKSPACE_LAYOUT_DEFAULTS: WorkspaceLayoutPreferences = {
  aiPanelWidth: 364,
  composerHeight: 144,
  projectOverviewLayoutModes: {},
  projectOverviewMaximizedProjectIds: {},
  projectOverviewViews: {},
  sidePanelWidth: 250,
  toolOverviewViews: {},
  collectionOverviewViews: {},
};

export const WORKSPACE_LAYOUT_LIMITS = {
  aiPanelWidth: {
    max: 900,
    min: 248,
  },
  composerHeight: {
    max: 280,
    min: 112,
  },
  sidePanelWidth: {
    max: 560,
    min: 108,
  },
} as const;

export function normalizeWorkspaceLayoutPreferences(
  preferences: WorkspaceLayoutPreferencesInput | null | undefined,
): WorkspaceLayoutPreferences {
  return {
    aiPanelWidth: normalizeWorkspaceLayoutValue(
      preferences?.aiPanelWidth,
      WORKSPACE_LAYOUT_DEFAULTS.aiPanelWidth,
      WORKSPACE_LAYOUT_LIMITS.aiPanelWidth.min,
      WORKSPACE_LAYOUT_LIMITS.aiPanelWidth.max,
    ),
    composerHeight: normalizeWorkspaceLayoutValue(
      preferences?.composerHeight,
      WORKSPACE_LAYOUT_DEFAULTS.composerHeight,
      WORKSPACE_LAYOUT_LIMITS.composerHeight.min,
      WORKSPACE_LAYOUT_LIMITS.composerHeight.max,
    ),
    projectOverviewLayoutModes: normalizeProjectOverviewLayoutModes(
      preferences?.projectOverviewLayoutModes,
    ),
    projectOverviewMaximizedProjectIds: normalizeProjectOverviewMaximizedProjectIds(
      preferences?.projectOverviewMaximizedProjectIds,
    ),
    projectOverviewViews: normalizeProjectOverviewViews(
      preferences?.projectOverviewViews,
    ),
    sidePanelWidth: normalizeWorkspaceLayoutValue(
      preferences?.sidePanelWidth,
      WORKSPACE_LAYOUT_DEFAULTS.sidePanelWidth,
      WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.min,
      WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.max,
    ),
    toolOverviewViews: normalizeToolOverviewViews(
      preferences?.toolOverviewViews,
    ),
    collectionOverviewViews: normalizeCollectionOverviewViews(
      preferences?.collectionOverviewViews,
    ),
  };
}

export function normalizeWorkspaceLayoutPreferenceUpdate(
  update: WorkspaceLayoutPreferenceUpdate,
): WorkspaceLayoutPreferenceUpdate {
  const normalized: WorkspaceLayoutPreferenceUpdate = {};
  if (update.aiPanelWidth !== undefined) {
    normalized.aiPanelWidth = normalizeWorkspaceLayoutValue(
      update.aiPanelWidth,
      WORKSPACE_LAYOUT_DEFAULTS.aiPanelWidth,
      WORKSPACE_LAYOUT_LIMITS.aiPanelWidth.min,
      WORKSPACE_LAYOUT_LIMITS.aiPanelWidth.max,
    );
  }
  if (update.composerHeight !== undefined) {
    normalized.composerHeight = normalizeWorkspaceLayoutValue(
      update.composerHeight,
      WORKSPACE_LAYOUT_DEFAULTS.composerHeight,
      WORKSPACE_LAYOUT_LIMITS.composerHeight.min,
      WORKSPACE_LAYOUT_LIMITS.composerHeight.max,
    );
  }
  if (update.sidePanelWidth !== undefined) {
    normalized.sidePanelWidth = normalizeWorkspaceLayoutValue(
      update.sidePanelWidth,
      WORKSPACE_LAYOUT_DEFAULTS.sidePanelWidth,
      WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.min,
      WORKSPACE_LAYOUT_LIMITS.sidePanelWidth.max,
    );
  }
  const categoryId = update.projectOverviewLayout?.categoryId.trim();
  if (
    categoryId
    && isProjectOverviewLayoutMode(update.projectOverviewLayout?.layoutMode)
  ) {
    normalized.projectOverviewLayout = {
      categoryId,
      layoutMode: update.projectOverviewLayout.layoutMode,
    };
  }
  const maximizedCategoryId = update.projectOverviewMaximized?.categoryId.trim();
  const maximizedProjectId = update.projectOverviewMaximized?.projectId?.trim() || null;
  if (maximizedCategoryId) {
    normalized.projectOverviewMaximized = {
      categoryId: maximizedCategoryId,
      projectId: maximizedProjectId,
    };
  }
  const viewCategoryId = update.projectOverviewView?.categoryId.trim();
  if (viewCategoryId && isProjectOverviewView(update.projectOverviewView?.view)) {
    normalized.projectOverviewView = {
      categoryId: viewCategoryId,
      view: update.projectOverviewView.view,
    };
  }
  const toolViewCategoryId = update.toolOverviewView?.categoryId.trim();
  if (toolViewCategoryId && isToolOverviewView(update.toolOverviewView?.view)) {
    normalized.toolOverviewView = {
      categoryId: toolViewCategoryId,
      view: update.toolOverviewView.view,
    };
  }
  const collectionViewCategoryId = update.collectionOverviewView?.categoryId.trim();
  if (
    collectionViewCategoryId
    && isCollectionOverviewView(update.collectionOverviewView?.view)
  ) {
    normalized.collectionOverviewView = {
      categoryId: collectionViewCategoryId,
      view: update.collectionOverviewView.view,
    };
  }
  return normalized;
}

export function isProjectOverviewLayoutMode(
  value: unknown,
): value is ProjectOverviewLayoutMode {
  return value === "grid"
    || value === "wide"
    || value === "roller"
    || value === "stack";
}

export function isProjectOverviewView(value: unknown): value is ProjectOverviewView {
  return value === "projects"
    || value === "online"
    || value === "conversation"
    || value === "branches";
}

export function isToolOverviewView(value: unknown): value is ToolOverviewView {
  return value === "tools" || isProjectOverviewView(value);
}

export function isCollectionOverviewView(value: unknown): value is CollectionOverviewView {
  return value === "specialized"
    || value === "online"
    || value === "projects"
    || value === "conversation";
}

function normalizeProjectOverviewLayoutModes(
  value: Readonly<Record<string, ProjectOverviewLayoutMode>> | null | undefined,
): Readonly<Record<string, ProjectOverviewLayoutMode>> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([categoryId, layoutMode]) =>
        categoryId.trim().length > 0 && isProjectOverviewLayoutMode(layoutMode),
    ),
  );
}

function normalizeProjectOverviewMaximizedProjectIds(
  value: Readonly<Record<string, string>> | null | undefined,
): Readonly<Record<string, string>> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value)
      .map(([categoryId, projectId]) => [categoryId.trim(), projectId.trim()])
      .filter(([categoryId, projectId]) => categoryId.length > 0 && projectId.length > 0),
  );
}

function normalizeProjectOverviewViews(
  value: Readonly<Record<string, ProjectOverviewView>> | null | undefined,
): Readonly<Record<string, ProjectOverviewView>> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([categoryId, view]) =>
        categoryId.trim().length > 0 && isProjectOverviewView(view),
    ),
  );
}

function normalizeToolOverviewViews(
  value: Readonly<Record<string, ToolOverviewView>> | null | undefined,
): Readonly<Record<string, ToolOverviewView>> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([categoryId, view]) =>
        categoryId.trim().length > 0 && isToolOverviewView(view),
    ),
  );
}

function normalizeCollectionOverviewViews(
  value: Readonly<Record<string, CollectionOverviewView>> | null | undefined,
): Readonly<Record<string, CollectionOverviewView>> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([categoryId, view]) =>
        categoryId.trim().length > 0 && isCollectionOverviewView(view),
    ),
  );
}

export function normalizeWorkspaceLayoutValue(
  value: number | null | undefined,
  fallback: number,
  min: number,
  max: number,
) {
  const candidate = Number.isFinite(value) ? Number(value) : fallback;
  return Math.min(Math.max(Math.round(candidate), min), max);
}

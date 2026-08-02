export type ToolCatalogChange =
  | {
    kind: "toolsets";
    sourceId?: string;
  }
  | {
    folderId?: string;
    kind: "folders";
    sourceId?: string;
    toolsetId?: string;
  }
  | {
    folderId?: string;
    kind: "metadata";
    sourceId?: string;
    toolsetId?: string;
  };

type ToolCatalogChangeListener = (change: ToolCatalogChange) => void;

const listeners = new Set<ToolCatalogChangeListener>();

export function publishToolCatalogChange(change: ToolCatalogChange) {
  for (const listener of listeners) {
    listener(change);
  }
}

export function subscribeToolCatalogChanges(listener: ToolCatalogChangeListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

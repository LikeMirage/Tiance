const PROJECT_CATALOG_CHANGED_EVENT = "tiance:project-catalog-changed";

export function dispatchProjectCatalogChanged() {
  window.dispatchEvent(new Event(PROJECT_CATALOG_CHANGED_EVENT));
}

export function listenProjectCatalogChanged(listener: () => void) {
  window.addEventListener(PROJECT_CATALOG_CHANGED_EVENT, listener);
  return () => window.removeEventListener(PROJECT_CATALOG_CHANGED_EVENT, listener);
}

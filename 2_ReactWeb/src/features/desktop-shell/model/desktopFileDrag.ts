export type DesktopFileDragData = { mimeType: string; data: string };

let activeDrag: DesktopFileDragData | null = null;

export function getDesktopFileDragData(mimeType: string): string | null {
  return activeDrag?.mimeType === mimeType ? activeDrag.data : null;
}

export function hasDesktopFileDragData(): boolean {
  return activeDrag !== null;
}

/** Keep the app reference locally while the OS receives an actual file-drop data object. */
export function startDesktopFileDrag(
  event: { preventDefault: () => void },
  paths: string[],
  data: DesktopFileDragData,
  onUnavailable: () => void,
): boolean {
  const api = window.pywebview?.api;
  if (typeof api?.start_file_drag !== "function" || !navigator.platform.startsWith("Win")) return false;
  event.preventDefault(); // Cancel Chromium's text drag before starting the native OLE drag.
  if (activeDrag) return true;
  if (paths.length === 0) { onUnavailable(); return true; }
  const source = { ...data };
  activeDrag = source;
  const clear = () => {
    if (activeDrag === source) activeDrag = null;
  };
  // The document bubble listener runs after the app's drop handlers have consumed the reference.
  document.addEventListener("drop", clear, { once: true });
  void Promise.resolve().then(() => api.start_file_drag!(paths)).then((started) => {
    if (!started) onUnavailable();
  }).catch(onUnavailable).finally(() => {
    document.removeEventListener("drop", clear);
    clear();
  });
  return true;
}

import { fetchNoContent } from "../http/httpClient";

/** Hand off Windows foreground permission for this user-initiated reveal only. */
export async function revealInFileExplorer(apiPath: string, init: RequestInit) {
  const api = typeof window === "undefined" ? undefined : window.pywebview?.api;
  if (api?.prepare_file_explorer) {
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.resolve().then(() => api.prepare_file_explorer!()),
        new Promise<void>((resolve) => { timeout = setTimeout(resolve, 500); }),
      ]);
    } catch {
      // An old/unavailable native bridge must not prevent opening the path.
    } finally {
      clearTimeout(timeout);
    }
  }
  return fetchNoContent(apiPath, init);
}

import { fetchNoContent } from "../http/httpClient";
import { revealInFileExplorer } from "./fileExplorer";

export function revealDesktopLocalPath(path: string) {
  return revealInFileExplorer("/api/desktop/local-path/reveal", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function openDesktopLocalPath(path: string) {
  return fetchNoContent("/api/desktop/local-path/open-default", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

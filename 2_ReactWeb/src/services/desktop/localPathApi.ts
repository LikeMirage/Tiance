import { fetchNoContent } from "../http/httpClient";

export function revealDesktopLocalPath(path: string) {
  return fetchNoContent("/api/desktop/local-path/reveal", {
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

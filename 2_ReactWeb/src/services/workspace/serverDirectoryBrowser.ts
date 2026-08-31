import { fetchJson } from "../http/httpClient";

export type ServerDirectoryEntry = {
  name: string;
  path: string;
};

export type ServerDirectoryListing = {
  path: string;
  parent_path: string | null;
  roots: ServerDirectoryEntry[];
  directories: ServerDirectoryEntry[];
};

export function listServerDirectories(path?: string, signal?: AbortSignal) {
  const query = path?.trim()
    ? `?path=${encodeURIComponent(path.trim())}`
    : "";
  return fetchJson<ServerDirectoryListing>(`/api/workspace/directories${query}`, { signal });
}

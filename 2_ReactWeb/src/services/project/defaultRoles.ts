import { fetchJson } from "../http/httpClient";

export const DEFAULT_ROLE_COLLECTIONS = [
  "project", "tool", "knowledge", "experience", "role", "provider", "theme",
] as const;
export type DefaultRoleCollection = typeof DEFAULT_ROLE_COLLECTIONS[number];
export type DefaultRoles = Record<DefaultRoleCollection, string>;

export function getDefaultRoles(): Promise<DefaultRoles> {
  return fetchJson<DefaultRoles>("/api/roles/defaults");
}

export function saveDefaultRole(collection: DefaultRoleCollection, roleId: string) {
  return fetchJson<{ role_project_id: string }>(`/api/roles/defaults/${collection}`, {
    method: "PUT",
    body: JSON.stringify({ role_project_id: roleId }),
  });
}

import type { ConversationRoleCatalog } from "../../entities/role-configuration/model/roleConfiguration";
import { fetchJson } from "../http/httpClient";

export function getConversationRoles() {
  return fetchJson<ConversationRoleCatalog>("/api/projects/roles/catalog");
}

import { env } from "../../shared/config/env";
import { conversationRuntime } from "../../entities/llm-chat/model/conversationRuntime";
import { watchEventSocket } from "../http/watchEventSocket";
import { dispatchProjectCatalogChanged } from "../../entities/project/model/projectCatalogEvents";
import { dispatchProjectConversationUpdated } from "../../entities/llm-chat/model/projectConversationEvents";

export function watchWorkspaceCatalogChanges(projectIds: () => string[]) {
  const stopRuntime = watchEventSocket(`${env.apiBaseUrl}/api/projects/runtime-events`, {
    onMessage(data) {
      try { conversationRuntime.receive(JSON.parse(data)); } catch { /* Ignore malformed events. */ }
    },
  });
  const stopCatalog = watchEventSocket(`${env.apiBaseUrl}/api/projects/catalog-events`, {
    onMessage(data) {
      let event;
      try { event = JSON.parse(data); } catch { return; }
      if (event?.kind !== "ready" && event?.kind !== "changed") return;
      const reset = event.kind === "ready" || event.reset === true;
      if (reset || event.catalog === true) dispatchProjectCatalogChanged();
      const ids = reset ? projectIds() : Array.isArray(event.projects) ? event.projects : [];
      for (const projectId of new Set(ids)) {
        if (typeof projectId === "string") dispatchProjectConversationUpdated({
          kind: "structure", projectId, source: "server",
        });
      }
    },
  });
  return () => { stopRuntime(); stopCatalog(); };
}

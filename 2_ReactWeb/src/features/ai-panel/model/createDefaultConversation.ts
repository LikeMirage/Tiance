import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { createProjectConversation } from "../../../services/project/createProjectConversation";

export async function createDefaultConversation(
  projectId: string,
) {
  const session = await createProjectConversation(projectId);
  dispatchProjectConversationUpdated({
    kind: "structure",
    projectId,
    sessionId: session.session_id,
  });
  return session;
}

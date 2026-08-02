import type { ConversationSessionState } from "../../../entities/llm-chat/model/conversation";
import { buildSessionKey } from "./sessionKey";

export function mergeStreamingRuntimeStatuses(
  projectId: string,
  responseStates: Record<string, ConversationSessionState>,
  previousStates: Record<string, ConversationSessionState>,
  streamingSessionKeys: ReadonlySet<string>,
) {
  const nextStates = { ...responseStates };
  for (const [sessionId, previousState] of Object.entries(previousStates)) {
    if (!streamingSessionKeys.has(buildSessionKey(projectId, sessionId))) continue;
    const responseState = nextStates[sessionId];
    if (!responseState) continue;
    nextStates[sessionId] = {
      ...responseState,
      runtime_status: previousState.runtime_status,
    };
  }
  return nextStates;
}

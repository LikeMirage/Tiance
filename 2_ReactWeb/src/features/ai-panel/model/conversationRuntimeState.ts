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
    const responseState = nextStates[sessionId];
    if (!responseState) continue;
    const localRunIsNewer = compareTimestamps(
      previousState.runtime_updated_at ?? previousState.updated_at,
      responseState.runtime_updated_at ?? responseState.updated_at,
    ) > 0;
    if (
      !localRunIsNewer
      && !streamingSessionKeys.has(buildSessionKey(projectId, sessionId))
    ) continue;
    nextStates[sessionId] = {
      ...responseState,
      runtime_status: previousState.runtime_status,
      runtime_updated_at: previousState.runtime_updated_at ?? previousState.updated_at,
    };
  }
  return nextStates;
}

function compareTimestamps(left: string, right: string) {
  const leftValue = Date.parse(left);
  const rightValue = Date.parse(right);
  if (!Number.isFinite(leftValue) || !Number.isFinite(rightValue)) return 0;
  return leftValue - rightValue;
}

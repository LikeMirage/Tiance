import { useSyncExternalStore } from "react";
import { conversationRuntime } from "./conversationRuntime";

export function useConversationRuntimeVersion() {
  return useSyncExternalStore(conversationRuntime.subscribe, conversationRuntime.getSnapshot);
}

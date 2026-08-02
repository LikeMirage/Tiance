export type ConversationSessionLoadState =
  | { status: "idle"; projectId: null; requestId: number }
  | { status: "loading"; projectId: string; requestId: number; hasSnapshot: boolean }
  | { status: "ready"; projectId: string; requestId: number }
  | { status: "error"; projectId: string; requestId: number; message: string; hasSnapshot: boolean };

export type ConversationSessionLoadEvent =
  | { type: "clear" }
  | { type: "begin"; projectId: string; requestId: number; hasSnapshot: boolean }
  | { type: "ready"; projectId: string; requestId: number }
  | {
      type: "failed";
      projectId: string;
      requestId: number;
      message: string;
      hasSnapshot: boolean;
    };

export const initialConversationSessionLoadState: ConversationSessionLoadState = {
  projectId: null,
  requestId: 0,
  status: "idle",
};

export function reduceConversationSessionLoad(
  state: ConversationSessionLoadState,
  event: ConversationSessionLoadEvent,
): ConversationSessionLoadState {
  switch (event.type) {
    case "clear":
      return initialConversationSessionLoadState;
    case "begin":
      return {
        hasSnapshot: event.hasSnapshot,
        projectId: event.projectId,
        requestId: event.requestId,
        status: "loading",
      };
    case "ready":
      if (!matchesRequest(state, event.projectId, event.requestId)) return state;
      return {
        projectId: event.projectId,
        requestId: event.requestId,
        status: "ready",
      };
    case "failed":
      if (!matchesRequest(state, event.projectId, event.requestId)) return state;
      return {
        hasSnapshot: event.hasSnapshot,
        message: event.message,
        projectId: event.projectId,
        requestId: event.requestId,
        status: "error",
      };
  }
}

function matchesRequest(
  state: ConversationSessionLoadState,
  projectId: string,
  requestId: number,
) {
  return state.projectId === projectId && state.requestId === requestId;
}

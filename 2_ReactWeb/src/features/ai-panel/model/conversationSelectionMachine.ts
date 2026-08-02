export type ConversationSelectionTarget = {
  projectId: string;
  sessionId: string | null;
};

export type ConversationSelectionRequest = {
  requestId: number;
  source: "overview" | "branch" | "create";
  target: ConversationSelectionTarget & { messageId?: string; sessionId: string };
};

export type ConversationSelectionFailure = {
  message: string;
  reason: "failed" | "missing";
  request: ConversationSelectionRequest;
};

export type ConversationSelectionState =
  | {
      current: ConversationSelectionTarget | null;
      status: "stable";
    }
  | {
      current: ConversationSelectionTarget | null;
      phase: "switching_project" | "waiting_for_session";
      request: ConversationSelectionRequest;
      status: "selecting";
    }
  | {
      current: ConversationSelectionTarget | null;
      failure: ConversationSelectionFailure;
      status: "failed";
    };

export type ConversationSelectionEvent =
  | { type: "request"; request: ConversationSelectionRequest }
  | { type: "cancelled"; requestId: number }
  | { type: "project_ready"; requestId: number }
  | { type: "confirmed"; requestId: number; target: ConversationSelectionTarget }
  | {
      type: "failed";
      current: ConversationSelectionTarget | null;
      message: string;
      reason: "failed" | "missing";
      requestId: number;
    }
  | { type: "project_changed"; projectId: string | null }
  | { type: "sync_current"; target: ConversationSelectionTarget };

export const initialConversationSelectionState: ConversationSelectionState = {
  current: null,
  status: "stable",
};

export function reduceConversationSelection(
  state: ConversationSelectionState,
  event: ConversationSelectionEvent,
): ConversationSelectionState {
  switch (event.type) {
    case "request":
      return {
        current: state.current,
        phase: "switching_project",
        request: event.request,
        status: "selecting",
      };
    case "cancelled":
      if (state.status !== "selecting" || state.request.requestId !== event.requestId) {
        return state;
      }
      return { current: state.current, status: "stable" };
    case "project_ready":
      if (state.status !== "selecting" || state.request.requestId !== event.requestId) {
        return state;
      }
      return { ...state, phase: "waiting_for_session" };
    case "confirmed":
      if (state.status !== "selecting" || state.request.requestId !== event.requestId) {
        return state;
      }
      if (!isSameTarget(state.request.target, event.target)) {
        return state;
      }
      return { current: event.target, status: "stable" };
    case "failed":
      if (state.status !== "selecting" || state.request.requestId !== event.requestId) {
        return state;
      }
      return {
        current: event.current,
        failure: {
          message: event.message,
          reason: event.reason,
          request: state.request,
        },
        status: "failed",
      };
    case "project_changed":
      if (
        state.status === "selecting" &&
        event.projectId !== state.request.target.projectId &&
        (
          state.phase === "waiting_for_session" ||
          event.projectId !== state.current?.projectId
        )
      ) {
        return {
          current: selectionForChangedProject(state.current, event.projectId),
          status: "stable",
        };
      }
      if (state.status === "selecting" || state.current?.projectId === event.projectId) {
        return state;
      }
      return {
        current: selectionForChangedProject(state.current, event.projectId),
        status: "stable",
      };
    case "sync_current":
      if (state.status === "selecting") {
        return isSameTarget(state.request.target, event.target)
          ? { current: event.target, status: "stable" }
          : state;
      }
      if (state.status === "failed" && isSameTarget(state.current, event.target)) {
        return { ...state, current: event.target };
      }
      return { current: event.target, status: "stable" };
  }
}

export function visibleConversationSelection(
  state: ConversationSelectionState,
): ConversationSelectionTarget | null {
  return state.status === "selecting" ? state.request.target : state.current;
}

function selectionForChangedProject(
  current: ConversationSelectionTarget | null,
  projectId: string | null,
): ConversationSelectionTarget | null {
  if (!projectId) return null;
  return current?.projectId === projectId
    ? current
    : { projectId, sessionId: null };
}

function isSameTarget(
  left: ConversationSelectionTarget | null,
  right: ConversationSelectionTarget | null,
) {
  return left?.projectId === right?.projectId && left?.sessionId === right?.sessionId;
}

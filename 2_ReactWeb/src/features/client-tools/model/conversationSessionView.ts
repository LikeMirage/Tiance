import type {
  ConversationBranchNode,
  ConversationSession,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import { serializeConversationConfiguration } from "./conversationConfiguration";

type ConversationRuntimeStatus = "idle" | "running" | "error";

export function getConversationMessagesFilePath(sessionId: string): string {
  return `.Tiance/conversations/sessions/${sessionId}/messages.jsonl`;
}

export function getConversationRelationshipFilePath(): string {
  return ".Tiance/conversations/branch_graph.json";
}

export function serializeConversationSessionSummary(
  response: ConversationSessionListResponse,
  session: ConversationSession,
) {
  return {
    session_id: session.session_id,
    title: session.title,
    runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
  };
}

export function serializeConversationSession(
  response: ConversationSessionListResponse,
  session: ConversationSession,
) {
  return serializeStandaloneConversationSession(
    session,
    response.session_states[session.session_id]?.runtime_status ?? "idle",
  );
}

export function serializeStandaloneConversationSession(
  session: ConversationSession,
  runtimeStatus: ConversationRuntimeStatus,
) {
  return {
    session_id: session.session_id,
    sequence_number: session.sequence_number,
    title: session.title,
    runtime_status: runtimeStatus,
    message_count: session.message_count,
    created_at: session.created_at,
    updated_at: session.updated_at,
    configuration: serializeConversationConfiguration(session),
    messages_file_path: getConversationMessagesFilePath(session.session_id),
  };
}

export function serializeConversationRelationship(
  response: ConversationSessionListResponse,
  sessionId: string,
) {
  const node = response.branch_nodes.find((item) => item.session_id === sessionId);
  if (!node) return null;
  const parentSession = findParentSession(response, node);
  return {
    branch_id: node.branch_id,
    tree_id: node.tree_id,
    parent_branch_id: node.parent_branch_id,
    parent_session: node.parent_session_id
      ? {
          session_id: node.parent_session_id,
          title: parentSession?.title ?? null,
        }
      : null,
    relation_kind: node.relation_kind,
    function_type: node.function_type,
    created_by: node.created_by,
    history_mode: node.history_mode,
    source_message_id: node.source_message_id,
    sibling_index: node.sibling_index,
    created_at: node.created_at,
    deleted_at: node.deleted_at,
  };
}

function findParentSession(
  response: ConversationSessionListResponse,
  node: ConversationBranchNode,
) {
  if (!node.parent_session_id) return null;
  return response.items.find((session) => session.session_id === node.parent_session_id) ?? null;
}

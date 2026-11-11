import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { getProjectConversationSummaries } from "../../../services/project/getProjectConversationSummaries";
import { deleteProjectConversations } from "../../../services/project/deleteProjectConversations";
import { buildConversationDeletionPlan } from "./conversationDeletionPlan";
import { clientToolSuccess, readOptionalString } from "./conversationClientToolValues";
import {
  buildConversationSessionIndex, conversationSessionLocation, selectConversationSessions,
  SESSION_GROUPS, type ConversationSessionListScope,
} from "./conversationSessionScope";

export async function executeConversationSelection(
  projectId: string, callerSessionId: string | null, args: Record<string, unknown>, signal?: AbortSignal,
) {
  const response = await getProjectConversationSummaries(projectId, signal);
  signal?.throwIfAborted();
  const action = args.action;
  if (action === "list_sessions") {
    if (args.session_ids !== undefined) throw new Error("list_sessions 使用单个 session_id 定位层级，不使用 session_ids。");
    const scope = readScope(args.scope);
    const relationDepth = readDepth(args.relation_depth);
    if (relationDepth !== null && scope !== "related" && scope !== "descendants") {
      throw new Error("relation_depth 只用于 scope=related 或 descendants。");
    }
    const specifiedAnchor = readOptionalString(args.session_id);
    if (specifiedAnchor && (scope === "all" || scope === "roots")) {
      throw new Error("scope=all 或 roots 时不要指定 session_id。");
    }
    const anchor = scope === "all" || scope === "roots" ? null : specifiedAnchor ?? callerSessionId;
    const group = readOptionalString(args.group);
    if (group && !(SESSION_GROUPS as readonly string[]).includes(group)) throw new Error(`不支持的会话分类：${group}`);
    const runtimeStatus = readOptionalString(args.runtime_status);
    if (runtimeStatus && !["idle", "running", "error"].includes(runtimeStatus)) throw new Error("runtime_status 只支持 idle、running、error。");
    const index = buildConversationSessionIndex(response);
    const sessions = selectConversationSessions(response, anchor, scope, relationDepth, index)
      .map((session) => ({
        session_id: session.session_id, title: session.title,
        runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
        ...conversationSessionLocation(index, session.session_id),
      })).filter((session) => (
        (!runtimeStatus || session.runtime_status === runtimeStatus)
        && (!group || (group === "functional"
          ? !["root", "child", "fork"].includes(session.group) : session.group === group))
      ));
    return clientToolSuccess({
      action, project_id: projectId, active_session_id: response.active_session_id,
      caller_session_id: callerSessionId, anchor_session_id: anchor,
      scope, relation_depth: relationDepth, group_filter: group, status_filter: runtimeStatus,
      count: sessions.length, sessions,
    });
  }
  if (action !== "preview_delete" && action !== "delete_session") throw new Error("不支持的会话选择操作。");
  if (args.group !== undefined || args.runtime_status !== undefined || args.relation_depth !== undefined
    || (args.scope !== undefined && args.scope !== "related")) {
    throw new Error("请先用 list_sessions 筛选，再通过 session_id 或 session_ids 明确指定删除目标；删除动作不接受列表筛选条件。");
  }
  const plan = buildConversationDeletionPlan(response, args, callerSessionId);
  if (action === "preview_delete") {
    return clientToolSuccess({ action, project_id: projectId, ...plan });
  }
  if (args.confirm !== true) throw new Error("删除会话必须明确传入 confirm=true。");
  signal?.throwIfAborted();
  // Submit an exact set once. Never run separate deletes that could leave half a batch deleted.
  await deleteProjectConversations(projectId, plan.session_ids, callerSessionId!, signal);
  dispatchProjectConversationUpdated({ kind: "structure", projectId, sessionId: plan.session_ids[0] });
  return clientToolSuccess({
    action, project_id: projectId,
    target_session_ids: plan.target_session_ids,
    include_descendants: plan.include_descendants,
    count: plan.count, deleted_session_ids: plan.session_ids,
    ...(args.session_id !== undefined ? { deleted_session_id: plan.target_session_ids[0] } : {}),
  });
}

function readScope(value: unknown): ConversationSessionListScope {
  if (value === undefined || value === null) return "related";
  if (typeof value === "string" && ["related", "all", "roots", "children", "descendants"].includes(value)) return value as ConversationSessionListScope;
  throw new Error("scope 只支持 related、all、roots、children、descendants。");
}

function readDepth(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  if (!Number.isSafeInteger(value) || Number(value) < 1) throw new Error("关系深度必须是大于等于 1 的整数。");
  return Number(value);
}

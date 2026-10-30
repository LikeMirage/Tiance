import type { ConversationBranchNode } from "../../../entities/llm-chat/model/conversation";
import {
  buildConversationSessionTree,
  type ConversationSessionTree,
  type ConversationSessionTreeNode,
} from "../../../entities/llm-chat/model/conversationSessionTree";
import type { ProjectOverviewSessionWithDisplayUsage } from "./projectOverviewUsage";

export {
  collectSessionAncestorIds,
  CONVERSATION_SESSION_GROUPS as PROJECT_OVERVIEW_SESSION_GROUPS,
  CONVERSATION_FUNCTION_SESSION_GROUPS as PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS,
  type ConversationSessionGroup as ProjectOverviewSessionGroup,
  type ConversationSessionLeafGroup as ProjectOverviewSessionLeafGroup,
} from "../../../entities/llm-chat/model/conversationSessionTree";

export type ProjectOverviewSessionTreeNode = ConversationSessionTreeNode<ProjectOverviewSessionWithDisplayUsage>;
export type ProjectOverviewSessionTree = ConversationSessionTree<ProjectOverviewSessionWithDisplayUsage>;

export function buildProjectOverviewSessionTree(
  sessions: ProjectOverviewSessionWithDisplayUsage[],
  relations: ConversationBranchNode[],
): ProjectOverviewSessionTree {
  return buildConversationSessionTree(sessions, relations);
}

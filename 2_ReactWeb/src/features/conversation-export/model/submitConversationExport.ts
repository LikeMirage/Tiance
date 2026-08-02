import {
  exportProjectConversation,
  type ProjectConversationExportResponse,
} from "@/services/project/exportProjectConversation";

import type {
  ConversationExportContentSelection,
  ConversationExportFormat,
  ConversationExportRange,
  ConversationExportRequest,
} from "./conversationExport";

export type ConversationExportSubmission = {
  baseName: string;
  content: ConversationExportContentSelection;
  directory: string;
  format: ConversationExportFormat;
  openAfterExport: boolean;
  range: ConversationExportRange;
};

export function submitConversationExport(
  request: ConversationExportRequest,
  submission: ConversationExportSubmission,
): Promise<ProjectConversationExportResponse> {
  return exportProjectConversation(request.projectId, request.sessionId, {
    base_name: submission.baseName,
    content: {
      assistant_content: submission.content.assistantContent,
      error_messages: submission.content.errorMessages,
      images: submission.content.images,
      message_metadata: submission.content.messageMetadata,
      model_info: submission.content.modelInfo,
      session_info: submission.content.sessionInfo,
      system_messages: submission.content.systemMessages,
      thinking: submission.content.thinking,
      timestamps: submission.content.timestamps,
      token_usage: submission.content.tokenUsage,
      tool_calls: submission.content.toolCalls,
      tool_results: submission.content.toolResults,
      user_messages: submission.content.userMessages,
    },
    format: submission.format,
    message_id: submission.range === "conversation" ? null : request.messageId,
    open_after_export: submission.openAfterExport,
    range: submission.range,
    target_directory: submission.directory,
  });
}

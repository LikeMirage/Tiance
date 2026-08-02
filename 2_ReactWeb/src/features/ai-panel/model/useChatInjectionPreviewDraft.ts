import { useEffect } from "react";

import { publishProjectFileMutation } from "../../../entities/project/model/projectFileMutation";
import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import type {
  ChatCompletionMessageInput,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { isAbortError } from "../../../services/http/httpErrors";
import { updateChatInjectionPreview } from "../../../services/llm/updateChatInjectionPreview";
import type { ChatModelOption } from "./chatModelOption";
import { buildGenerationParams } from "./generationParams";
import {
  buildConversationImageContentParts,
  hasConversationReferences,
} from "./conversationReferences";
import { toConversationDraftReferences } from "./conversationDraftReferences";
import type { SettledConversationDraft } from "./useConversationSessions";

const INJECTION_PREVIEW_FILE_NAME = "injection_preview.json";

type UseChatInjectionPreviewDraftOptions = {
  activeModel: ChatModelOption | null;
  activeReasoningMode: DsLlmReasoningMode;
  activeSessionId: string | null;
  activeSessionSettings: ConversationSessionSettings;
  references: ConversationMessageReferences;
  isActiveSessionStreaming: boolean;
  projectId: string | null;
  settledDraft: SettledConversationDraft | null;
  supportsImageInput: boolean;
};

export function useChatInjectionPreviewDraft({
  activeModel,
  activeReasoningMode,
  activeSessionId,
  activeSessionSettings,
  references,
  isActiveSessionStreaming,
  projectId,
  settledDraft,
  supportsImageInput,
}: UseChatInjectionPreviewDraftOptions) {
  useEffect(() => {
    if (!projectId || !activeSessionId || !activeModel || !settledDraft || isActiveSessionStreaming) {
      return undefined;
    }
    if (settledDraft.projectId !== projectId || settledDraft.sessionId !== activeSessionId) {
      return undefined;
    }

    const draftContent = settledDraft.draft.trim();
    const hasReferences = hasConversationReferences(references);
    const nextUserContent = draftContent || hasReferences ? draftContent : null;

    const controller = new AbortController();
    const requestContentParts = supportsImageInput && nextUserContent !== null
      ? buildConversationImageContentParts(references, projectId)
      : [];
    const requestMessages: ChatCompletionMessageInput[] = nextUserContent === null
      ? []
      : [{
        role: "user",
        content: nextUserContent,
        ...(hasReferences
          ? { references: toConversationDraftReferences(references) }
          : {}),
        ...(requestContentParts.length
          ? { content_parts: requestContentParts }
          : {}),
      }];

    void updateChatInjectionPreview({
      provider_id: activeModel.providerId,
      model_id: activeModel.modelId,
      project_id: projectId,
      session_id: activeSessionId,
      messages: requestMessages,
      return_thinking_content: activeSessionSettings.return_thinking_content,
      max_tool_calls: activeSessionSettings.max_tool_calls,
      generation: buildGenerationParams(activeSessionSettings, activeReasoningMode),
    }, { signal: controller.signal }).then(() => {
      publishProjectFileMutation({
        projectId,
        node: buildInjectionPreviewFileNode(activeSessionId),
        sourceId: "chat-injection-preview",
      });
    }).catch((error) => {
      if (!isAbortError(error)) {
        return undefined;
      }
      return undefined;
    });

    return () => {
      controller.abort();
    };
  }, [
    activeModel,
    activeReasoningMode,
    activeSessionId,
    activeSessionSettings,
    references,
    isActiveSessionStreaming,
    projectId,
    settledDraft,
    supportsImageInput,
  ]);
}

function buildInjectionPreviewFileNode(sessionId: string) {
  const path = `.Tiance/conversations/sessions/${sessionId}/${INJECTION_PREVIEW_FILE_NAME}`;
  return {
    id: path,
    name: INJECTION_PREVIEW_FILE_NAME,
    path,
    kind: "file" as const,
    has_children: false,
    mtime_ms: Date.now(),
    children: [],
  };
}

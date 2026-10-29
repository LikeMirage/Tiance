import { useEffect } from "react";

import { publishProjectFileMutation } from "../../../entities/project/model/projectFileMutation";
import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import type {
  ChatCompletionMessageInput,
  ChatCompletionRequest,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { isAbortError } from "../../../services/http/httpErrors";
import { updateChatInjectionPreview } from "../../../services/llm/updateChatInjectionPreview";
import type { ChatModelOption } from "./chatModelOption";
import { buildGenerationParams } from "../../conversation-runtime/model/generationParams";
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
  historyRevision: number | null;
  roleProjectId: string | null;
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
  historyRevision,
  roleProjectId,
}: UseChatInjectionPreviewDraftOptions) {
  let previewKey: string | null = null;
  if (projectId && activeSessionId && activeModel && settledDraft && !isActiveSessionStreaming
    && historyRevision !== null
    && settledDraft.projectId === projectId && settledDraft.sessionId === activeSessionId) {
    const draftContent = settledDraft.draft.trim();
    const hasReferences = hasConversationReferences(references);
    const nextUserContent = draftContent || hasReferences ? draftContent : null;

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

    const request: ChatCompletionRequest = {
      provider_id: activeModel.providerId,
      model_id: activeModel.modelId,
      project_id: projectId,
      session_id: activeSessionId,
      messages: requestMessages,
      malformed_tool_call_recovery_enabled: (
        activeSessionSettings.malformed_tool_call_recovery_enabled
      ),
      max_tool_calls: activeSessionSettings.max_tool_calls,
      generation: buildGenerationParams(activeSessionSettings, activeReasoningMode),
    };
    // List reloads replace settings/reference objects even when their values are
    // unchanged. Compare inputs, not object identity or the draft's publish count.
    // Include server-side context inputs so history/memory completion and role or
    // tool selection changes still update the preview without copying history here.
    previewKey = JSON.stringify({ request, settings: activeSessionSettings, historyRevision, roleProjectId },
      (_key, value) => value && typeof value === "object" && !Array.isArray(value)
        ? Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
        : value);
  }

  useEffect(() => {
    if (previewKey === null) return undefined;
    const { request } = JSON.parse(previewKey) as { request: ChatCompletionRequest };
    const controller = new AbortController();
    void updateChatInjectionPreview(request, { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted || !result.ok) return;
      publishProjectFileMutation({
        projectId: request.project_id!,
        node: buildInjectionPreviewFileNode(request.session_id!),
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
  }, [previewKey]);
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

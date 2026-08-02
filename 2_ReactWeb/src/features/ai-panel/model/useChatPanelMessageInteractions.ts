import { useCallback, useMemo, useState } from "react";

import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import type { ChatMessage } from "./chatMessage";
import type { ChatMessageItemInteractions } from "../ui/chatMessageItemTypes";

type UseChatPanelMessageInteractionsOptions = {
  activeSessionId: string | null;
  handleThinkingContentScroll: (messageId: string) => void;
  handleThinkingContentWheel: ChatMessageItemInteractions["onThinkingContentWheel"];
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  pauseThinkingAutoScroll: (messageId: string) => void;
  projectId: string | null;
  setThinkingContentRef: (messageId: string, node: HTMLDivElement | null) => void;
  updateSessionMessages: (
    projectId: string,
    sessionId: string,
    updater: (prev: ChatMessage[]) => ChatMessage[],
  ) => void;
  getVariantNavigation?: ChatMessageItemInteractions["getVariantNavigation"];
  onExportAssistantMessage?: ChatMessageItemInteractions["onExportAssistantMessage"];
  onForkUserMessage?: ChatMessageItemInteractions["onForkUserMessage"];
};

export function useChatPanelMessageInteractions({
  activeSessionId,
  handleThinkingContentScroll,
  handleThinkingContentWheel,
  onOpenReference,
  onPreviewHtmlCode,
  onSaveCodeBlock,
  pauseThinkingAutoScroll,
  projectId,
  setThinkingContentRef,
  updateSessionMessages,
  getVariantNavigation,
  onExportAssistantMessage,
  onForkUserMessage,
}: UseChatPanelMessageInteractionsOptions) {
  const [expandedUserMessageIds, setExpandedUserMessageIds] = useState<Set<string>>(() => new Set());

  const toggleThinking = useCallback((messageId: string) => {
    if (!projectId || !activeSessionId) return;
    updateSessionMessages(projectId, activeSessionId, (prev) => prev.map((message) =>
      message.id === messageId
        ? { ...message, isThinkingExpanded: !message.isThinkingExpanded }
        : message,
    ));
  }, [activeSessionId, projectId, updateSessionMessages]);

  const toggleUserMessageExpanded = useCallback((messageId: string) => {
    setExpandedUserMessageIds((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }, []);

  const saveCodeBlock = useCallback(async ({ code, language }: CodeBlockSavePayload) => {
    if (!onSaveCodeBlock) {
      throw new Error("当前会话未配置代码块保存能力。");
    }
    return onSaveCodeBlock({ code, language });
  }, [onSaveCodeBlock]);

  const messageInteractions = useMemo(() => ({
    getVariantNavigation,
    onExportAssistantMessage,
    onForkUserMessage,
    onOpenReference,
    onPreviewHtmlCode,
    onSaveCodeBlock: saveCodeBlock,
    onThinkingContentScroll: handleThinkingContentScroll,
    onThinkingContentWheel: handleThinkingContentWheel,
    onToggleThinking: toggleThinking,
    onToggleUserMessageExpanded: toggleUserMessageExpanded,
    onTouchMoveThinkingContent: pauseThinkingAutoScroll,
    projectId,
    setThinkingContentRef,
  }), [
    handleThinkingContentScroll,
    handleThinkingContentWheel,
    onOpenReference,
    onPreviewHtmlCode,
    pauseThinkingAutoScroll,
    projectId,
    saveCodeBlock,
    setThinkingContentRef,
    toggleThinking,
    toggleUserMessageExpanded,
    getVariantNavigation,
    onExportAssistantMessage,
    onForkUserMessage,
  ]);

  return {
    expandedUserMessageIds,
    messageInteractions,
  };
}

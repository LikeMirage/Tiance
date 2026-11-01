import { useCallback, useMemo, useState } from "react";

import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import type { ChatMessageItemInteractions } from "../ui/chatMessageItemTypes";
import type { LocalFileReference } from "../../../entities/local-file/model/localFileReference";
import type { MarkdownLocalFileActions } from "../../markdown-preview/ui/MarkdownLocalFileLink";

type UseChatPanelMessageInteractionsOptions = {
  handleThinkingContentScroll: (messageId: string) => void;
  handleThinkingContentWheel: ChatMessageItemInteractions["onThinkingContentWheel"];
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  localFileActions: MarkdownLocalFileActions;
  resolveLocalFileReference: (href: string) => LocalFileReference | null;
  pauseThinkingAutoScroll: (messageId: string) => void;
  projectId: string | null;
  setThinkingContentRef: (messageId: string, node: HTMLDivElement | null) => void;
  getVariantNavigation?: ChatMessageItemInteractions["getVariantNavigation"];
  onExportAssistantMessage?: ChatMessageItemInteractions["onExportAssistantMessage"];
  onForkUserMessage?: ChatMessageItemInteractions["onForkUserMessage"];
};

export function useChatPanelMessageInteractions({
  handleThinkingContentScroll,
  handleThinkingContentWheel,
  onOpenReference,
  onPreviewHtmlCode,
  onSaveCodeBlock,
  localFileActions,
  resolveLocalFileReference,
  pauseThinkingAutoScroll,
  projectId,
  setThinkingContentRef,
  getVariantNavigation,
  onExportAssistantMessage,
  onForkUserMessage,
}: UseChatPanelMessageInteractionsOptions) {
  const [expandedUserMessageIds, setExpandedUserMessageIds] = useState<Set<string>>(() => new Set());

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
    localFileActions,
    resolveLocalFileReference,
    onThinkingContentScroll: handleThinkingContentScroll,
    onThinkingContentWheel: handleThinkingContentWheel,
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
    localFileActions,
    resolveLocalFileReference,
    setThinkingContentRef,
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

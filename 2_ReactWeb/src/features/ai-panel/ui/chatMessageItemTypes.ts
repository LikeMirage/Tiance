import type { WheelEvent } from "react";

import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import type { ChatMessage } from "../model/chatMessage";
import type { LocalFileReference } from "../../../entities/local-file/model/localFileReference";
import type { MarkdownLocalFileActions } from "../../markdown-preview/ui/MarkdownLocalFileLink";

export type ChatMessageVariantNavigation = {
  count: number;
  currentPosition: number;
  onNext: () => void;
  onPrevious: () => void;
};

export type ChatMessageItemInteractions = {
  getVariantNavigation?: (message: ChatMessage) => ChatMessageVariantNavigation | null;
  localFileActions: MarkdownLocalFileActions;
  onExportAssistantMessage?: (message: ChatMessage) => void;
  onForkUserMessage?: (message: ChatMessage) => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock: (payload: CodeBlockSavePayload) => Promise<string>;
  onThinkingContentScroll: (messageId: string) => void;
  onThinkingContentWheel: (
    messageId: string,
    event: WheelEvent<HTMLDivElement>,
  ) => void;
  onToggleThinking: (messageId: string) => void;
  onToggleUserMessageExpanded: (messageId: string) => void;
  onTouchMoveThinkingContent: (messageId: string) => void;
  projectId: string | null;
  resolveLocalFileReference: (href: string) => LocalFileReference | null;
  setThinkingContentRef: (messageId: string, node: HTMLDivElement | null) => void;
};

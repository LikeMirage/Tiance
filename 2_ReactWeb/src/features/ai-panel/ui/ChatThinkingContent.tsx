import { useCallback } from "react";
import { CaretDown } from "@phosphor-icons/react";

import { SlidingContent } from "../../../shared/ui/sliding-content/SlidingContent";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { useChatProcessFolds } from "../model/chatProcessFoldState";
import type { ChatMessageItemInteractions } from "./chatMessageItemTypes";

// Approximately four lines at the chat's normal text size.
const THINKING_PREVIEW_HEIGHT = 96;

/** The existing thinking body has a compact automatic state and a full manual state. */
export function ChatThinkingContent({ content, foldKey, interactions, isExpanded, isLiveSegment, isStreaming, messageId }: {
  content: string;
  foldKey: string;
  interactions: ChatMessageItemInteractions;
  isExpanded: boolean;
  isLiveSegment: boolean;
  isStreaming: boolean;
  messageId: string;
}) {
  const { states, setExpanded } = useChatProcessFolds();
  const fullyExpanded = states[foldKey] === true;
  const { setThinkingContentRef } = interactions;
  const setContentRef = useCallback((node: HTMLDivElement | null) => {
    if (isLiveSegment && isExpanded) setThinkingContentRef(messageId, node);
  }, [isLiveSegment, isExpanded, messageId, setThinkingContentRef]);

  return <SlidingContent expanded={isExpanded}>
    <SlidingContent
      expanded={fullyExpanded}
      collapsedHeight={THINKING_PREVIEW_HEIGHT}
      ref={setContentRef}
      className={[
        "chat-msg__thinking-content",
        fullyExpanded ? "chat-msg__thinking-content--full" : "chat-msg__thinking-content--preview",
        isStreaming ? "chat-msg__thinking-content--streaming" : "",
      ].filter(Boolean).join(" ")}
      onScroll={() => interactions.onThinkingContentScroll(messageId)}
      onWheel={(event) => interactions.onThinkingContentWheel(messageId, event)}
      onTouchMove={() => interactions.onTouchMoveThinkingContent(messageId)}
    >
      <LazyMarkdownPreview
        content={content}
        isStreaming={isStreaming}
        renderStrategy="responsive"
        mathErrorMode="neutral"
        localFileActions={interactions.localFileActions}
        onPreviewHtmlCode={interactions.onPreviewHtmlCode}
        onSaveCodeBlock={interactions.onSaveCodeBlock}
        resolveLocalFileReference={interactions.resolveLocalFileReference}
      />
    </SlidingContent>
    {!fullyExpanded ? <button type="button" className="chat-msg__thinking-expand"
      aria-label="展开全部思考" title="展开全部思考"
      onClick={() => setExpanded(foldKey, true)}>
      <CaretDown size={16} aria-hidden="true" />
    </button> : null}
  </SlidingContent>;
}

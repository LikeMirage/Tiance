import { CaretDown } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { useDesktopFileDropTarget } from "../../desktop-shell/model/useDesktopFileDropTarget";
import { ChatComposerAddMenu } from "./ChatComposerAddMenu";
import { UserMessageHistoryMenu, type UserMessageHistoryState } from "./UserMessageHistoryMenu";
import { ChatModelPicker } from "./ChatComposerModelPicker";
import { ChatComposerReasoningControl } from "./ChatComposerReasoningControl";
import { ChatComposerReferences } from "./ChatComposerReferences";
import { ComposerSubmitButton } from "./ChatComposerSubmitButton";
import { ChatComposerTextArea } from "./ChatComposerTextArea";
import type {
  ChatComposerGenerationState,
  ChatComposerInputState,
  ChatComposerLayoutState,
  ChatComposerModelPickerState,
  ChatComposerReasoningState,
  ChatComposerUsageState,
} from "./ChatComposerTypes";
import { ChatUsagePopover } from "./ChatComposerUsagePopover";
import {
  handleChatComposerReferenceDrop,
  hasChatComposerReferenceDrag,
} from "./chatComposerDrop";

export type {
  ChatComposerGenerationState,
  ChatComposerInputState,
  ChatComposerLayoutState,
  ChatComposerModelPickerState,
  ChatComposerReasoningState,
  ChatComposerUsageState,
  ChatComposerUploadStatus,
} from "./ChatComposerTypes";

type ChatComposerProps = {
  userMessageHistory?: UserMessageHistoryState;
  conversationActions?: ReactNode;
  generation: ChatComposerGenerationState;
  input: ChatComposerInputState;
  layout: ChatComposerLayoutState;
  modelPicker: ChatComposerModelPickerState;
  onScrollToBottom: () => void;
  reasoning: ChatComposerReasoningState;
  usage: ChatComposerUsageState;
};

export function ChatComposer({
  userMessageHistory,
  conversationActions,
  generation,
  input,
  layout,
  modelPicker,
  onScrollToBottom,
  reasoning,
  usage,
}: ChatComposerProps) {
  const [isReferenceDragOver, setIsReferenceDragOver] = useState(false);
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  useEffect(() => {
    setIsAddMenuOpen(false);
    setIsHistoryOpen(false);
  }, [input.externalFileDropScopeKey]);
  const { isFileDragOver, targetRef } = useDesktopFileDropTarget({
    onFileDrop: input.onExternalFileDrop,
    scopeKey: input.externalFileDropScopeKey,
  });
  const isDragOver = isReferenceDragOver || isFileDragOver;
  const composerClassName = layout.isResizing
    ? `ai-panel__composer ai-panel__composer--resizing${isDragOver ? " ai-panel__composer--drag-over" : ""}`
    : `ai-panel__composer${isDragOver ? " ai-panel__composer--drag-over" : ""}`;

  return (
    <footer
      ref={targetRef}
      className={composerClassName}
      style={{ "--chat-composer-height": `${layout.height}px` } as CSSProperties}
      onDragEnter={(event) => {
        if (!hasChatComposerReferenceDrag(event, input)) return;
        event.preventDefault();
        setIsReferenceDragOver(true);
      }}
      onDragOver={(event) => {
        if (!hasChatComposerReferenceDrag(event, input)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setIsReferenceDragOver(true);
      }}
      onDragLeave={(event) => {
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        setIsReferenceDragOver(false);
      }}
      onDrop={(event) => {
        if (!hasChatComposerReferenceDrag(event, input)) return;
        event.preventDefault();
        setIsReferenceDragOver(false);
        handleChatComposerReferenceDrop(event, input);
      }}
    >
      <div
        className="ai-panel__composer-resize-handle"
        role="separator"
        aria-label="调整输入区高度"
        onPointerDown={layout.onResizeStart}
      />
      <ChatComposerReferences
        references={input.references}
        onRemoveFile={input.onRemoveFileReference}
        onRemoveImage={input.onRemoveImageReference}
        onRemoveText={input.onRemoveTextReference}
        onOpenReference={input.onOpenReference}
      />
      <div className="ai-panel__composer-toolbar">
        <ChatComposerAddMenu
          key={input.projectId}
          projectId={input.projectId}
          projectCatalog={input.projectReferenceCatalog}
          onReferenceExternalPath={input.onReferenceExternalPath}
          isOpen={isAddMenuOpen}
          onOpenChange={(nextOpen) => {
            if (nextOpen) {
              modelPicker.onToggleOpen(() => false);
              setIsHistoryOpen(false);
            }
            setIsAddMenuOpen(nextOpen);
          }}
          onSelectFiles={input.onSelectExternalFiles}
        />
        {conversationActions}
        <UserMessageHistoryMenu history={userMessageHistory} isOpen={isHistoryOpen}
          onOpenReference={input.onOpenReference}
          onOpenChange={(open) => {
            if (open) { setIsAddMenuOpen(false); modelPicker.onToggleOpen(() => false); }
            setIsHistoryOpen(open);
          }} />
        <button
          className="ai-panel__composer-scroll-bottom"
          type="button"
          aria-label="回到底部"
          title="回到底部"
          onClick={onScrollToBottom}
        >
          <CaretDown size={18} weight="bold" aria-hidden="true" />
        </button>
      </div>
      <div className="ai-panel__composer-box">
        <ChatComposerTextArea input={input} />
        <div className="ai-panel__composer-actions">
          <ChatModelPicker
            modelPicker={{
              ...modelPicker,
              onToggleOpen: (updater) => {
                setIsAddMenuOpen(false);
                setIsHistoryOpen(false);
                modelPicker.onToggleOpen(updater);
              },
            }}
          />
          <ChatComposerReasoningControl reasoning={reasoning} />
          <ChatUsagePopover usage={usage} />
          <ComposerSubmitButton generation={generation} input={input} />
        </div>
      </div>
    </footer>
  );
}

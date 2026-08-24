import { useState } from "react";
import type { CSSProperties } from "react";

import { useDesktopFileDropTarget } from "../../desktop-shell/model/useDesktopFileDropTarget";
import { ChatComposerAddMenu } from "./ChatComposerAddMenu";
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
  handleChatComposerProjectFileDrop,
  hasDraggedProjectFile,
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
  generation: ChatComposerGenerationState;
  input: ChatComposerInputState;
  layout: ChatComposerLayoutState;
  modelPicker: ChatComposerModelPickerState;
  reasoning: ChatComposerReasoningState;
  usage: ChatComposerUsageState;
};

export function ChatComposer({
  generation,
  input,
  layout,
  modelPicker,
  reasoning,
  usage,
}: ChatComposerProps) {
  const [isProjectFileDragOver, setIsProjectFileDragOver] = useState(false);
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const { isFileDragOver, targetRef } = useDesktopFileDropTarget({
    onFileDrop: input.onExternalFileDrop,
    scopeKey: input.externalFileDropScopeKey,
  });
  const isDragOver = isProjectFileDragOver || isFileDragOver;
  const composerClassName = layout.isResizing
    ? `ai-panel__composer ai-panel__composer--resizing${isDragOver ? " ai-panel__composer--drag-over" : ""}`
    : `ai-panel__composer${isDragOver ? " ai-panel__composer--drag-over" : ""}`;

  return (
    <footer
      ref={targetRef}
      className={composerClassName}
      style={{ "--chat-composer-height": `${layout.height}px` } as CSSProperties}
      onDragEnter={(event) => {
        if (!hasDraggedProjectFile(event)) return;
        event.preventDefault();
        setIsProjectFileDragOver(true);
      }}
      onDragOver={(event) => {
        if (!hasDraggedProjectFile(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setIsProjectFileDragOver(true);
      }}
      onDragLeave={(event) => {
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        setIsProjectFileDragOver(false);
      }}
      onDrop={(event) => {
        if (!hasDraggedProjectFile(event)) return;
        event.preventDefault();
        setIsProjectFileDragOver(false);
        handleChatComposerProjectFileDrop(event, input);
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
      <div className="ai-panel__composer-box">
        <ChatComposerTextArea input={input} />
        <div className="ai-panel__composer-actions">
          <ChatComposerAddMenu
            isOpen={isAddMenuOpen}
            onOpenChange={(nextOpen) => {
              if (nextOpen) modelPicker.onToggleOpen(() => false);
              setIsAddMenuOpen(nextOpen);
            }}
            onSelectFiles={input.onSelectExternalFiles}
          />
          <ChatModelPicker
            modelPicker={{
              ...modelPicker,
              onToggleOpen: (updater) => {
                setIsAddMenuOpen(false);
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

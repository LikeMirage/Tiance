import { CaretDown, Microphone } from "@phosphor-icons/react";
import { useId, useLayoutEffect, useState, useRef } from "react";
import type { SpeechInputState } from "../model/useSpeechInput";
import { ChatSpeechRecording } from "./ChatSpeechRecording";
import type { CSSProperties } from "react";
import type { ConversationExportRequest } from "../../conversation-export/model/conversationExport";
import { ConversationExportDialog } from "../../conversation-export/ui/ConversationExportDialog";
import { ChatConversationActions } from "./ChatConversationActions";

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
  speech?: SpeechInputState;
  userMessageHistory?: UserMessageHistoryState;
  conversationActions?: {
    exportRequest: ConversationExportRequest | null;
    onSelectDirectory?: () => Promise<string | null>;
    onOpenOverview?: () => void;
    onOpenBranches?: () => void;
  };
  generation: ChatComposerGenerationState;
  input: ChatComposerInputState;
  layout: ChatComposerLayoutState;
  modelPicker: ChatComposerModelPickerState;
  isBottomFollowLocked: boolean;
  onScrollToBottom: (lockRequested: boolean) => void;
  reasoning: ChatComposerReasoningState;
  usage: ChatComposerUsageState;
};

export function ChatComposer({
  speech,
  userMessageHistory,
  conversationActions,
  generation,
  input,
  layout,
  modelPicker,
  isBottomFollowLocked,
  onScrollToBottom,
  reasoning,
  usage,
}: ChatComposerProps) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [isReferenceDragOver, setIsReferenceDragOver] = useState(false);
  const [activePanel, setActivePanel] = useState<"references" | "export" | "history" | "models" | "reasoning" | "usage" | null>(null);
  const exportPanelId = useId();
  const exportRequest = conversationActions?.exportRequest;
  const canOpenExport = !!exportRequest;
  const [panelContainer, setPanelContainer] = useState<HTMLDivElement | null>(null);
  const previousPanel = useRef(activePanel);
  const scopeKey = JSON.stringify([input.projectId, modelPicker.activeSession?.session_id, input.externalFileDropScopeKey]);
  const previousScope = useRef(scopeKey);
  // The textarea stays mounted while browsing panels, preserving draft, selection and scroll.
  useLayoutEffect(() => {
    const scopeChanged = previousScope.current !== scopeKey;
    previousScope.current = scopeKey;
    if (scopeChanged || speech?.view || (activePanel === "reasoning" && !reasoning.isVisible) || (activePanel === "export" && !canOpenExport)) {
      setActivePanel(null);
    } else if (previousPanel.current && !activePanel) {
      inputRef.current?.focus({ preventScroll: true });
    }
    previousPanel.current = scopeChanged || speech?.view ? null : activePanel;
  }, [activePanel, scopeKey, speech?.view, reasoning.isVisible, canOpenExport]);
  const changePanel = (panel: NonNullable<typeof activePanel>, open: boolean) => {
    if (open && speech?.view) return;
    setActivePanel(open ? panel : null);
  };
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
          isOpen={activePanel === "references"}
          panelContainer={panelContainer}
          onOpenChange={open => changePanel("references", open)}
          onSelectFiles={input.onSelectExternalFiles}
        />
        {conversationActions && <ChatConversationActions
          exportPanelId={exportPanelId}
          exportOpen={activePanel === "export"}
          onExport={exportRequest && !speech?.view ? () => changePanel("export", activePanel !== "export") : undefined}
          onOpenOverview={conversationActions.onOpenOverview}
          onOpenBranches={conversationActions.onOpenBranches}
        />}
        {activePanel === "export" && exportRequest && <ConversationExportDialog
          key={`export:${scopeKey}`} embedded={{ container: panelContainer, id: exportPanelId }}
          request={exportRequest} onSelectDirectory={conversationActions?.onSelectDirectory}
          onClose={() => changePanel("export", false)}
        />}
        <UserMessageHistoryMenu history={userMessageHistory} isOpen={activePanel === "history"}
          panelContainer={panelContainer} onOpenReference={input.onOpenReference}
          onOpenChange={open => changePanel("history", open)} />
        <button
          className="ai-panel__composer-scroll-bottom"
          type="button"
          aria-label="回到底部"
          aria-pressed={isBottomFollowLocked}
          aria-controls="ai-panel-message-scroll-region"
          title={isBottomFollowLocked ? "已锁定底部跟随，单击解锁" : "回到底部，双击锁定跟随（Shift + Enter）"}
          onClick={(event) => onScrollToBottom(event.detail === 2)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || !event.shiftKey) return;
            event.preventDefault();
            if (!event.repeat) onScrollToBottom(true);
          }}
        >
          <CaretDown size={18} weight="bold" aria-hidden="true" />
        </button>
      </div>
      <div className="ai-panel__composer-box">
        {speech?.view ? <ChatSpeechRecording speech={speech} /> : <>
        <ChatComposerTextArea input={input} inputRef={inputRef} hidden={activePanel !== null} />
        <div ref={setPanelContainer} className="ai-panel__composer-panel-slot" hidden={activePanel === null} />
        <div className="ai-panel__composer-actions">
          <ChatModelPicker modelPicker={modelPicker} isOpen={activePanel === "models"}
            panelContainer={panelContainer} onOpenChange={open => changePanel("models", open)} />
          <ChatComposerReasoningControl reasoning={reasoning} isOpen={activePanel === "reasoning"}
            panelContainer={panelContainer} onOpenChange={open => changePanel("reasoning", open)} />
          <ChatUsagePopover usage={usage} isOpen={activePanel === "usage"}
            panelContainer={panelContainer} onOpenChange={open => changePanel("usage", open)} />
          {speech && <button type="button" className="ai-panel__speech-start"
            disabled={!speech.available}
            title={speech.available ? "语音输入（录音将上传云端识别）" : "语音输入需要麦克风权限及 HTTPS 或本机访问"}
            aria-label="语音输入"
            onPointerDown={(event) => event.preventDefault()}
            onClick={() => speech.start(document.activeElement === inputRef.current ? inputRef.current?.selectionEnd ?? null : null)}>
            <Microphone size={18} aria-hidden="true" />
          </button>}
          <ComposerSubmitButton generation={generation} input={input} />
        </div>
        </>}
      </div>
    </footer>
  );
}

import type { PointerEvent, RefObject } from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import type {
  EditorReferenceViewerPayload,
} from "../../../entities/editor/model/editorReference";
import type { ConversationMessageReferences } from "../../../entities/llm-chat/model/chatCompletion";
import type { ProjectFileDragData } from "../../../entities/project/model/projectFileDragData";
import type { OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import type { ConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";
import type { DesktopFileDropEvent } from "../../desktop-shell/model/desktopFileDropBridge";
import type { ChatModelOption } from "../model/chatModelOption";
import type {
  UsageDisplaySummary,
  UsageScopeOption,
} from "../model/usageSummary";

export type ChatComposerInputState = {
  canSend: boolean;
  draft: string;
  externalFileDropScopeKey?: string | null;
  references?: ConversationMessageReferences;
  onDraftChange: (value: string) => void;
  onExternalFileDrop?: (event: DesktopFileDropEvent) => void;
  onDropProjectFile?: (file: ProjectFileDragData) => void;
  onPasteFiles?: (files: File[]) => Promise<void>;
  onRemoveFileReference?: (referenceId: string) => void;
  onRemoveImageReference?: (referenceId: string) => void;
  onRemoveTextReference?: (referenceId: string) => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onSend: () => void;
  uploadStatus?: ChatComposerUploadStatus;
};

export type ChatComposerUploadStatus = {
  kind: "idle" | "saving" | "error";
  message: string | null;
};

export type ChatComposerLayoutState = {
  height: number;
  isResizing: boolean;
  onResizeStart: (event: PointerEvent<HTMLElement>) => void;
};

export type ChatComposerModelPickerState = {
  activeModel: ChatModelOption | null;
  activeSession: ConversationSession | null;
  isDisabled: boolean;
  isLoading: boolean;
  isOpen: boolean;
  loadError: string | null;
  menuRef: RefObject<HTMLDivElement | null>;
  models: ChatModelOption[];
  onReload: () => Promise<void>;
  onSelect: (model: ChatModelOption) => void;
  onToggleOpen: (updater: (current: boolean) => boolean) => void;
};

export type ChatComposerReasoningState = {
  activeMode: DsLlmReasoningMode;
  isVisible: boolean;
  onChange: (mode: DsLlmReasoningMode | null) => void;
  options: Array<OptionSelectItem<DsLlmReasoningMode>>;
};

export type ChatComposerUsageState = {
  areaRef: RefObject<HTMLDivElement | null>;
  contextTokens: number | null;
  contextTokensEstimated: boolean;
  isOpen: boolean;
  onSelectScope: (value: string) => void;
  onToggleOpen: (updater: (current: boolean) => boolean) => void;
  scopeKey: string;
  scopeOptions: UsageScopeOption[];
  selected: UsageDisplaySummary | undefined;
  session: ConversationUsageSummary | undefined;
};

export type ChatComposerGenerationState = {
  isStreaming: boolean;
  onStop: () => void;
};

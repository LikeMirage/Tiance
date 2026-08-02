import { memo } from "react";

import { ChatPanelController } from "./ChatPanelController";
import type {
  EditorExternalPathReferenceRequest,
  EditorReferenceViewerPayload,
} from "../../../entities/editor/model/editorReference";
import type { ConversationMessageReferences } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ProjectFileDragData,
  ProjectFileReferenceRequest,
} from "../../../entities/project/model/projectFileDragData";
import type { ConversationDataFileName } from "./ChatDataDashboardPanel";
import type {
  ChatPanelSessionSelectionRequest,
  ChatPanelSessionSelectionResult,
} from "../model/chatSessionSelectionRequest";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import type { ClientToolRegistration } from "../../client-tools/model/clientToolBridge";
import "./ai-panel.css";

export type { ChatPanelSessionSelectionRequest } from "../model/chatSessionSelectionRequest";

type Props = {
  projectId: string | null;
  activeConversationDataFile?: ConversationDataFileName | null;
  clientToolRegistrations?: readonly ClientToolRegistration[];
  composerInitialHeight?: number;
  isActive?: boolean;
  isImageReferenceUploadPending?: boolean;
  onActiveUserMessageChange?: (
    projectId: string,
    sessionId: string,
    messageId: string | null,
  ) => void;
  onActiveSessionChange?: (projectId: string, sessionId: string | null) => void;
  onSessionSelectionResult?: (result: ChatPanelSessionSelectionResult) => void;
  onComposerHeightCommit?: (height: number) => void;
  references?: ConversationMessageReferences;
  onOpenConversationDataFile?: (sessionId: string, fileName: ConversationDataFileName) => void;
  onOpenConversationBranches?: () => void;
  onOpenConversationOverview?: () => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onPreviewHtmlCode?: (html: string) => void;
  onClearReferences?: () => void;
  onDraftReferencesChange?: (references: ConversationMessageReferences) => void;
  onReferenceExternalPath?: (reference: EditorExternalPathReferenceRequest) => void;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  onRemoveFileReference?: (referenceId: string) => void;
  onRemoveImageReference?: (referenceId: string) => void;
  onRemoveTextReference?: (referenceId: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  onSelectExportDirectory?: () => Promise<string | null>;
  preferredSessionId?: string | null;
  projectFileReferenceRequest?: ProjectFileReferenceRequest | null;
  projectRootPath?: string;
  sessionSelectionError?: string | null;
  sessionSelectionRequest?: ChatPanelSessionSelectionRequest | null;
};

export const ChatPanel = memo(function ChatPanel(props: Props) {
  return <ChatPanelController {...props} />;
});

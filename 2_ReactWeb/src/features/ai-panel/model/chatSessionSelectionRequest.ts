export type ChatPanelSessionSelectionRequest = {
  messageId?: string;
  projectId: string;
  requestId: number;
  sessionId: string;
};

export type ChatPanelSessionSelectionResult = {
  activeSessionId: string | null;
  message?: string;
  projectId: string;
  requestId: number;
  sessionId: string;
  status: "failed" | "missing";
};

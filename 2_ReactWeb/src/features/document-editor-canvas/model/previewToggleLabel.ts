export function getPreviewToggleLabel({
  isCompressionLog,
  isConversationIndex,
  isConversationInjectionPreview,
  isConversationMessages,
  isConversationSession,
  isGlobalMemory,
  isHtml,
  isMarkdown,
  isProjectMemory,
  previewOpen,
}: {
  isCompressionLog: boolean;
  isConversationIndex: boolean;
  isConversationInjectionPreview: boolean;
  isConversationMessages: boolean;
  isConversationSession: boolean;
  isGlobalMemory: boolean;
  isHtml: boolean;
  isMarkdown: boolean;
  isProjectMemory: boolean;
  previewOpen: boolean;
}) {
  if (isProjectMemory || isGlobalMemory) {
    return previewOpen ? "查看原文" : "管理面板";
  }
  if (isConversationIndex || isConversationSession) {
    return previewOpen ? "查看原文" : "管理面板";
  }
  if (isConversationMessages) {
    return previewOpen ? "查看原文" : "管理面板";
  }
  if (isConversationInjectionPreview) {
    return previewOpen ? "查看原文" : "管理面板";
  }
  if (isCompressionLog) {
    return previewOpen ? "查看原文" : "管理面板";
  }
  if (isHtml) {
    return previewOpen ? "返回" : "预览";
  }
  if (isMarkdown) {
    return previewOpen ? "关闭" : "预览 Markdown";
  }
  return previewOpen ? "返回" : "预览";
}

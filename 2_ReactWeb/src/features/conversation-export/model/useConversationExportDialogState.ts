import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildConversationExportBaseName,
  CONVERSATION_EXPORT_FORMATS,
  DEFAULT_CONVERSATION_EXPORT_CONTENT,
  getConversationExportContentOptions,
  getDefaultConversationExportRange,
  type ConversationExportContentKey,
  type ConversationExportContentSelection,
  type ConversationExportFormat,
  type ConversationExportRange,
  type ConversationExportRequest,
} from "./conversationExport";
import { submitConversationExport } from "./submitConversationExport";

export type ConversationExportSettingsTab = "length" | "content";

type ConversationExportDialogStateOptions = {
  directoryErrorMessage: string;
  fallbackExportError: string;
  onClose: () => void;
  onSelectDirectory: () => Promise<string | null>;
  request: ConversationExportRequest;
};

export function useConversationExportDialogState({
  directoryErrorMessage,
  fallbackExportError,
  onClose,
  onSelectDirectory,
  request,
}: ConversationExportDialogStateOptions) {
  const isMountedRef = useRef(true);
  const [format, setFormatState] = useState<ConversationExportFormat>("docx");
  const [baseName, setBaseNameState] = useState(() => buildConversationExportBaseName(request));
  const [directory, setDirectoryState] = useState(request.initialDirectory);
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [isSelectingDirectory, setIsSelectingDirectory] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [settingsTab, setSettingsTab] = useState<ConversationExportSettingsTab>("length");
  const [range, setRange] = useState<ConversationExportRange>(
    () => getDefaultConversationExportRange(request),
  );
  const [contentSelection, setContentSelection] = useState<ConversationExportContentSelection>(
    () => ({ ...DEFAULT_CONVERSATION_EXPORT_CONTENT }),
  );
  const selectedFormat = useMemo(
    () => CONVERSATION_EXPORT_FORMATS.find((item) => item.format === format)
      ?? CONVERSATION_EXPORT_FORMATS[0],
    [format],
  );
  const contentOptions = useMemo(
    () => getConversationExportContentOptions(format),
    [format],
  );
  const canExport = Boolean(
    baseName.trim()
    && directory.trim()
    && contentOptions.some((option) => contentSelection[option]),
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const setFormat = (value: ConversationExportFormat) => {
    setExportError(null);
    setFormatState(value);
  };
  const setBaseName = (value: string) => {
    setExportError(null);
    setBaseNameState(value);
  };
  const setDirectory = (value: string) => {
    setDirectoryError(null);
    setExportError(null);
    setDirectoryState(value);
  };
  const toggleContentOption = (option: ConversationExportContentKey) => {
    setExportError(null);
    setContentSelection((current) => ({
      ...current,
      [option]: !current[option],
    }));
  };
  const selectDirectory = async () => {
    if (isSelectingDirectory || isExporting) return;
    setDirectoryError(null);
    setIsSelectingDirectory(true);
    try {
      const selectedDirectory = await onSelectDirectory();
      if (isMountedRef.current && selectedDirectory) setDirectory(selectedDirectory);
    } catch {
      if (isMountedRef.current) setDirectoryError(directoryErrorMessage);
    } finally {
      if (isMountedRef.current) setIsSelectingDirectory(false);
    }
  };
  const exportConversation = async (openAfterExport: boolean) => {
    if (!canExport || isExporting) return;
    setExportError(null);
    setIsExporting(true);
    try {
      const result = await submitConversationExport(request, {
        baseName: baseName.trim(),
        content: contentSelection,
        directory: directory.trim(),
        format,
        openAfterExport,
        range,
      });
      if (result.warnings.length > 0) {
        console.warn("Conversation export completed with warnings.", result.warnings);
      }
      if (!isMountedRef.current) return;
      setIsExporting(false);
      onClose();
    } catch (error) {
      if (!isMountedRef.current) return;
      setExportError(
        error instanceof Error && error.message.trim()
          ? error.message
          : fallbackExportError,
      );
      setIsExporting(false);
    }
  };

  return {
    baseName,
    canExport,
    contentOptions,
    contentSelection,
    directory,
    directoryError,
    exportConversation,
    exportError,
    format,
    isExporting,
    isSelectingDirectory,
    range,
    selectDirectory,
    selectedFormat,
    setBaseName,
    setDirectory,
    setFormat,
    setRange,
    setSettingsTab,
    settingsTab,
    toggleContentOption,
  };
}

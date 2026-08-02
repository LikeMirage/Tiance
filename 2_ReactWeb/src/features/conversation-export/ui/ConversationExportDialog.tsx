import {
  FileDoc,
  FileCode,
  FileHtml,
  FileTxt,
  FolderOpen,
  MarkdownLogo,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../../../shared/i18n";
import {
  CONVERSATION_EXPORT_FORMATS,
  type ConversationExportFormat,
  type ConversationExportRange,
  type ConversationExportRequest,
} from "../model/conversationExport";
import { useConversationExportDialogState } from "../model/useConversationExportDialogState";
import "./conversation-export-dialog.css";

type ConversationExportDialogProps = {
  onClose: () => void;
  onSelectDirectory: () => Promise<string | null>;
  request: ConversationExportRequest;
};

const FORMAT_ICONS: Record<ConversationExportFormat, Icon> = {
  docx: FileDoc,
  markdown: MarkdownLogo,
  txt: FileTxt,
  html: FileHtml,
  json: FileCode,
};

const MESSAGE_RANGE_OPTIONS: Exclude<ConversationExportRange, "conversation">[] = [
  "message",
  "through-message",
  "from-message",
];

export function ConversationExportDialog({
  onClose,
  onSelectDirectory,
  request,
}: ConversationExportDialogProps) {
  const { t } = useI18n();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const state = useConversationExportDialogState({
    directoryErrorMessage: t("aiPanel.exportDialog.directoryError"),
    fallbackExportError: t("aiPanel.exportDialog.requestError"),
    onClose,
    onSelectDirectory,
    request,
  });
  const {
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
  } = state;

  useEffect(() => {
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isExporting) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isExporting, onClose]);

  return createPortal(
    <div
      className="conversation-export-dialog__backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isExporting) onClose();
      }}
    >
      <section
        className="conversation-export-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="conversation-export-dialog-title"
      >
        <header className="conversation-export-dialog__header">
          <div>
            <h3 id="conversation-export-dialog-title">{t("aiPanel.exportDialog.title")}</h3>
          </div>
          <button
            ref={closeButtonRef}
            className="conversation-export-dialog__icon-button"
            type="button"
            aria-label={t("aiPanel.exportDialog.close")}
            title={t("aiPanel.exportDialog.close")}
            disabled={isExporting}
            onClick={onClose}
          >
            <X size={16} weight="regular" aria-hidden="true" />
          </button>
        </header>

        <div className="conversation-export-dialog__content">
          <nav className="conversation-export-dialog__formats" aria-label={t("aiPanel.exportDialog.formatList")}>
            {CONVERSATION_EXPORT_FORMATS.map((item) => {
              const FormatIcon = FORMAT_ICONS[item.format];
              const isActive = item.format === format;
              return (
                <button
                  className={isActive
                    ? "conversation-export-dialog__format conversation-export-dialog__format--active"
                    : "conversation-export-dialog__format"}
                  type="button"
                  aria-pressed={isActive}
                  disabled={isExporting}
                  onClick={() => setFormat(item.format)}
                  key={item.format}
                >
                  <FormatIcon size={19} weight="regular" aria-hidden="true" />
                  <span>{formatLabel(item.format)}</span>
                  <small>{item.extension}</small>
                </button>
              );
            })}
          </nav>

          <section className="conversation-export-dialog__details">
            <header className="conversation-export-dialog__details-header">
              <span>{t("aiPanel.exportDialog.fileName")}</span>
              <span className="conversation-export-dialog__filename">
                <input
                  type="text"
                  value={baseName}
                  maxLength={120}
                  disabled={isExporting}
                  onChange={(event) => setBaseName(event.target.value)}
                />
                <small>{selectedFormat.extension}</small>
              </span>
            </header>

            <div className="conversation-export-dialog__settings">
              <label className="conversation-export-dialog__setting conversation-export-dialog__setting--directory">
                <span>{t("aiPanel.exportDialog.directory")}</span>
                <span className="conversation-export-dialog__directory-control">
                  <input
                    type="text"
                    value={directory}
                    disabled={isExporting}
                    onChange={(event) => setDirectory(event.target.value)}
                  />
                  <button
                    className="conversation-export-dialog__icon-button"
                    type="button"
                    aria-label={t("aiPanel.exportDialog.chooseDirectory")}
                    title={t("aiPanel.exportDialog.chooseDirectory")}
                    disabled={isSelectingDirectory || isExporting}
                    onClick={() => {
                      void selectDirectory();
                    }}
                  >
                    <FolderOpen size={16} weight="regular" aria-hidden="true" />
                  </button>
                </span>
                {directoryError ? (
                  <small className="conversation-export-dialog__field-error" role="status">
                    {directoryError}
                  </small>
                ) : null}
              </label>

              <div
                className="conversation-export-dialog__settings-tabs"
                role="tablist"
                aria-label={t("aiPanel.exportDialog.settingsTabs.aria")}
              >
                {(["length", "content"] as const).map((tab) => {
                  const isActive = settingsTab === tab;
                  return (
                    <button
                      className={isActive
                        ? "conversation-export-dialog__settings-tab conversation-export-dialog__settings-tab--active"
                        : "conversation-export-dialog__settings-tab"}
                      id={`conversation-export-dialog-tab-${tab}`}
                      type="button"
                      role="tab"
                      aria-controls={`conversation-export-dialog-panel-${tab}`}
                      aria-selected={isActive}
                      disabled={isExporting}
                      onClick={() => setSettingsTab(tab)}
                      key={tab}
                    >
                      {t(`aiPanel.exportDialog.settingsTabs.${tab}`)}
                    </button>
                  );
                })}
              </div>

              {settingsTab === "length" ? (
                <div
                  className="conversation-export-dialog__settings-panel"
                  id="conversation-export-dialog-panel-length"
                  role="tabpanel"
                  aria-labelledby="conversation-export-dialog-tab-length"
                >
                  {request.scope === "conversation" ? (
                    <RangeOption
                      checked
                      label={t("aiPanel.exportDialog.range.conversation")}
                    />
                  ) : (
                    <div className="conversation-export-dialog__range-options">
                      {MESSAGE_RANGE_OPTIONS.map((option) => (
                        <RangeOption
                          checked={range === option}
                          label={t(`aiPanel.exportDialog.range.${rangeLabelKey(option)}`)}
                          name="conversation-export-range"
                          disabled={isExporting}
                          onChange={() => setRange(option)}
                          key={option}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div
                  className="conversation-export-dialog__settings-panel"
                  id="conversation-export-dialog-panel-content"
                  role="tabpanel"
                  aria-labelledby="conversation-export-dialog-tab-content"
                >
                  <div className="conversation-export-dialog__content-options">
                    {contentOptions.map((option) => (
                      <label
                        className="conversation-export-dialog__content-option"
                        title={t(`aiPanel.exportDialog.content.${option}.description`)}
                        key={option}
                      >
                        <strong>{t(`aiPanel.exportDialog.content.${option}.label`)}</strong>
                        <input
                          type="checkbox"
                          checked={contentSelection[option]}
                          disabled={isExporting}
                          onChange={() => toggleContentOption(option)}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}

            </div>

            <footer className="conversation-export-dialog__footer">
              {exportError ? (
                <span className="conversation-export-dialog__submit-error" role="alert">
                  {exportError}
                </span>
              ) : null}
              <button type="button" disabled={isExporting} onClick={onClose}>
                {t("aiPanel.exportDialog.cancel")}
              </button>
              <button
                type="button"
                disabled={!canExport || isExporting}
                onClick={() => { void exportConversation(false); }}
              >
                {isExporting
                  ? t("aiPanel.exportDialog.exporting")
                  : t("aiPanel.exportDialog.export")}
              </button>
              <button
                className="conversation-export-dialog__primary"
                type="button"
                disabled={!canExport || isExporting}
                onClick={() => { void exportConversation(true); }}
              >
                {isExporting
                  ? t("aiPanel.exportDialog.exporting")
                  : t("aiPanel.exportDialog.exportAndOpen")}
              </button>
            </footer>
          </section>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function formatLabel(format: ConversationExportFormat) {
  if (format === "docx") return "Word";
  if (format === "markdown") return "Markdown";
  if (format === "txt") return "TXT";
  if (format === "html") return "HTML";
  return "JSON";
}

function RangeOption({
  checked,
  disabled = false,
  label,
  name,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  name?: string;
  onChange?: () => void;
}) {
  return (
    <label className={checked
      ? "conversation-export-dialog__range-option conversation-export-dialog__range-option--active"
      : "conversation-export-dialog__range-option"}
    >
      <input
        checked={checked}
        disabled={disabled}
        name={name}
        readOnly={!onChange}
        type="radio"
        onChange={onChange}
      />
      <strong>{label}</strong>
    </label>
  );
}

function rangeLabelKey(range: Exclude<ConversationExportRange, "conversation">) {
  if (range === "message") return "message" as const;
  if (range === "through-message") return "throughMessage" as const;
  return "fromMessage" as const;
}

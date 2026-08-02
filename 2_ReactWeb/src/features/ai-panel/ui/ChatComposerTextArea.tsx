import { CircleNotch } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { ClipboardEvent } from "react";

import { useI18n } from "../../../shared/i18n";
import type {
  ChatComposerInputState,
  ChatComposerUploadStatus,
} from "./ChatComposerTypes";

export function ChatComposerTextArea({ input }: { input: ChatComposerInputState }) {
  const { t } = useI18n();
  return (
    <>
      <textarea
        className="ai-panel__input"
        placeholder={t("aiPanel.composer.placeholder")}
        rows={4}
        value={input.draft}
        onChange={(event) => input.onDraftChange(event.target.value)}
        onPaste={(event) => handleInputPaste(event, input)}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (input.canSend) {
              input.onSend();
            }
          }
        }}
      />
      <ComposerUploadStatus status={input.uploadStatus} />
    </>
  );
}

function handleInputPaste(
  event: ClipboardEvent<HTMLTextAreaElement>,
  input: ChatComposerInputState,
) {
  if (!input.onPasteFiles) return;
  const itemFiles = Array.from(event.clipboardData.items)
    .filter((item) => item.kind === "file")
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null);
  const files = itemFiles.length > 0
    ? itemFiles
    : Array.from(event.clipboardData.files);
  const hasFileData = files.length > 0 || Array.from(event.clipboardData.types).includes("Files");
  if (!hasFileData) return;
  event.preventDefault();
  void input.onPasteFiles(files);
}

function ComposerUploadStatus({
  status,
}: {
  status: ChatComposerUploadStatus | undefined;
}) {
  const { t } = useI18n();
  const [showSaving, setShowSaving] = useState(false);

  useEffect(() => {
    setShowSaving(false);
    if (status?.kind !== "saving") return;
    const timer = window.setTimeout(() => setShowSaving(true), 1000);
    return () => window.clearTimeout(timer);
  }, [status?.kind]);

  if (!status || status.kind === "idle") return null;
  if (status.kind === "saving" && !showSaving) return null;
  const isError = status.kind === "error";
  const message = isError ? status.message : t("aiPanel.composer.savingImageReference");
  if (!message) return null;
  return (
    <div
      aria-live="polite"
      className={`ai-panel__upload-status${isError ? " ai-panel__upload-status--error" : ""}`}
      role={isError ? "alert" : "status"}
    >
      {!isError ? (
        <CircleNotch
          aria-hidden="true"
          className="ai-panel__upload-status-spinner"
          size={13}
          weight="bold"
        />
      ) : null}
      <span>{message}</span>
    </div>
  );
}

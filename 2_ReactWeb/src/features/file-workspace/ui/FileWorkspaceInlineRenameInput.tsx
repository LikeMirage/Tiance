import { Check } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "../../../shared/i18n";

type FileWorkspaceInlineRenameInputProps = {
  initialName: string;
  onCancel: () => void;
  onCommit: (name: string) => Promise<void> | void;
};

export function FileWorkspaceInlineRenameInput({
  initialName,
  onCancel,
  onCommit,
}: FileWorkspaceInlineRenameInputProps) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const fieldRef = useRef<HTMLSpanElement>(null);
  const commitInFlightRef = useRef(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const commit = useCallback(async (rawValue: string) => {
    if (commitInFlightRef.current) {
      return;
    }
    const value = rawValue.trim();
    if (!value) {
      setErrorMessage(t("fileWorkspace.nameRequired"));
      inputRef.current?.focus();
      return;
    }
    commitInFlightRef.current = true;
    setErrorMessage(null);
    try {
      await onCommit(value);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("fileWorkspace.renameFailed"));
      window.setTimeout(() => inputRef.current?.focus(), 0);
    } finally {
      commitInFlightRef.current = false;
    }
  }, [onCommit, t]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      const field = fieldRef.current;
      const input = inputRef.current;
      const target = event.target;
      if (!field || !input || !(target instanceof Node) || field.contains(target)) {
        return;
      }

      void commit(input.value);
    };

    window.addEventListener("pointerdown", handlePointerDown, { capture: true });
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown, { capture: true });
    };
  }, [commit]);

  return (
    <span ref={fieldRef} className="fwt-rename-field">
      <span className="fwt-rename-control">
        <input
          ref={inputRef}
          className="fwt-rename-input"
          defaultValue={initialName}
          aria-invalid={Boolean(errorMessage)}
          onBlur={(event) => {
            void commit(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void commit(event.currentTarget.value);
            } else if (event.key === "Escape") {
              onCancel();
            }
          }}
          onChange={() => setErrorMessage(null)}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        />
        <button
          className="fwt-rename-save"
          type="button"
          aria-label={t("fileWorkspace.confirmRename")}
          title={t("common.actions.confirm")}
          onPointerDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          onClick={(event) => {
            event.stopPropagation();
            void commit(inputRef.current?.value ?? initialName);
          }}
        >
          <Check size={13} weight="bold" aria-hidden="true" />
        </button>
      </span>
      {errorMessage ? (
        <span className="fwt-rename-error">{errorMessage}</span>
      ) : null}
    </span>
  );
}

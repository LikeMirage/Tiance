import { useEffect, useRef, useState } from "react";
import type { ElementType, KeyboardEvent } from "react";

import "./inline-editable-text.css";

type InlineEditableTextProps = {
  ariaLabel: string;
  as?: ElementType;
  className?: string;
  disabled?: boolean;
  editable?: boolean;
  emptyErrorMessage?: string;
  onCommit: (nextValue: string) => Promise<void> | void;
  value: string;
};

export function InlineEditableText({
  ariaLabel,
  as: Component = "span",
  className = "",
  disabled = false,
  editable = true,
  emptyErrorMessage = "内容不能为空。",
  onCommit,
  value,
}: InlineEditableTextProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [draftValue, setDraftValue] = useState(value);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!isEditing) {
      setDraftValue(value);
    }
  }, [isEditing, value]);

  useEffect(() => {
    if (!isEditing) {
      return;
    }

    const animationFrameId = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });

    return () => window.cancelAnimationFrame(animationFrameId);
  }, [isEditing]);

  const beginEditing = () => {
    if (!editable || disabled || isSaving) {
      return;
    }

    setDraftValue(value);
    setError(null);
    setIsEditing(true);
  };

  const commitDraft = async () => {
    if (!isEditing || isSaving) {
      return;
    }

    const normalizedValue = draftValue.trim();
    if (!normalizedValue) {
      setError(emptyErrorMessage);
      window.requestAnimationFrame(() => inputRef.current?.focus());
      return;
    }

    if (normalizedValue === value.trim()) {
      setDraftValue(value);
      setError(null);
      setIsEditing(false);
      return;
    }

    setIsSaving(true);
    try {
      await onCommit(normalizedValue);
      setError(null);
      setIsEditing(false);
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : "保存失败。");
      window.requestAnimationFrame(() => inputRef.current?.focus());
    } finally {
      setIsSaving(false);
    }
  };

  const cancelEditing = () => {
    setDraftValue(value);
    setError(null);
    setIsEditing(false);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitDraft();
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      cancelEditing();
    }
  };

  const rootClassName = [
    "inline-editable-text",
    isEditing ? "inline-editable-text--editing" : "",
    isSaving ? "inline-editable-text--saving" : "",
    error ? "inline-editable-text--error" : "",
    editable && !disabled ? "inline-editable-text--editable" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Component className={rootClassName}>
      {isEditing ? (
        <input
          ref={inputRef}
          className="inline-editable-text__input"
          type="text"
          aria-label={ariaLabel}
          disabled={disabled || isSaving}
          value={draftValue}
          onBlur={() => {
            void commitDraft();
          }}
          onChange={(event) => setDraftValue(event.target.value)}
          onKeyDown={handleKeyDown}
        />
      ) : (
        <button
          className="inline-editable-text__display"
          type="button"
          aria-label={editable ? ariaLabel : undefined}
          disabled={!editable || disabled}
          onClick={beginEditing}
        >
          {value}
        </button>
      )}
      {error ? (
        <span className="inline-editable-text__error" role="status">
          {error}
        </span>
      ) : null}
    </Component>
  );
}

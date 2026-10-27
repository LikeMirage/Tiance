import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "@phosphor-icons/react";
import "./confirm-modal.css";

export type ConfirmModalProps = {
  cancelDisabled?: boolean;
  cancelLabel?: string;
  showClose?: boolean;
  closeLabel?: string;
  children?: ReactNode;
  confirmDisabled?: boolean;
  confirmLabel?: string;
  closeOnBackdrop?: boolean;
  contained?: boolean;
  danger?: boolean;
  dialogClassName?: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  onSecondary?: () => void;
  portalTarget?: Element | DocumentFragment;
  secondaryDanger?: boolean;
  secondaryDisabled?: boolean;
  secondaryLabel?: string;
  showCancel?: boolean;
  showHeader?: boolean;
  title: string;
};

export function ConfirmModal({
  cancelDisabled = false,
  cancelLabel = "取消",
  showClose = false,
  closeLabel = "关闭",
  children = null,
  confirmDisabled = false,
  confirmLabel = "确认",
  closeOnBackdrop = true,
  contained = false,
  danger = false,
  dialogClassName,
  message,
  onCancel,
  onConfirm,
  onSecondary,
  portalTarget,
  secondaryDanger = false,
  secondaryDisabled = false,
  secondaryLabel,
  showCancel = true,
  showHeader = true,
  title,
}: ConfirmModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (danger && showCancel && !cancelDisabled) {
      cancelRef.current?.focus();
      return;
    }
    confirmRef.current?.focus();
  }, [cancelDisabled, danger, showCancel]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !cancelDisabled) onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [cancelDisabled, onCancel]);

  const handleCancel = () => {
    if (!cancelDisabled) {
      onCancel();
    }
  };

  return createPortal(
    <div
      className={
        contained
          ? "confirm-modal-backdrop confirm-modal-backdrop--contained"
          : "confirm-modal-backdrop"
      }
      role="presentation"
      onClick={closeOnBackdrop ? handleCancel : undefined}
    >
      <div
        className={["confirm-modal", dialogClassName].filter(Boolean).join(" ")}
        role="dialog"
        aria-modal="true"
        aria-label={showHeader ? undefined : title}
        onClick={(e) => e.stopPropagation()}
      >
        {showClose ? (
          <button
            className="confirm-modal__close"
            type="button"
            aria-label={closeLabel}
            title={closeLabel}
            disabled={cancelDisabled}
            onClick={handleCancel}
          >
            <X size={18} aria-hidden="true" />
          </button>
        ) : null}
        {showHeader ? (
          <>
            <h3 className="confirm-modal__title">{title}</h3>
            <p className="confirm-modal__message">{message}</p>
          </>
        ) : null}
        {children}
        <div className="confirm-modal__actions">
          {showCancel ? (
            <button
              ref={cancelRef}
              className="confirm-modal__btn"
              type="button"
              disabled={cancelDisabled}
              onClick={handleCancel}
            >
              {cancelLabel}
            </button>
          ) : null}
          {onSecondary && secondaryLabel ? (
            <button
              className={
                secondaryDanger
                  ? "confirm-modal__btn confirm-modal__btn--danger"
                  : "confirm-modal__btn"
              }
              type="button"
              disabled={secondaryDisabled}
              onClick={onSecondary}
            >
              {secondaryLabel}
            </button>
          ) : null}
          <button
            ref={confirmRef}
            className={
              danger
                ? "confirm-modal__btn confirm-modal__btn--danger"
                : "confirm-modal__btn confirm-modal__btn--primary"
            }
            type="button"
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    portalTarget ?? document.body,
  );
}

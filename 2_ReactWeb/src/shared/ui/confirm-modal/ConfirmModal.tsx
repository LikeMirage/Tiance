import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./confirm-modal.css";

export type ConfirmModalProps = {
  cancelDisabled?: boolean;
  children?: ReactNode;
  confirmDisabled?: boolean;
  confirmLabel?: string;
  contained?: boolean;
  danger?: boolean;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  onSecondary?: () => void;
  portalTarget?: Element | DocumentFragment;
  secondaryDanger?: boolean;
  secondaryDisabled?: boolean;
  secondaryLabel?: string;
  showCancel?: boolean;
  title: string;
};

export function ConfirmModal({
  cancelDisabled = false,
  children = null,
  confirmDisabled = false,
  confirmLabel = "确认",
  contained = false,
  danger = false,
  message,
  onCancel,
  onConfirm,
  onSecondary,
  portalTarget,
  secondaryDanger = false,
  secondaryDisabled = false,
  secondaryLabel,
  showCancel = true,
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
      onClick={handleCancel}
    >
      <div
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="confirm-modal__title">{title}</h3>
        <p className="confirm-modal__message">{message}</p>
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
              取消
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

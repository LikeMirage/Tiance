import { useEffect, useId } from "react";
import type { ReactNode } from "react";

export function DashboardSection({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <section className="tool-dashboard__section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function Field({
  children,
  className = "",
  label,
}: {
  children: ReactNode;
  className?: string;
  label: string;
}) {
  return (
    <div className={["tool-dashboard__field", className].filter(Boolean).join(" ")}>
      <span>{label}</span>
      {children}
    </div>
  );
}

export function ReadonlyValue({ value }: { value: string }) {
  return <span className="tool-dashboard__readonly-value">{value || "未设置"}</span>;
}

export function ConfirmDialog({
  confirmLabel,
  message,
  onCancel,
  onConfirm,
  title,
}: {
  confirmLabel: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  title: string;
}) {
  const titleId = useId();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  return (
    <div className="tool-dashboard__dialog-backdrop" role="presentation">
      <div
        className="tool-dashboard__dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h3 id={titleId}>{title}</h3>
        <p>{message}</p>
        <div className="tool-dashboard__dialog-actions">
          <button className="tool-dashboard__secondary-button" type="button" onClick={onCancel}>
            取消
          </button>
          <button className="tool-dashboard__danger-button" type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

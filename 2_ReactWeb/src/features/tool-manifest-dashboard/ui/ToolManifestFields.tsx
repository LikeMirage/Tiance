import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Plus } from "@phosphor-icons/react";

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

function TokenButtons({
  addLabel,
  emptyText,
  items,
  onAdd,
  onRemove,
  removeLabelPrefix,
}: {
  addLabel: string;
  emptyText: string;
  items: string[];
  onAdd: () => void;
  onRemove: (item: string) => void;
  removeLabelPrefix: string;
}) {
  return (
    <div className="tool-dashboard__token-row">
      {items.length > 0 ? (
        items.map((item) => (
          <button
            className="tool-dashboard__token-chip"
            key={item}
            type="button"
            title={`${removeLabelPrefix} ${item}`}
            onClick={() => onRemove(item)}
          >
            <span>{item}</span>
            <strong aria-hidden="true">×</strong>
          </button>
        ))
      ) : (
        <span className="tool-dashboard__token-empty">{emptyText}</span>
      )}
      <button
        className="tool-dashboard__token-add"
        type="button"
        aria-label={addLabel}
        title={addLabel}
        onClick={onAdd}
      >
        <Plus size={14} weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}

export function KeywordButtons({
  keywords,
  onAdd,
  onRemove,
}: {
  keywords: string[];
  onAdd: () => void;
  onRemove: (keyword: string) => void;
}) {
  return (
    <TokenButtons
      addLabel="添加关键词"
      emptyText="暂无关键词"
      items={keywords}
      removeLabelPrefix="移除"
      onAdd={onAdd}
      onRemove={onRemove}
    />
  );
}

export function KeywordDialog({
  existingKeywords,
  onCancel,
  onConfirm,
}: {
  existingKeywords: string[];
  onCancel: () => void;
  onConfirm: (keyword: string) => void;
}) {
  return (
    <TokenDialog
      confirmLabel="添加"
      existingItems={existingKeywords}
      placeholder="例如：文本"
      title="添加关键词"
      validateToken={(keyword) => validateKeyword(keyword, existingKeywords)}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

function TokenDialog({
  confirmLabel,
  existingItems,
  onCancel,
  onConfirm,
  placeholder,
  title,
  validateToken,
}: {
  confirmLabel: string;
  existingItems: string[];
  onCancel: () => void;
  onConfirm: (item: string) => void;
  placeholder: string;
  title: string;
  validateToken: (item: string, existingItems: string[]) => string | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = () => {
    const item = normalizeToken(value);
    const validationError = validateToken(item, existingItems);
    if (validationError) {
      setError(validationError);
      inputRef.current?.focus();
      inputRef.current?.select();
      return;
    }
    onConfirm(item);
  };

  return (
    <div className="tool-dashboard__dialog-backdrop" role="presentation">
      <div
        className="tool-dashboard__dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h3 id={titleId}>{title}</h3>
        <input
          ref={inputRef}
          className="tool-dashboard__input"
          value={value}
          placeholder={placeholder}
          onChange={(event) => {
            setValue(event.target.value);
            setError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              submit();
            } else if (event.key === "Escape") {
              onCancel();
            }
          }}
        />
        {error ? <p className="tool-dashboard__dialog-error">{error}</p> : null}
        <div className="tool-dashboard__dialog-actions">
          <button className="tool-dashboard__secondary-button" type="button" onClick={onCancel}>
            取消
          </button>
          <button className="tool-dashboard__primary-button" type="button" onClick={submit}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
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

function normalizeToken(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function validateKeyword(keyword: string, existingKeywords: string[]) {
  if (!keyword) {
    return "关键词不能为空。";
  }
  if (existingKeywords.includes(keyword)) {
    return "关键词已存在。";
  }
  return null;
}

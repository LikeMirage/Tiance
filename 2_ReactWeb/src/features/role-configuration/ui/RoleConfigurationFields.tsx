import { useEffect, useState } from "react";
import type { ReactNode } from "react";

export function RoleField({
  children,
  description,
  label,
  wide = false,
}: {
  children: ReactNode;
  description?: string;
  label: string;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "role-dashboard__field role-dashboard__field--wide" : "role-dashboard__field"}>
      <span>{label}</span>
      {description ? <small>{description}</small> : null}
      {children}
    </label>
  );
}

export function RoleToggle({
  checked,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      className={checked ? "role-dashboard__toggle role-dashboard__toggle--on" : "role-dashboard__toggle"}
      disabled={disabled}
      role="switch"
      type="button"
      onClick={() => onChange(!checked)}
    >
      <span>{label}</span>
      <i aria-hidden="true" />
    </button>
  );
}

export function RoleNumberInput({
  allowNull = false,
  max,
  min,
  onCommit,
  step = 1,
  value,
}: {
  allowNull?: boolean;
  max?: number;
  min: number;
  onCommit: (value: number | null) => void;
  step?: number;
  value: number | null;
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));

  useEffect(() => {
    setDraft(value === null ? "" : String(value));
  }, [value]);

  const commit = () => {
    const normalizedDraft = draft.trim();
    if (!normalizedDraft && allowNull) {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(normalizedDraft);
    if (!Number.isFinite(parsed)) {
      setDraft(value === null ? "" : String(value));
      return;
    }
    const lowerBounded = Math.max(min, parsed);
    const normalized = max === undefined ? lowerBounded : Math.min(max, lowerBounded);
    setDraft(String(normalized));
    if (normalized !== value) onCommit(normalized);
  };

  return (
    <input
      className="role-dashboard__input"
      max={max}
      min={min}
      step={step}
      type="number"
      value={draft}
      onBlur={commit}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          event.currentTarget.blur();
        }
      }}
    />
  );
}

export function RoleSection({
  children,
  className = "",
  description,
  title,
}: {
  children: ReactNode;
  className?: string;
  description?: string;
  title: string;
}) {
  return (
    <section className={`role-dashboard__section ${className}`.trim()}>
      <header>
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </header>
      {children}
    </section>
  );
}

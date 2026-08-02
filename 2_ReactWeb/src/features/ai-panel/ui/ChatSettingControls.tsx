import { useEffect, useState } from "react";

import { Tooltip } from "../../../shared/ui/tooltip";

export function SettingsNumberInput({
  defaultValue,
  label,
  max,
  min,
  onCommit,
  placeholder,
  step,
  value,
}: {
  defaultValue?: number;
  label: string;
  max?: number;
  min: number;
  onCommit: (value: number | null) => void;
  placeholder: string;
  step: number;
  value: number | null;
}) {
  const displayValue = value ?? defaultValue ?? null;
  const [draft, setDraft] = useState(displayValue === null ? "" : String(displayValue));

  useEffect(() => {
    const nextDisplayValue = value ?? defaultValue ?? null;
    setDraft(nextDisplayValue === null ? "" : String(nextDisplayValue));
  }, [defaultValue, value]);

  const commitDraft = () => {
    const rawValue = draft.trim();
    if (!rawValue) {
      const nextDisplayValue = value ?? defaultValue ?? null;
      setDraft(nextDisplayValue === null ? "" : String(nextDisplayValue));
      if (value !== null) {
        onCommit(null);
      }
      return;
    }
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed)) {
      setDraft(displayValue === null ? "" : String(displayValue));
      return;
    }
    const minBounded = Math.max(parsed, min);
    const normalized = max === undefined ? minBounded : Math.min(minBounded, max);
    setDraft(String(normalized));
    if (normalized === displayValue) {
      return;
    }
    onCommit(normalized);
  };

  return (
    <label className="ai-panel__setting-row">
      <span className="ai-panel__setting-label">{label}</span>
      <input
        className="ai-panel__number-input"
        max={max}
        min={min}
        placeholder={placeholder}
        step={step}
        type="number"
        value={draft}
        onBlur={commitDraft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}

export function SettingsIntegerInput({
  description,
  disabled = false,
  label,
  max,
  min,
  onCommit,
  suffix,
  value,
}: {
  description?: string;
  disabled?: boolean;
  label: string;
  max?: number;
  min: number;
  onCommit: (value: number) => void;
  suffix?: string;
  value: number;
}) {
  const [draft, setDraft] = useState(String(value));

  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commitDraft = () => {
    const parsed = Number(draft.trim());
    if (!Number.isFinite(parsed)) {
      setDraft(String(value));
      return;
    }
    const minBounded = Math.max(Math.round(parsed), min);
    const normalized = max === undefined ? minBounded : Math.min(minBounded, max);
    setDraft(String(normalized));
    if (normalized !== value) {
      onCommit(normalized);
    }
  };

  return (
    <label className="ai-panel__setting-row">
      <SettingLabel description={description} label={label} />
      {suffix ? (
        <span className="ai-panel__number-with-suffix">
          <input
            className="ai-panel__number-input"
            disabled={disabled}
            max={max}
            min={min}
            step={1}
            type="number"
            value={draft}
            onBlur={commitDraft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }
            }}
          />
          <span className="ai-panel__setting-value">{suffix}</span>
        </span>
      ) : (
        <input
          className="ai-panel__number-input"
          disabled={disabled}
          max={max}
          min={min}
          step={1}
          type="number"
          value={draft}
          onBlur={commitDraft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
        />
      )}
    </label>
  );
}

function SettingLabel({
  description,
  label,
}: {
  description?: string;
  label: string;
}) {
  const labelContent = <span className="ai-panel__setting-label">{label}</span>;
  if (!description) {
    return labelContent;
  }
  return <Tooltip content={description}>{labelContent}</Tooltip>;
}

export function SettingsToggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      className="ai-panel__setting-row"
      onClick={(event) => {
        if (event.target instanceof HTMLInputElement) return;
        event.preventDefault();
        onChange(!checked);
      }}
    >
      <span className="ai-panel__setting-label">{label}</span>
      <input
        className="ai-panel__toggle-input"
        checked={checked}
        type="checkbox"
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

import { useEffect, useRef, useState } from "react";

import "./option-select.css";

export type OptionSelectItem<Value extends string> = {
  label: string;
  value: Value;
};

export type OptionSelectVariant = "field" | "integrated-overlay";

type OptionSelectProps<Value extends string> = {
  ariaLabel?: string;
  ariaLabelledBy?: string;
  className?: string;
  disabled?: boolean;
  floating?: boolean;
  onChange: (value: Value) => void;
  onOpen?: () => Promise<void> | void;
  options: readonly OptionSelectItem<Value>[];
  placeholder?: string;
  showSelectedOption?: boolean;
  value: Value;
  variant?: OptionSelectVariant;
};

export function OptionSelect<Value extends string>({
  ariaLabel,
  ariaLabelledBy,
  className,
  disabled = false,
  floating = false,
  onChange,
  onOpen,
  options,
  placeholder,
  showSelectedOption = false,
  value,
  variant = "field",
}: OptionSelectProps<Value>) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedOption = options.find((option) => option.value === value);
  const isIntegratedOverlay = variant === "integrated-overlay";
  const isFloating = floating || isIntegratedOverlay;
  const selectableOptions = showSelectedOption
    ? options
    : options.filter((option) => option.value !== value);
  const displayLabel = selectedOption?.label ?? placeholder ?? value;

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (rootRef.current?.contains(target)) {
        return;
      }

      setIsOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  useEffect(() => {
    if (disabled) {
      setIsOpen(false);
    }
  }, [disabled]);

  return (
    <div
      ref={rootRef}
      className={[
        "ds-option-select",
        isFloating ? "ds-option-select--floating" : "",
        isIntegratedOverlay ? "ds-option-select--integrated" : "",
        isOpen ? "ds-option-select--open" : "",
        className ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        className="ds-option-select__trigger"
        aria-expanded={isOpen}
        aria-haspopup="true"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        disabled={disabled}
        onClick={() => {
          if (!isOpen) {
            void onOpen?.();
          }
          setIsOpen((current) => !current);
        }}
      >
        <span
          className={[
            "ds-option-select__value",
            selectedOption ? "" : "ds-option-select__value--placeholder",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {displayLabel}
        </span>
        <span className="ds-option-select__caret" aria-hidden="true" />
      </button>
      <div className="ds-option-select__options" role="group" aria-hidden={!isOpen}>
        {selectableOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-current={option.value === value ? "true" : undefined}
            className={[
              "ds-option-select__option",
              option.value === value ? "ds-option-select__option--selected" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            tabIndex={isOpen ? 0 : -1}
            onClick={() => {
              onChange(option.value);
              setIsOpen(false);
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

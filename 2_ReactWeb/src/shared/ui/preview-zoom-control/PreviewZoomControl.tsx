import {
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
} from "@phosphor-icons/react";

import { RangeSlider } from "../range-slider";
import "./preview-zoom-control.css";

type PreviewZoomControlProps = {
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  max: number;
  min: number;
  onDecrease: () => void;
  onIncrease: () => void;
  onValueChange: (value: number) => void;
  step: number;
  value: number;
  valueLabel?: string;
};

export function PreviewZoomControl({
  ariaLabel,
  className,
  disabled = false,
  max,
  min,
  onDecrease,
  onIncrease,
  onValueChange,
  step,
  value,
  valueLabel = `${Math.round(value * 100)}%`,
}: PreviewZoomControlProps) {
  const rootClassName = className
    ? `preview-zoom-control ${className}`
    : "preview-zoom-control";

  return (
    <div className={rootClassName} aria-label={ariaLabel}>
      <button
        aria-label="缩小"
        className="preview-zoom-control__button"
        disabled={disabled || value <= min}
        title="缩小"
        type="button"
        onClick={onDecrease}
      >
        <MagnifyingGlassMinus size={15} weight="bold" />
      </button>
      <RangeSlider
        ariaLabel={ariaLabel}
        ariaValueText={valueLabel}
        className="preview-zoom-control__slider"
        disabled={disabled}
        max={max}
        min={min}
        step={step}
        value={value}
        onValueChange={onValueChange}
      />
      <button
        aria-label="放大"
        className="preview-zoom-control__button"
        disabled={disabled || value >= max}
        title="放大"
        type="button"
        onClick={onIncrease}
      >
        <MagnifyingGlassPlus size={15} weight="bold" />
      </button>
      <span className="preview-zoom-control__value">{valueLabel}</span>
    </div>
  );
}

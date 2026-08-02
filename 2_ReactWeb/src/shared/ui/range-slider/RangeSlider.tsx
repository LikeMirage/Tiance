import "./range-slider.css";

type RangeSliderProps = {
  ariaLabel: string;
  ariaValueText?: string;
  className?: string;
  disabled?: boolean;
  max: number;
  min: number;
  onValueChange: (value: number) => void;
  step: number;
  value: number;
};

export function RangeSlider({
  ariaLabel,
  ariaValueText,
  className,
  disabled = false,
  max,
  min,
  onValueChange,
  step,
  value,
}: RangeSliderProps) {
  const progress = max > min ? ((value - min) / (max - min)) * 100 : 0;
  const boundedProgress = Math.min(100, Math.max(0, progress));
  const rootClassName = className ? `range-slider ${className}` : "range-slider";

  return (
    <span className={rootClassName} data-disabled={disabled || undefined}>
      <span className="range-slider__visual" aria-hidden="true">
        <span
          className="range-slider__progress"
          style={{ width: `${boundedProgress}%` }}
        />
      </span>
      <input
        className="range-slider__input"
        type="range"
        aria-label={ariaLabel}
        aria-valuetext={ariaValueText}
        disabled={disabled}
        max={max}
        min={min}
        step={step}
        value={value}
        onChange={(event) => onValueChange(Number(event.currentTarget.value))}
      />
    </span>
  );
}

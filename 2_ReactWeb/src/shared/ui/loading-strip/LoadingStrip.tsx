import "./loading-strip.css";

type LoadingStripMode = "inline" | "fill" | "overlay";
type LoadingStripSurface = "none" | "dark";
type LoadingStripVisual = "bar" | "ring";

export type LoadingStripProps = {
  ariaLabel?: string;
  className?: string;
  label?: string;
  mode?: LoadingStripMode;
  surface?: LoadingStripSurface;
  visual?: LoadingStripVisual;
};

export function LoadingStrip({
  ariaLabel = "正在加载",
  className = "",
  label,
  mode = "fill",
  surface = "none",
  visual = "bar",
}: LoadingStripProps) {
  const resolvedLabel = label ?? (visual === "ring" ? "Tiance" : "Loading...");
  const classes = [
    "ds-loading-strip",
    `ds-loading-strip--${mode}`,
    `ds-loading-strip--visual-${visual}`,
    surface !== "none" ? `ds-loading-strip--surface-${surface}` : "",
    className,
  ].filter(Boolean).join(" ");

  if (visual === "ring") {
    return (
      <div className={classes} aria-busy="true" aria-label={ariaLabel}>
        <div className="ds-loading-strip__ring" aria-hidden="true">
          <div className="ds-loading-strip__ring-label">{resolvedLabel}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={classes} aria-busy="true" aria-label={ariaLabel}>
      <div className="ds-loading-strip__label">{resolvedLabel}</div>
      <div className="ds-loading-strip__bar" />
    </div>
  );
}

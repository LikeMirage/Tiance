import type { ThemeDefinition } from "./themeTypes";
import { env } from "../config/env";

export type ThemeCssVariables = Record<string, string>;

export function getThemeCssVariables(theme: ThemeDefinition): ThemeCssVariables {
  const { background, color, editor, shadow, structure } = theme.tokens;
  const backgroundImage = toCssBackgroundImage(theme.id, background?.image);
  const backgroundOpacity = clampNumber(background?.opacity, 0, 1, 0);
  const hasBackgroundImage = backgroundImage !== "none";
  const imageBackgroundActive = hasBackgroundImage && backgroundOpacity > 0;

  return {
    "--color-surface-base": backgroundSurface(color.surface.base, imageBackgroundActive),
    "--color-surface-panel": backgroundSurface(color.surface.panel, imageBackgroundActive),
    "--color-surface-panel-solid": opaqueBackgroundSurface(color.surface.panel),
    "--color-surface-panel-alt": backgroundSurface(color.surface.panelAlt, imageBackgroundActive),
    "--color-surface-toolbar": backgroundSurface(color.surface.toolbar, imageBackgroundActive),
    "--color-surface-titlebar": backgroundSurface(color.surface.titlebar, imageBackgroundActive),
    "--color-surface-statusbar": backgroundSurface(color.surface.statusbar, imageBackgroundActive),
    "--color-surface-sidebar": backgroundSurface(color.surface.sidebar, imageBackgroundActive),
    "--color-surface-canvas": backgroundSurface(color.surface.canvas, imageBackgroundActive),
    "--color-surface-elevated": backgroundSurface(color.surface.elevated, imageBackgroundActive),
    "--color-surface-elevated-solid": opaqueBackgroundSurface(color.surface.elevated),
    "--color-surface-muted": color.surface.muted,
    "--color-surface-overlay": color.surface.overlay,
    "--color-surface-menu": floatingBackgroundSurface(color.surface.menu, imageBackgroundActive),
    "--color-surface-input": backgroundSurface(color.surface.input, imageBackgroundActive),
    "--color-surface-input-hover": backgroundSurface(color.surface.inputHover, imageBackgroundActive),
    "--color-surface-item-hover": color.surface.itemHover,
    "--color-surface-item-hover-strong": color.surface.itemHoverStrong,
    "--color-border-soft": color.border.soft,
    "--color-border-subtle": color.border.subtle,
    "--color-border-strong": color.border.strong,
    "--color-border-focus": color.border.focus,
    "--color-border-separator": color.border.separator,
    "--color-text-primary": color.text.primary,
    "--color-text-secondary": color.text.secondary,
    "--color-text-muted": color.text.muted,
    "--color-text-heading": color.text.heading,
    "--color-text-heading-accent": color.text.headingAccent,
    "--color-text-inverse": color.text.inverse,
    "--color-accent": color.accent.base,
    "--color-accent-rgb": color.accent.rgb,
    "--color-accent-hover": color.accent.hover,
    "--color-accent-text": color.accent.text,
    "--color-accent-soft-text": color.accent.softText,
    "--color-selection-accent-bg-subtle": color.accent.selectionBgSubtle,
    "--color-selection-accent-bg": color.accent.selectionBg,
    "--color-selection-accent-bg-hover": color.accent.selectionBgHover,
    "--color-selection-accent-border": color.accent.selectionBorder,
    "--color-selection-accent-text": color.accent.selectionText,
    "--color-text-selection-bg": color.accent.textSelectionBg,
    "--color-text-selection-text": color.text.selectionText,
    "--color-danger": color.state.danger,
    "--color-danger-text": color.state.dangerText,
    "--color-danger-soft-text": color.state.dangerSoftText,
    "--color-danger-bg": color.state.dangerBg,
    "--color-danger-border": color.state.dangerBorder,
    "--color-warning": color.state.warning,
    "--color-warning-text": color.state.warningText,
    "--color-success": color.state.success,
    "--color-success-text": color.state.successText,
    "--color-collapse-fade-start": color.collapse.fadeStart,
    "--color-collapse-fade-mid": color.collapse.fadeMid,
    "--color-collapse-fade-end": color.collapse.fadeEnd,
    "--color-collapse-caret": color.collapse.caret,
    "--scrollbar-size": "8px",
    "--scrollbar-track": color.scrollbar.track,
    "--scrollbar-thumb": color.scrollbar.thumb,
    "--scrollbar-thumb-hover": color.scrollbar.thumbHover,
    "--shadow-floating": shadow.floating,
    "--shadow-panel": shadow.panel,
    "--editor-background": backgroundSurface(editor.background, imageBackgroundActive),
    "--editor-foreground": editor.foreground,
    "--editor-gutter-background": backgroundSurface(editor.gutterBackground, imageBackgroundActive),
    "--editor-gutter-foreground": editor.gutterForeground,
    "--editor-active-line": editor.activeLine,
    "--editor-selection-match": editor.selectionMatch,
    "--editor-tooltip-background": floatingBackgroundSurface(
      editor.tooltipBackground,
      imageBackgroundActive,
    ),
    "--structure-line-color": structure.color,
    "--structure-line-hover-color": structure.hoverColor,
    "--structure-line-active-color": structure.activeColor,
    "--structure-titlebar-bottom-width": getStructureLineWidth(
      structure.enabled && structure.lines.titlebarBottom,
      structure.width,
    ),
    "--structure-statusbar-top-width": getStructureLineWidth(
      structure.enabled && structure.lines.statusbarTop,
      structure.width,
    ),
    "--structure-navigation-right-width": getStructureLineWidth(
      structure.enabled && structure.lines.navigationRight,
      structure.width,
    ),
    "--structure-side-panel-right-width": getStructureLineWidth(
      structure.enabled && structure.lines.sidePanelRight,
      structure.width,
    ),
    "--structure-assistant-panel-left-width": getStructureLineWidth(
      structure.enabled && structure.lines.assistantPanelLeft,
      structure.width,
    ),
    "--structure-content-split-width": getStructureLineWidth(
      structure.enabled && structure.lines.contentSplit,
      structure.width,
    ),
    "--app-background-base": color.surface.base,
    "--app-background-image": backgroundImage,
    "--app-background-image-opacity": String(backgroundOpacity),
    "--app-background-surface-weight": getBackgroundSurfaceWeight(hasBackgroundImage, backgroundOpacity),
    "--app-background-image-blur": `${clampNumber(background?.blur, 0, 80, 0)}px`,
    "--app-background-overlay": background?.overlay?.trim() || "transparent",
    "--app-background-position": background?.position?.trim() || "center",
    "--app-background-size": background?.size?.trim() || "cover",
    "--app-background-repeat": background?.repeat?.trim() || "no-repeat",
  };
}

function getStructureLineWidth(enabled: boolean, width: number): string {
  return enabled ? `${width}px` : "0px";
}

function getBackgroundSurfaceWeight(hasBackgroundImage: boolean, opacity: number): string {
  if (!hasBackgroundImage || opacity <= 0) return "100%";
  return "0%";
}

function backgroundSurface(value: string, imageBackgroundActive: boolean): string {
  return imageBackgroundActive ? "transparent" : value;
}

function floatingBackgroundSurface(value: string, imageBackgroundActive: boolean): string {
  return imageBackgroundActive ? opaqueBackgroundSurface(value) : value;
}

function opaqueBackgroundSurface(value: string): string {
  return `rgb(from ${value} r g b)`;
}

function toCssBackgroundImage(themeId: string, image: string | undefined): string {
  const source = image?.trim();
  if (!source) return "none";
  return `url("${escapeCssUrl(resolveThemeBackgroundImageUrl(themeId, source))}")`;
}

function resolveThemeBackgroundImageUrl(themeId: string, source: string): string {
  if (
    source.startsWith("data:") ||
    source.startsWith("blob:") ||
    /^[a-z][a-z0-9+.-]*:\/\//i.test(source)
  ) {
    return source;
  }

  if (source.startsWith("/api/")) {
    return `${env.apiBaseUrl}${source}`;
  }

  if (source.startsWith("/")) {
    return source;
  }

  const normalizedPath = source
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part && part !== "." && part !== "..")
    .map(encodeURIComponent)
    .join("/");

  return normalizedPath ? `${env.apiBaseUrl}/api/themes/assets/${encodeURIComponent(themeId)}/${normalizedPath}` : source;
}

function escapeCssUrl(source: string): string {
  return source
    .replace(/\\/g, "\\\\")
    .replace(/"/g, "\\\"")
    .replace(/\n/g, "")
    .replace(/\r/g, "");
}

function clampNumber(
  value: number | undefined,
  min: number,
  max: number,
  fallback: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

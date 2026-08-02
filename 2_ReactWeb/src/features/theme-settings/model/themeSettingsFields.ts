import type { TranslationKey } from "../../../shared/i18n";

export type ThemeFieldKind = "text" | "number" | "select" | "color" | "boolean";

export type ThemeFieldOption = {
  labelKey: TranslationKey;
  value: string;
};

export type ThemeFieldConfig = {
  kind: ThemeFieldKind;
  labelKey: TranslationKey;
  path: string;
  readOnly?: boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: readonly ThemeFieldOption[];
};

export type ThemeFieldGroupId =
  | "info"
  | "surface"
  | "text"
  | "border"
  | "accent"
  | "state"
  | "collapse"
  | "scrollbar"
  | "shadow"
  | "structure-style"
  | "structure-lines"
  | "editor"
  | "background"
  | "integrations";

export type ThemeFieldGroup = {
  id: ThemeFieldGroupId;
  titleKey: TranslationKey;
  fields: readonly ThemeFieldConfig[];
};

export type ThemeSettingsSectionId =
  | "component-colors"
  | "structure"
  | "editor"
  | "background"
  | "integrations";

export type ThemeSettingsSection = {
  id: ThemeSettingsSectionId;
  labelKey: TranslationKey;
  groups: readonly ThemeFieldGroup[];
};

const MODE_OPTIONS: readonly ThemeFieldOption[] = [
  { labelKey: "themeSettings.options.mode.dark", value: "dark" },
  { labelKey: "themeSettings.options.mode.light", value: "light" },
];

const SHIKI_THEME_OPTIONS: readonly ThemeFieldOption[] = [
  { labelKey: "themeSettings.options.shiki.githubLight", value: "github-light" },
  { labelKey: "themeSettings.options.shiki.githubLightDefault", value: "github-light-default" },
  { labelKey: "themeSettings.options.shiki.githubDark", value: "github-dark" },
  { labelKey: "themeSettings.options.shiki.githubDarkDefault", value: "github-dark-default" },
];

const MERMAID_THEME_OPTIONS: readonly ThemeFieldOption[] = [
  { labelKey: "themeSettings.options.mermaid.default", value: "default" },
  { labelKey: "themeSettings.options.mermaid.neutral", value: "neutral" },
  { labelKey: "themeSettings.options.mermaid.dark", value: "dark" },
  { labelKey: "themeSettings.options.mermaid.forest", value: "forest" },
];

export const THEME_FIELD_GROUPS: readonly ThemeFieldGroup[] = [
  {
    id: "info",
    titleKey: "themeSettings.groups.info",
    fields: [
      { kind: "number", labelKey: "themeSettings.fields.schemaVersion", path: "schemaVersion", readOnly: true },
      { kind: "text", labelKey: "themeSettings.fields.id", path: "id", readOnly: true },
      { kind: "text", labelKey: "themeSettings.fields.name", path: "name" },
      { kind: "select", labelKey: "themeSettings.fields.mode", path: "mode", options: MODE_OPTIONS },
    ],
  },
  {
    id: "surface",
    titleKey: "themeSettings.groups.surface",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.surfaceBase", path: "tokens.color.surface.base" },
      { kind: "color", labelKey: "themeSettings.fields.surfacePanel", path: "tokens.color.surface.panel" },
      { kind: "color", labelKey: "themeSettings.fields.surfacePanelAlt", path: "tokens.color.surface.panelAlt" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceToolbar", path: "tokens.color.surface.toolbar" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceTitlebar", path: "tokens.color.surface.titlebar" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceStatusbar", path: "tokens.color.surface.statusbar" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceSidebar", path: "tokens.color.surface.sidebar" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceCanvas", path: "tokens.color.surface.canvas" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceElevated", path: "tokens.color.surface.elevated" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceMuted", path: "tokens.color.surface.muted" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceOverlay", path: "tokens.color.surface.overlay" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceMenu", path: "tokens.color.surface.menu" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceInput", path: "tokens.color.surface.input" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceInputHover", path: "tokens.color.surface.inputHover" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceItemHover", path: "tokens.color.surface.itemHover" },
      { kind: "color", labelKey: "themeSettings.fields.surfaceItemHoverStrong", path: "tokens.color.surface.itemHoverStrong" },
    ],
  },
  {
    id: "text",
    titleKey: "themeSettings.groups.text",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.textPrimary", path: "tokens.color.text.primary" },
      { kind: "color", labelKey: "themeSettings.fields.textSecondary", path: "tokens.color.text.secondary" },
      { kind: "color", labelKey: "themeSettings.fields.textMuted", path: "tokens.color.text.muted" },
      { kind: "color", labelKey: "themeSettings.fields.textHeading", path: "tokens.color.text.heading" },
      { kind: "color", labelKey: "themeSettings.fields.textHeadingAccent", path: "tokens.color.text.headingAccent" },
      { kind: "color", labelKey: "themeSettings.fields.textInverse", path: "tokens.color.text.inverse" },
      { kind: "color", labelKey: "themeSettings.fields.textSelection", path: "tokens.color.text.selectionText" },
    ],
  },
  {
    id: "border",
    titleKey: "themeSettings.groups.border",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.borderSoft", path: "tokens.color.border.soft" },
      { kind: "color", labelKey: "themeSettings.fields.borderSubtle", path: "tokens.color.border.subtle" },
      { kind: "color", labelKey: "themeSettings.fields.borderStrong", path: "tokens.color.border.strong" },
      { kind: "color", labelKey: "themeSettings.fields.borderFocus", path: "tokens.color.border.focus" },
      { kind: "color", labelKey: "themeSettings.fields.borderSeparator", path: "tokens.color.border.separator" },
    ],
  },
  {
    id: "accent",
    titleKey: "themeSettings.groups.accent",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.accentBase", path: "tokens.color.accent.base" },
      { kind: "text", labelKey: "themeSettings.fields.accentRgb", path: "tokens.color.accent.rgb" },
      { kind: "color", labelKey: "themeSettings.fields.accentHover", path: "tokens.color.accent.hover" },
      { kind: "color", labelKey: "themeSettings.fields.accentText", path: "tokens.color.accent.text" },
      { kind: "color", labelKey: "themeSettings.fields.accentSoftText", path: "tokens.color.accent.softText" },
      { kind: "color", labelKey: "themeSettings.fields.accentSelectionText", path: "tokens.color.accent.selectionText" },
      { kind: "color", labelKey: "themeSettings.fields.accentSelectionBgSubtle", path: "tokens.color.accent.selectionBgSubtle" },
      { kind: "color", labelKey: "themeSettings.fields.accentSelectionBg", path: "tokens.color.accent.selectionBg" },
      { kind: "color", labelKey: "themeSettings.fields.accentSelectionBgHover", path: "tokens.color.accent.selectionBgHover" },
      { kind: "color", labelKey: "themeSettings.fields.accentSelectionBorder", path: "tokens.color.accent.selectionBorder" },
      { kind: "color", labelKey: "themeSettings.fields.accentTextSelectionBg", path: "tokens.color.accent.textSelectionBg" },
    ],
  },
  {
    id: "state",
    titleKey: "themeSettings.groups.state",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.stateDanger", path: "tokens.color.state.danger" },
      { kind: "color", labelKey: "themeSettings.fields.stateDangerText", path: "tokens.color.state.dangerText" },
      { kind: "color", labelKey: "themeSettings.fields.stateDangerSoftText", path: "tokens.color.state.dangerSoftText" },
      { kind: "color", labelKey: "themeSettings.fields.stateDangerBg", path: "tokens.color.state.dangerBg" },
      { kind: "color", labelKey: "themeSettings.fields.stateDangerBorder", path: "tokens.color.state.dangerBorder" },
      { kind: "color", labelKey: "themeSettings.fields.stateWarning", path: "tokens.color.state.warning" },
      { kind: "color", labelKey: "themeSettings.fields.stateWarningText", path: "tokens.color.state.warningText" },
      { kind: "color", labelKey: "themeSettings.fields.stateSuccess", path: "tokens.color.state.success" },
      { kind: "color", labelKey: "themeSettings.fields.stateSuccessText", path: "tokens.color.state.successText" },
    ],
  },
  {
    id: "collapse",
    titleKey: "themeSettings.groups.collapse",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.collapseFadeStart", path: "tokens.color.collapse.fadeStart" },
      { kind: "color", labelKey: "themeSettings.fields.collapseFadeMid", path: "tokens.color.collapse.fadeMid" },
      { kind: "color", labelKey: "themeSettings.fields.collapseFadeEnd", path: "tokens.color.collapse.fadeEnd" },
      { kind: "color", labelKey: "themeSettings.fields.collapseCaret", path: "tokens.color.collapse.caret" },
    ],
  },
  {
    id: "scrollbar",
    titleKey: "themeSettings.groups.scrollbar",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.scrollbarTrack", path: "tokens.color.scrollbar.track" },
      { kind: "color", labelKey: "themeSettings.fields.scrollbarThumb", path: "tokens.color.scrollbar.thumb" },
      { kind: "color", labelKey: "themeSettings.fields.scrollbarThumbHover", path: "tokens.color.scrollbar.thumbHover" },
    ],
  },
  {
    id: "shadow",
    titleKey: "themeSettings.groups.shadow",
    fields: [
      { kind: "text", labelKey: "themeSettings.fields.shadowFloating", path: "tokens.shadow.floating" },
      { kind: "text", labelKey: "themeSettings.fields.shadowPanel", path: "tokens.shadow.panel" },
    ],
  },
  {
    id: "structure-style",
    titleKey: "themeSettings.groups.structureStyle",
    fields: [
      { kind: "boolean", labelKey: "themeSettings.fields.structureEnabled", path: "tokens.structure.enabled" },
      { kind: "number", labelKey: "themeSettings.fields.structureWidth", path: "tokens.structure.width", min: 1, max: 2, step: 1 },
      { kind: "color", labelKey: "themeSettings.fields.structureColor", path: "tokens.structure.color" },
      { kind: "color", labelKey: "themeSettings.fields.structureHoverColor", path: "tokens.structure.hoverColor" },
      { kind: "color", labelKey: "themeSettings.fields.structureActiveColor", path: "tokens.structure.activeColor" },
    ],
  },
  {
    id: "structure-lines",
    titleKey: "themeSettings.groups.structureLines",
    fields: [
      { kind: "boolean", labelKey: "themeSettings.fields.structureTitlebarBottom", path: "tokens.structure.lines.titlebarBottom" },
      { kind: "boolean", labelKey: "themeSettings.fields.structureStatusbarTop", path: "tokens.structure.lines.statusbarTop" },
      { kind: "boolean", labelKey: "themeSettings.fields.structureNavigationRight", path: "tokens.structure.lines.navigationRight" },
      { kind: "boolean", labelKey: "themeSettings.fields.structureSidePanelRight", path: "tokens.structure.lines.sidePanelRight" },
      { kind: "boolean", labelKey: "themeSettings.fields.structureAssistantPanelLeft", path: "tokens.structure.lines.assistantPanelLeft" },
      { kind: "boolean", labelKey: "themeSettings.fields.structureContentSplit", path: "tokens.structure.lines.contentSplit" },
    ],
  },
  {
    id: "editor",
    titleKey: "themeSettings.groups.editor",
    fields: [
      { kind: "color", labelKey: "themeSettings.fields.editorBackground", path: "tokens.editor.background" },
      { kind: "color", labelKey: "themeSettings.fields.editorForeground", path: "tokens.editor.foreground" },
      { kind: "color", labelKey: "themeSettings.fields.editorGutterBackground", path: "tokens.editor.gutterBackground" },
      { kind: "color", labelKey: "themeSettings.fields.editorGutterForeground", path: "tokens.editor.gutterForeground" },
      { kind: "color", labelKey: "themeSettings.fields.editorActiveLine", path: "tokens.editor.activeLine" },
      { kind: "color", labelKey: "themeSettings.fields.editorSelectionMatch", path: "tokens.editor.selectionMatch" },
      { kind: "color", labelKey: "themeSettings.fields.editorTooltipBackground", path: "tokens.editor.tooltipBackground" },
    ],
  },
  {
    id: "background",
    titleKey: "themeSettings.groups.background",
    fields: [
      { kind: "text", labelKey: "themeSettings.fields.backgroundImage", path: "tokens.background.image" },
      { kind: "number", labelKey: "themeSettings.fields.backgroundOpacity", path: "tokens.background.opacity", min: 0, max: 1, step: 0.01 },
      { kind: "number", labelKey: "themeSettings.fields.backgroundBlur", path: "tokens.background.blur", min: 0, max: 80, step: 1 },
      { kind: "color", labelKey: "themeSettings.fields.backgroundOverlay", path: "tokens.background.overlay" },
      { kind: "text", labelKey: "themeSettings.fields.backgroundPosition", path: "tokens.background.position" },
      { kind: "text", labelKey: "themeSettings.fields.backgroundSize", path: "tokens.background.size" },
      { kind: "text", labelKey: "themeSettings.fields.backgroundRepeat", path: "tokens.background.repeat" },
    ],
  },
  {
    id: "integrations",
    titleKey: "themeSettings.groups.integrations",
    fields: [
      { kind: "select", labelKey: "themeSettings.fields.shikiTheme", path: "integrations.shiki", options: SHIKI_THEME_OPTIONS },
      { kind: "select", labelKey: "themeSettings.fields.mermaidTheme", path: "integrations.mermaid", options: MERMAID_THEME_OPTIONS },
    ],
  },
];

function getThemeFieldGroup(id: ThemeFieldGroupId): ThemeFieldGroup {
  const group = THEME_FIELD_GROUPS.find((item) => item.id === id);
  if (!group) {
    throw new Error(`Theme field group not found: ${id}`);
  }
  return group;
}

export const THEME_INFO_FIELD_GROUP = getThemeFieldGroup("info");

export const THEME_SETTINGS_SECTIONS: readonly ThemeSettingsSection[] = [
  {
    id: "component-colors",
    labelKey: "themeSettings.sections.componentColors",
    groups: [
      getThemeFieldGroup("surface"),
      getThemeFieldGroup("text"),
      getThemeFieldGroup("border"),
      getThemeFieldGroup("accent"),
      getThemeFieldGroup("state"),
      getThemeFieldGroup("collapse"),
      getThemeFieldGroup("scrollbar"),
      getThemeFieldGroup("shadow"),
    ],
  },
  {
    id: "structure",
    labelKey: "themeSettings.sections.structure",
    groups: [
      getThemeFieldGroup("structure-style"),
      getThemeFieldGroup("structure-lines"),
    ],
  },
  {
    id: "editor",
    labelKey: "themeSettings.sections.editor",
    groups: [getThemeFieldGroup("editor")],
  },
  {
    id: "background",
    labelKey: "themeSettings.sections.background",
    groups: [getThemeFieldGroup("background")],
  },
  {
    id: "integrations",
    labelKey: "themeSettings.sections.integrations",
    groups: [getThemeFieldGroup("integrations")],
  },
];

export type ThemeMode = "dark" | "light";

export interface ThemeDefinition {
  schemaVersion: 2;
  id: string;
  name: string;
  mode: ThemeMode;
  tokens: ThemeTokens;
  integrations: ThemeIntegrations;
}

export interface ThemeSummary {
  id: string;
  name: string;
  mode: ThemeMode;
}

export interface ThemeListResponse {
  active_theme_id: string;
  themes: ThemeSummary[];
}

export interface ThemeTokens {
  color: ThemeColorTokens;
  structure: ThemeStructureTokens;
  shadow: ThemeShadowTokens;
  editor: ThemeEditorTokens;
  background?: ThemeBackgroundTokens;
}

export interface ThemeColorTokens {
  surface: ThemeSurfaceTokens;
  text: ThemeTextTokens;
  border: ThemeBorderTokens;
  accent: ThemeAccentTokens;
  state: ThemeStateTokens;
  collapse: ThemeCollapseTokens;
  scrollbar: ThemeScrollbarTokens;
}

export interface ThemeSurfaceTokens {
  base: string;
  panel: string;
  panelAlt: string;
  toolbar: string;
  titlebar: string;
  statusbar: string;
  sidebar: string;
  canvas: string;
  elevated: string;
  muted: string;
  overlay: string;
  menu: string;
  input: string;
  inputHover: string;
  itemHover: string;
  itemHoverStrong: string;
}

export interface ThemeTextTokens {
  primary: string;
  secondary: string;
  muted: string;
  heading: string;
  headingAccent: string;
  inverse: string;
  selectionText: string;
}

export interface ThemeBorderTokens {
  soft: string;
  subtle: string;
  strong: string;
  focus: string;
  separator: string;
}

export interface ThemeAccentTokens {
  base: string;
  rgb: string;
  hover: string;
  text: string;
  softText: string;
  selectionText: string;
  selectionBgSubtle: string;
  selectionBg: string;
  selectionBgHover: string;
  selectionBorder: string;
  textSelectionBg: string;
}

export interface ThemeStateTokens {
  danger: string;
  dangerText: string;
  dangerSoftText: string;
  dangerBg: string;
  dangerBorder: string;
  warning: string;
  warningText: string;
  success: string;
  successText: string;
}

export interface ThemeCollapseTokens {
  fadeStart: string;
  fadeMid: string;
  fadeEnd: string;
  caret: string;
}

export interface ThemeScrollbarTokens {
  track: string;
  thumb: string;
  thumbHover: string;
}

export interface ThemeShadowTokens {
  floating: string;
  panel: string;
}

export interface ThemeEditorTokens {
  background: string;
  foreground: string;
  gutterBackground: string;
  gutterForeground: string;
  activeLine: string;
  selectionMatch: string;
  tooltipBackground: string;
}

export interface ThemeStructureTokens {
  enabled: boolean;
  width: 1 | 2;
  color: string;
  hoverColor: string;
  activeColor: string;
  lines: ThemeStructureLines;
}

export interface ThemeStructureLines {
  titlebarBottom: boolean;
  statusbarTop: boolean;
  navigationRight: boolean;
  sidePanelRight: boolean;
  assistantPanelLeft: boolean;
  contentSplit: boolean;
}

export interface ThemeBackgroundTokens {
  image?: string;
  opacity?: number;
  blur?: number;
  overlay?: string;
  position?: string;
  size?: string;
  repeat?: string;
}

export interface ThemeIntegrations {
  codeMirror: string;
  shiki: string;
  mermaid: string;
  milkdown: string;
}

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ThemeContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ThemeSurfaceTokens(ThemeContract):
    base: str
    panel: str
    panel_alt: str = Field(alias="panelAlt")
    toolbar: str
    titlebar: str
    statusbar: str
    sidebar: str
    canvas: str
    elevated: str
    muted: str
    overlay: str
    menu: str
    input: str
    input_hover: str = Field(alias="inputHover")
    item_hover: str = Field(alias="itemHover")
    item_hover_strong: str = Field(alias="itemHoverStrong")


class ThemeTextTokens(ThemeContract):
    primary: str
    secondary: str
    muted: str
    heading: str
    heading_accent: str = Field(alias="headingAccent")
    inverse: str
    selection_text: str = Field(alias="selectionText")


class ThemeBorderTokens(ThemeContract):
    soft: str
    subtle: str
    strong: str
    focus: str
    separator: str


class ThemeAccentTokens(ThemeContract):
    base: str
    rgb: str
    hover: str
    text: str
    soft_text: str = Field(alias="softText")
    selection_text: str = Field(alias="selectionText")
    selection_bg_subtle: str = Field(alias="selectionBgSubtle")
    selection_bg: str = Field(alias="selectionBg")
    selection_bg_hover: str = Field(alias="selectionBgHover")
    selection_border: str = Field(alias="selectionBorder")
    text_selection_bg: str = Field(alias="textSelectionBg")


class ThemeStateTokens(ThemeContract):
    danger: str
    danger_text: str = Field(alias="dangerText")
    danger_soft_text: str = Field(alias="dangerSoftText")
    danger_bg: str = Field(alias="dangerBg")
    danger_border: str = Field(alias="dangerBorder")
    warning: str
    warning_text: str = Field(alias="warningText")
    success: str
    success_text: str = Field(alias="successText")


class ThemeCollapseTokens(ThemeContract):
    fade_start: str = Field(alias="fadeStart")
    fade_mid: str = Field(alias="fadeMid")
    fade_end: str = Field(alias="fadeEnd")
    caret: str


class ThemeScrollbarTokens(ThemeContract):
    track: str
    thumb: str
    thumb_hover: str = Field(alias="thumbHover")


class ThemeColorTokens(ThemeContract):
    surface: ThemeSurfaceTokens
    text: ThemeTextTokens
    border: ThemeBorderTokens
    accent: ThemeAccentTokens
    state: ThemeStateTokens
    collapse: ThemeCollapseTokens
    scrollbar: ThemeScrollbarTokens


class ThemeShadowTokens(ThemeContract):
    floating: str
    panel: str


class ThemeEditorTokens(ThemeContract):
    background: str
    foreground: str
    gutter_background: str = Field(alias="gutterBackground")
    gutter_foreground: str = Field(alias="gutterForeground")
    active_line: str = Field(alias="activeLine")
    selection_match: str = Field(alias="selectionMatch")
    tooltip_background: str = Field(alias="tooltipBackground")


class ThemeStructureLines(ThemeContract):
    titlebar_bottom: bool = Field(alias="titlebarBottom")
    statusbar_top: bool = Field(alias="statusbarTop")
    navigation_right: bool = Field(alias="navigationRight")
    side_panel_right: bool = Field(alias="sidePanelRight")
    assistant_panel_left: bool = Field(alias="assistantPanelLeft")
    content_split: bool = Field(alias="contentSplit")


class ThemeStructureTokens(ThemeContract):
    enabled: bool
    width: int = Field(ge=1, le=2)
    color: str
    hover_color: str = Field(alias="hoverColor")
    active_color: str = Field(alias="activeColor")
    lines: ThemeStructureLines


class ThemeBackgroundTokens(ThemeContract):
    image: str = ""
    opacity: float = Field(default=0, ge=0, le=1)
    blur: int = Field(default=0, ge=0, le=80)
    overlay: str = "transparent"
    position: str = "center"
    size: str = "cover"
    repeat: str = "no-repeat"


class ThemeTokens(ThemeContract):
    color: ThemeColorTokens
    structure: ThemeStructureTokens
    shadow: ThemeShadowTokens
    editor: ThemeEditorTokens
    background: ThemeBackgroundTokens = Field(default_factory=ThemeBackgroundTokens)


class ThemeIntegrations(ThemeContract):
    code_mirror: str = Field(alias="codeMirror")
    shiki: str
    mermaid: str
    milkdown: str


class ThemeBaseDefinition(ThemeContract):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    id: str
    mode: Literal["dark", "light"]
    tokens: ThemeTokens
    integrations: ThemeIntegrations


class ThemeDefinition(ThemeBaseDefinition):
    name: str


class ThemePackageDefinition(ThemeBaseDefinition):
    registration_name: str = Field(alias="registrationName")


def theme_definition_from_package(
    package: ThemePackageDefinition,
    *,
    name: str,
) -> ThemeDefinition:
    payload = package.model_dump(mode="python", exclude={"registration_name"})
    return ThemeDefinition(name=name, **payload)


def theme_package_from_definition(
    theme: ThemeDefinition,
    *,
    registration_name: str,
) -> ThemePackageDefinition:
    payload = theme.model_dump(mode="python", exclude={"name"})
    return ThemePackageDefinition(registration_name=registration_name, **payload)


class ThemeSummary(BaseModel):
    id: str
    name: str
    mode: Literal["dark", "light"]


class ThemeListResponse(BaseModel):
    active_theme_id: str
    themes: list[ThemeSummary]


class ThemeSelectionUpdateRequest(ThemeContract):
    theme_id: str = Field(alias="themeId")

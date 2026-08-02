from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEMPLATE_SCHEMA_VERSION = 1
ALIGNMENTS = frozenset(
    {
        "left",
        "center",
        "right",
        "justify",
        "distribute",
        "justify-low",
        "justify-medium",
        "justify-high",
        "thai-distribute",
    }
)
LINE_SPACING_UNITS = frozenset({"multiple", "pt"})
ORIENTATIONS = frozenset({"portrait", "landscape"})


@dataclass(frozen=True, slots=True)
class RunStyleProfile:
    latin_font: str | None = None
    east_asia_font: str | None = None
    complex_script_font: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strike: bool | None = None
    all_caps: bool | None = None
    small_caps: bool | None = None
    color: str | None = None
    highlight: str | None = None


@dataclass(frozen=True, slots=True)
class ParagraphStyleProfile:
    alignment: str | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing_value: float | None = None
    line_spacing_unit: str | None = None
    left_indent_pt: float | None = None
    right_indent_pt: float | None = None
    first_line_indent_pt: float | None = None
    keep_together: bool | None = None
    keep_with_next: bool | None = None
    page_break_before: bool | None = None
    widow_control: bool | None = None
    contextual_spacing: bool | None = None
    outline_level: int | None = None


@dataclass(frozen=True, slots=True)
class ContentStyleProfile:
    style_id: str
    name: str
    based_on: str | None
    next_style: str | None
    linked_style: str | None
    run: RunStyleProfile
    paragraph: ParagraphStyleProfile


@dataclass(frozen=True, slots=True)
class SectionProfile:
    page_width_mm: float
    page_height_mm: float
    orientation: str
    top_margin_mm: float
    bottom_margin_mm: float
    left_margin_mm: float
    right_margin_mm: float
    gutter_mm: float
    header_distance_mm: float
    footer_distance_mm: float
    start_type: str | None
    different_first_page: bool
    vertical_alignment: str | None
    columns: dict[str, Any]
    page_numbering: dict[str, Any]
    header_text: list[str]
    footer_text: list[str]


@dataclass(frozen=True, slots=True)
class WordTemplateProfile:
    template_id: str
    name: str
    created_at: str
    source_file_name: str
    sections: tuple[SectionProfile, ...]
    role_styles: dict[str, ContentStyleProfile]
    source_styles: tuple[dict[str, Any], ...]
    document_settings: dict[str, Any]
    table_sample: dict[str, Any] | None
    source_summary: dict[str, int]

    @property
    def primary_section(self) -> SectionProfile | None:
        return self.sections[0] if self.sections else None

    def style_for(self, role: str) -> ContentStyleProfile | None:
        return self.role_styles.get(role)


def load_template_profile(payload: object) -> WordTemplateProfile:
    root = _mapping(payload, "模板根对象")
    version = _integer(root.get("schema_version"), "schema_version", minimum=1, maximum=1)
    if version != TEMPLATE_SCHEMA_VERSION:
        raise ValueError(f"不支持的模板版本：{version}。")

    role_styles_payload = _mapping(root.get("role_styles"), "role_styles")
    role_styles = {
        _non_empty_string(role, "role_styles 的角色名"): _load_content_style(style, role)
        for role, style in role_styles_payload.items()
    }
    sections_payload = _list(root.get("sections"), "sections")
    sections = tuple(_load_section(value, index) for index, value in enumerate(sections_payload))
    source_styles = tuple(
        _mapping(value, f"source_styles[{index}]")
        for index, value in enumerate(_list(root.get("source_styles"), "source_styles"))
    )
    table_sample_value = root.get("table_sample")
    table_sample = (
        None
        if table_sample_value is None
        else _mapping(table_sample_value, "table_sample")
    )
    return WordTemplateProfile(
        template_id=_non_empty_string(root.get("template_id"), "template_id"),
        name=_non_empty_string(root.get("name"), "name"),
        created_at=_non_empty_string(root.get("created_at"), "created_at"),
        source_file_name=_non_empty_string(root.get("source_file_name"), "source_file_name"),
        sections=sections,
        role_styles=role_styles,
        source_styles=source_styles,
        document_settings=_mapping(root.get("document_settings"), "document_settings"),
        table_sample=table_sample,
        source_summary={
            str(key): _integer(value, f"source_summary.{key}", minimum=0)
            for key, value in _mapping(root.get("source_summary"), "source_summary").items()
        },
    )


def _load_content_style(value: object, label: str) -> ContentStyleProfile:
    raw = _mapping(value, f"role_styles.{label}")
    run = _mapping(raw.get("run"), f"role_styles.{label}.run")
    paragraph = _mapping(raw.get("paragraph"), f"role_styles.{label}.paragraph")
    return ContentStyleProfile(
        style_id=_non_empty_string(raw.get("style_id"), f"role_styles.{label}.style_id"),
        name=_non_empty_string(raw.get("name"), f"role_styles.{label}.name"),
        based_on=_optional_string(raw.get("based_on"), f"role_styles.{label}.based_on"),
        next_style=_optional_string(raw.get("next_style"), f"role_styles.{label}.next_style"),
        linked_style=_optional_string(raw.get("linked_style"), f"role_styles.{label}.linked_style"),
        run=RunStyleProfile(
            latin_font=_optional_string(run.get("latin_font"), f"{label}.run.latin_font"),
            east_asia_font=_optional_string(
                run.get("east_asia_font"),
                f"{label}.run.east_asia_font",
            ),
            complex_script_font=_optional_string(
                run.get("complex_script_font"),
                f"{label}.run.complex_script_font",
            ),
            size_pt=_optional_number(run.get("size_pt"), f"{label}.run.size_pt", 1, 200),
            bold=_optional_bool(run.get("bold"), f"{label}.run.bold"),
            italic=_optional_bool(run.get("italic"), f"{label}.run.italic"),
            underline=_optional_bool(run.get("underline"), f"{label}.run.underline"),
            strike=_optional_bool(run.get("strike"), f"{label}.run.strike"),
            all_caps=_optional_bool(run.get("all_caps"), f"{label}.run.all_caps"),
            small_caps=_optional_bool(run.get("small_caps"), f"{label}.run.small_caps"),
            color=_optional_hex_color(run.get("color"), f"{label}.run.color"),
            highlight=_optional_string(run.get("highlight"), f"{label}.run.highlight"),
        ),
        paragraph=ParagraphStyleProfile(
            alignment=_optional_enum(
                paragraph.get("alignment"),
                f"{label}.paragraph.alignment",
                ALIGNMENTS,
            ),
            space_before_pt=_optional_number(
                paragraph.get("space_before_pt"),
                f"{label}.paragraph.space_before_pt",
                0,
                1000,
            ),
            space_after_pt=_optional_number(
                paragraph.get("space_after_pt"),
                f"{label}.paragraph.space_after_pt",
                0,
                1000,
            ),
            line_spacing_value=_optional_number(
                paragraph.get("line_spacing_value"),
                f"{label}.paragraph.line_spacing_value",
                0.1,
                1000,
            ),
            line_spacing_unit=_optional_enum(
                paragraph.get("line_spacing_unit"),
                f"{label}.paragraph.line_spacing_unit",
                LINE_SPACING_UNITS,
            ),
            left_indent_pt=_optional_number(
                paragraph.get("left_indent_pt"),
                f"{label}.paragraph.left_indent_pt",
                -2000,
                2000,
            ),
            right_indent_pt=_optional_number(
                paragraph.get("right_indent_pt"),
                f"{label}.paragraph.right_indent_pt",
                -2000,
                2000,
            ),
            first_line_indent_pt=_optional_number(
                paragraph.get("first_line_indent_pt"),
                f"{label}.paragraph.first_line_indent_pt",
                -2000,
                2000,
            ),
            keep_together=_optional_bool(
                paragraph.get("keep_together"),
                f"{label}.paragraph.keep_together",
            ),
            keep_with_next=_optional_bool(
                paragraph.get("keep_with_next"),
                f"{label}.paragraph.keep_with_next",
            ),
            page_break_before=_optional_bool(
                paragraph.get("page_break_before"),
                f"{label}.paragraph.page_break_before",
            ),
            widow_control=_optional_bool(
                paragraph.get("widow_control"),
                f"{label}.paragraph.widow_control",
            ),
            contextual_spacing=_optional_bool(
                paragraph.get("contextual_spacing"),
                f"{label}.paragraph.contextual_spacing",
            ),
            outline_level=_optional_integer(
                paragraph.get("outline_level"),
                f"{label}.paragraph.outline_level",
                0,
                9,
            ),
        ),
    )


def _load_section(value: object, index: int) -> SectionProfile:
    raw = _mapping(value, f"sections[{index}]")
    label = f"sections[{index}]"
    return SectionProfile(
        page_width_mm=_number(raw.get("page_width_mm"), f"{label}.page_width_mm", 10, 2000),
        page_height_mm=_number(raw.get("page_height_mm"), f"{label}.page_height_mm", 10, 2000),
        orientation=_enum(raw.get("orientation"), f"{label}.orientation", ORIENTATIONS),
        top_margin_mm=_number(raw.get("top_margin_mm"), f"{label}.top_margin_mm", 0, 500),
        bottom_margin_mm=_number(
            raw.get("bottom_margin_mm"),
            f"{label}.bottom_margin_mm",
            0,
            500,
        ),
        left_margin_mm=_number(raw.get("left_margin_mm"), f"{label}.left_margin_mm", 0, 500),
        right_margin_mm=_number(
            raw.get("right_margin_mm"),
            f"{label}.right_margin_mm",
            0,
            500,
        ),
        gutter_mm=_number(raw.get("gutter_mm"), f"{label}.gutter_mm", 0, 500),
        header_distance_mm=_number(
            raw.get("header_distance_mm"),
            f"{label}.header_distance_mm",
            0,
            500,
        ),
        footer_distance_mm=_number(
            raw.get("footer_distance_mm"),
            f"{label}.footer_distance_mm",
            0,
            500,
        ),
        start_type=_optional_string(raw.get("start_type"), f"{label}.start_type"),
        different_first_page=_boolean(
            raw.get("different_first_page"),
            f"{label}.different_first_page",
        ),
        vertical_alignment=_optional_string(
            raw.get("vertical_alignment"),
            f"{label}.vertical_alignment",
        ),
        columns=_mapping(raw.get("columns"), f"{label}.columns"),
        page_numbering=_mapping(raw.get("page_numbering"), f"{label}.page_numbering"),
        header_text=[
            _string(item, f"{label}.header_text[{item_index}]")
            for item_index, item in enumerate(_list(raw.get("header_text"), f"{label}.header_text"))
        ],
        footer_text=[
            _string(item, f"{label}.footer_text[{item_index}]")
            for item_index, item in enumerate(_list(raw.get("footer_text"), f"{label}.footer_text"))
        ],
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象。")
    return dict(value)


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组。")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串。")
    return value


def _non_empty_string(value: object, label: str) -> str:
    result = _string(value, label).strip()
    if not result:
        raise ValueError(f"{label} 不能为空。")
    return result


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label).strip() or None


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} 必须是布尔值。")
    return value


def _optional_bool(value: object, label: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, label)


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数字。")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{label} 必须在 {minimum} 到 {maximum} 之间。")
    return result


def _optional_number(
    value: object,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None:
        return None
    return _number(value, label, minimum, maximum)


def _integer(
    value: object,
    label: str,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} 必须是整数。")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" 到 {maximum}" if maximum is not None else "以上"
        raise ValueError(f"{label} 必须为 {minimum}{upper}的整数。")
    return value


def _optional_integer(
    value: object,
    label: str,
    minimum: int,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    return _integer(value, label, minimum, maximum)


def _enum(value: object, label: str, choices: frozenset[str]) -> str:
    result = _non_empty_string(value, label)
    if result not in choices:
        raise ValueError(f"{label} 的值不受支持。")
    return result


def _optional_enum(
    value: object,
    label: str,
    choices: frozenset[str],
) -> str | None:
    if value is None:
        return None
    return _enum(value, label, choices)


def _optional_hex_color(value: object, label: str) -> str | None:
    result = _optional_string(value, label)
    if result is None:
        return None
    normalized = result.removeprefix("#").upper()
    if len(normalized) not in {6, 8} or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        raise ValueError(f"{label} 必须是 6 位或 8 位十六进制颜色。")
    return normalized

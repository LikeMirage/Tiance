from __future__ import annotations

import re
from collections.abc import Callable

from .latex_diagrams import normalize_tikzcd, xymatrix_to_cd


WORD_COLOR_MAP = {
    "black": "000000",
    "blue": "0000FF",
    "brown": "A52A2A",
    "cyan": "00FFFF",
    "darkgray": "A9A9A9",
    "gray": "808080",
    "green": "008000",
    "lightgray": "D3D3D3",
    "lime": "00FF00",
    "magenta": "FF00FF",
    "olive": "808000",
    "orange": "FFA500",
    "pink": "FFC0CB",
    "purple": "800080",
    "red": "FF0000",
    "teal": "008080",
    "violet": "EE82EE",
    "white": "FFFFFF",
    "yellow": "FFFF00",
}
WORD_COLOR_RE = re.compile(r"#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$")
CSS_RGB_RE = re.compile(
    r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
    flags=re.IGNORECASE,
)


IMAGE_COMMANDS = frozenset(
    {
        "ce",
        "pu",
        "xymatrix",
    }
)
IMAGE_ENVIRONMENTS = frozenset({"tikzcd"})
COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
ENVIRONMENT_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}")


def needs_image_rendering(latex: str) -> bool:
    commands = set(COMMAND_RE.findall(latex))
    environments = set(ENVIRONMENT_RE.findall(latex))
    return bool(commands & IMAGE_COMMANDS or environments & IMAGE_ENVIRONMENTS)


def normalize_for_omml(latex: str) -> tuple[str, tuple[str, ...]]:
    notices: list[str] = []
    text = _normalize_prescript(latex)

    def replace_genfrac(arguments: list[str]) -> str:
        left, right, thickness, style, numerator, denominator = arguments
        thickness_value = thickness.strip().lower()
        if thickness_value in {"0", "0pt", "0.0pt"}:
            core = rf"\begin{{matrix}}{numerator}\\{denominator}\end{{matrix}}"
        else:
            core = rf"\frac{{{numerator}}}{{{denominator}}}"
            if thickness_value:
                notices.append("genfrac 的自定义分数线宽已按 Word 标准分数线显示")
        if style.strip():
            notices.append("genfrac 的字号样式由 Word 公式自动适配")
        if left.strip() or right.strip():
            core = rf"\left{left.strip() or '.'}{core}\right{right.strip() or '.'}"
        return core

    text = _replace_group_command(text, "genfrac", 6, replace_genfrac)

    def preserve_color(arguments: list[str]) -> str:
        color = normalize_word_color(arguments[0])
        if color is None:
            notices.append(f"暂不支持颜色 {arguments[0].strip()}，已保留数学内容并忽略颜色")
            return arguments[1]
        return rf"\style{{color:#{color}}}{{{arguments[1]}}}"

    text = _replace_color_declarations(text, preserve_color)
    text = _replace_group_command(text, "color", 2, preserve_color)
    text = _replace_group_command(text, "textcolor", 2, preserve_color)

    def preserve_colorbox(arguments: list[str]) -> str:
        color = normalize_word_color(arguments[0])
        content = _strip_math_delimiters(arguments[1])
        if color is None:
            notices.append(f"暂不支持背景颜色 {arguments[0].strip()}，已保留数学内容并忽略背景")
            return content
        notices.append("colorbox 已转换为 Word 可编辑底纹；复杂公式的背景会按公式节点分段显示")
        return rf"\style{{background:{color}}}{{{content}}}"

    text = _replace_group_command(text, "colorbox", 2, preserve_colorbox)

    def remove_cancel(arguments: list[str]) -> str:
        notices.append("删除线样式已忽略，数学内容保留为可编辑公式")
        return arguments[0]

    for command in ("cancel", "bcancel", "xcancel"):
        text = _replace_group_command(text, command, 1, remove_cancel)

    def replace_cancelto(arguments: list[str]) -> str:
        notices.append("cancelto 的删除箭头已忽略，目标值和数学内容已保留")
        return rf"\overset{{{arguments[0]}}}{{{arguments[1]}}}"

    text = _replace_group_command(text, "cancelto", 2, replace_cancelto)

    def replace_fbox(arguments: list[str]) -> str:
        notices.append("fbox 已按 Word 原生公式框显示")
        return rf"\boxed{{{_strip_math_delimiters(arguments[0])}}}"

    text = _replace_group_command(text, "fbox", 1, replace_fbox)

    def replace_bbox(arguments: list[str]) -> str:
        notices.append("bbox 的自定义边距和边框样式已按 Word 原生公式框显示")
        return rf"\boxed{{{arguments[0]}}}"

    text = _replace_bbox(text, replace_bbox)
    return text, tuple(dict.fromkeys(notices))


def normalize_for_image(latex: str) -> tuple[str, tuple[str, ...]]:
    notices: list[str] = []
    text = normalize_tikzcd(latex)
    text = _replace_group_command(
        text,
        "xymatrix",
        1,
        lambda arguments: xymatrix_to_cd(arguments[0]),
    )
    text = _normalize_prescript(text)

    def replace_cancelto(arguments: list[str]) -> str:
        notices.append("cancelto 已显示为带目标值的删除线，不含箭头头部")
        return rf"\overset{{{arguments[0]}}}{{\cancel{{{arguments[1]}}}}}"

    text = _replace_group_command(
        text,
        "cancelto",
        2,
        replace_cancelto,
    )

    def replace_bbox(arguments: list[str]) -> str:
        notices.append("bbox 的自定义边距和边框样式已按普通公式框显示")
        return rf"\boxed{{{arguments[0]}}}"

    text = _replace_bbox(text, replace_bbox)

    def replace_colorbox(arguments: list[str]) -> str:
        color, content = arguments
        content = content.strip()
        if not (content.startswith("$") and content.endswith("$")):
            content = f"${content}$"
        return rf"\colorbox{{{color}}}{{{content}}}"

    text = _replace_group_command(text, "colorbox", 2, replace_colorbox)
    if "\\begin{tikzcd}" in text or "\\xymatrix" in text:
        raise ValueError("交换图语法不完整，无法转换为图片")
    return text, tuple(dict.fromkeys(notices))


def _normalize_prescript(text: str) -> str:
    return _replace_group_command(
        text,
        "prescript",
        3,
        lambda arguments: rf"{{}}^{{{arguments[0]}}}_{{{arguments[1]}}}{{{arguments[2]}}}",
    )


def _strip_math_delimiters(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped.startswith("$") and stripped.endswith("$"):
        return stripped[1:-1].strip()
    return stripped


def normalize_word_color(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    named = WORD_COLOR_MAP.get(normalized.lower())
    if named:
        return named
    if match := WORD_COLOR_RE.fullmatch(normalized):
        digits = match.group(1).upper()
        return "".join(char * 2 for char in digits) if len(digits) == 3 else digits
    if match := CSS_RGB_RE.fullmatch(normalized):
        channels = tuple(int(value) for value in match.groups())
        if all(0 <= channel <= 255 for channel in channels):
            return "".join(f"{channel:02X}" for channel in channels)
    return None


def _replace_group_command(
    text: str,
    command: str,
    group_count: int,
    replacement: Callable[[list[str]], str],
) -> str:
    pattern = re.compile(rf"\\{re.escape(command)}(?![A-Za-z])")
    output: list[str] = []
    position = 0
    while match := pattern.search(text, position):
        cursor = _skip_spaces(text, match.end())
        arguments: list[str] = []
        try:
            for _ in range(group_count):
                argument, cursor = _read_group(text, cursor, "{", "}")
                arguments.append(argument)
                cursor = _skip_spaces(text, cursor)
        except ValueError:
            output.append(text[position : match.end()])
            position = match.end()
            continue
        output.append(text[position : match.start()])
        output.append(replacement(arguments))
        position = cursor
    output.append(text[position:])
    return "".join(output)


def _replace_color_declarations(
    text: str,
    replacement: Callable[[list[str]], str],
) -> str:
    pattern = re.compile(r"\{\s*\\color(?![A-Za-z])")
    output: list[str] = []
    position = 0
    while match := pattern.search(text, position):
        try:
            group_content, group_end = _read_group(text, match.start(), "{", "}")
            command = re.match(r"\s*\\color(?![A-Za-z])", group_content)
            if command is None:
                raise ValueError("颜色声明格式无效")
            color, content_start = _read_group(
                group_content,
                _skip_spaces(group_content, command.end()),
                "{",
                "}",
            )
            content = group_content[content_start:].strip()
            if not content:
                raise ValueError("颜色声明缺少数学内容")
        except ValueError:
            output.append(text[position : match.end()])
            position = match.end()
            continue
        output.append(text[position : match.start()])
        output.append(replacement([color, content]))
        position = group_end
    output.append(text[position:])
    return "".join(output)


def _replace_bbox(text: str, replacement: Callable[[list[str]], str]) -> str:
    pattern = re.compile(r"\\bbox(?![A-Za-z])")
    output: list[str] = []
    position = 0
    while match := pattern.search(text, position):
        cursor = _skip_spaces(text, match.end())
        try:
            if cursor < len(text) and text[cursor] == "[":
                _, cursor = _read_group(text, cursor, "[", "]")
                cursor = _skip_spaces(text, cursor)
            argument, cursor = _read_group(text, cursor, "{", "}")
        except ValueError:
            output.append(text[position : match.end()])
            position = match.end()
            continue
        output.append(text[position : match.start()])
        output.append(replacement([argument]))
        position = cursor
    output.append(text[position:])
    return "".join(output)


def _read_group(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    if start >= len(text) or text[start] != opener:
        raise ValueError(f"缺少 {opener}")
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
        index += 1
    raise ValueError(f"缺少 {closer}")


def _skip_spaces(text: str, start: int) -> int:
    while start < len(text) and text[start].isspace():
        start += 1
    return start

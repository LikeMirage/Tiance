from __future__ import annotations

import re


XY_ARROW_RE = re.compile(
    r"\\ar\s*\[\s*([^\]]+)\s*\]"
    r"\s*(?:(\^|_)\s*(\{[^{}]*\}|\\[A-Za-z]+|[^\\\s&]+))?"
)
TIKZ_ARROW_RE = re.compile(r"\\arrow\s*\[([^\]]*)\]")
TIKZCD_RE = re.compile(
    r"\\begin\{tikzcd\}(.*?)\\end\{tikzcd\}",
    flags=re.DOTALL,
)

DiagramCell = tuple[str, dict[str, tuple[str, bool]]]
DiagramGrid = list[list[DiagramCell]]


def normalize_tikzcd(text: str) -> str:
    return TIKZCD_RE.sub(lambda match: _grid_to_cd(_parse_tikz_grid(match.group(1))), text)


def xymatrix_to_cd(source: str) -> str:
    return _grid_to_cd(_parse_xymatrix_grid(source))


def _parse_xymatrix_grid(source: str) -> DiagramGrid:
    grid: DiagramGrid = []
    for row_text in _split_top_level(source, r"\\"):
        row: list[DiagramCell] = []
        for cell_text in _split_top_level(row_text, "&"):
            arrows: dict[str, tuple[str, bool]] = {}

            def remove_arrow(match: re.Match[str]) -> str:
                direction = match.group(1).strip()
                if direction not in {"r", "d"}:
                    raise ValueError(f"xymatrix 暂不支持 {direction} 方向箭头")
                if direction in arrows:
                    raise ValueError(f"xymatrix 单元格存在重复 {direction} 方向箭头")
                raw_label = (match.group(3) or "").strip()
                label = raw_label[1:-1] if raw_label.startswith("{") else raw_label
                arrows[direction] = (label, match.group(2) == "_")
                return ""

            content = XY_ARROW_RE.sub(remove_arrow, cell_text).strip()
            if r"\ar" in content:
                raise ValueError("xymatrix 箭头语法无法识别")
            row.append((content, arrows))
        grid.append(row)
    return grid


def _parse_tikz_grid(source: str) -> DiagramGrid:
    grid: DiagramGrid = []
    for row_text in _split_top_level(source, r"\\"):
        row: list[DiagramCell] = []
        for cell_text in _split_top_level(row_text, "&"):
            arrows: dict[str, tuple[str, bool]] = {}

            def remove_arrow(match: re.Match[str]) -> str:
                direction, label, opposite = _parse_tikz_arrow_options(match.group(1))
                if direction in arrows:
                    raise ValueError(f"tikz-cd 单元格存在重复 {direction} 方向箭头")
                arrows[direction] = (label, opposite)
                return ""

            content = TIKZ_ARROW_RE.sub(remove_arrow, cell_text).strip()
            if r"\arrow" in content:
                raise ValueError("tikz-cd 箭头语法无法识别")
            row.append((content, arrows))
        grid.append(row)
    return grid


def _parse_tikz_arrow_options(options: str) -> tuple[str, str, bool]:
    parts = _split_quoted_options(options)
    if not parts or parts[0] not in {"r", "d"}:
        direction = parts[0] if parts else "未知"
        raise ValueError(f"tikz-cd 暂不支持 {direction} 方向箭头")
    direction = parts[0]
    label = ""
    opposite = False
    for option in parts[1:]:
        value = option.strip()
        if value.startswith('"') and '"' in value[1:]:
            closing_quote = value.rfind('"')
            label = value[1:closing_quote]
            opposite = value[closing_quote + 1 :].strip() == "'"
        elif value:
            raise ValueError(f"tikz-cd 暂不支持箭头选项 {value}")
    return direction, label, opposite


def _split_quoted_options(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quoted = False
    for index, char in enumerate(text):
        if char == '"' and (index == 0 or text[index - 1] != "\\"):
            quoted = not quoted
        elif char == "," and not quoted:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _grid_to_cd(grid: DiagramGrid) -> str:
    if not grid or not grid[0]:
        raise ValueError("交换图内容为空")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("交换图各行的节点数量不一致")
    rows: list[str] = []
    for row_index, row in enumerate(grid):
        horizontal: list[str] = [row[0][0]]
        for column in range(width - 1):
            horizontal.append(_horizontal_cd_arrow(row[column][1].get("r")))
            horizontal.append(row[column + 1][0])
        if row[-1][1].get("r"):
            raise ValueError("交换图最右侧节点不能继续向右连接")
        rows.append(" ".join(horizontal))
        if row_index >= len(grid) - 1:
            if any(cell[1].get("d") for cell in row):
                raise ValueError("交换图最下方节点不能继续向下连接")
            continue
        rows.append(" ".join(_vertical_cd_arrow(cell[1].get("d")) for cell in row))
    return r"\begin{CD}" + r" \\ ".join(rows) + r"\end{CD}"


def _horizontal_cd_arrow(arrow: tuple[str, bool] | None) -> str:
    if arrow is None:
        return "@."
    label, opposite = arrow
    return rf"@>>{{{label}}}>" if opposite else rf"@>{{{label}}}>>"


def _vertical_cd_arrow(arrow: tuple[str, bool] | None) -> str:
    if arrow is None:
        return "@."
    label, opposite = arrow
    return rf"@VV{{{label}}}V" if opposite else rf"@V{{{label}}}VV"


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "{" and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif char == "}" and (index == 0 or text[index - 1] != "\\"):
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(separator, index):
            parts.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(text[start:])
    return parts

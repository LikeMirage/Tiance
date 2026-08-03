from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from word_text_measurement import FontTextMeasurer, is_east_asian_character


TWIPS_PER_POINT = 20
EMU_PER_TWIP = 635
CELL_MARGIN_TOP_TWIPS = 80
CELL_MARGIN_BOTTOM_TWIPS = 80
CELL_MARGIN_LEFT_TWIPS = 100
CELL_MARGIN_RIGHT_TWIPS = 100
CELL_HORIZONTAL_PADDING_POINTS = (CELL_MARGIN_LEFT_TWIPS + CELL_MARGIN_RIGHT_TWIPS) / TWIPS_PER_POINT
COARSE_ALLOCATION_STEP_POINTS = 4.0
FINE_ALLOCATION_WINDOW_POINTS = 24.0
MIN_COLUMN_WIDTH_POINTS = 12.0
MAX_STRUCTURAL_FLOOR_POINTS = 40.0
STRUCTURAL_FLOOR_RATIO = 0.55
HEADER_COST_WEIGHT = 1.6
ROW_WRAP_COST = 8.0
CELL_WRAP_COST = 0.45
OVERFLOW_COST = 18.0
MINIMUM_DEFICIT_COST = 32.0
EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class MeasuredToken:
    width: float
    gap_before: float = 0.0


@dataclass(frozen=True, slots=True)
class WrapMeasurement:
    lines: int
    overflow_points: float


@dataclass(frozen=True, slots=True)
class CellLayout:
    lines: tuple[tuple[MeasuredToken, ...], ...]
    minimum_width: float
    preferred_width: float

    def wrap(self, available_width: float) -> WrapMeasurement:
        width = max(1.0, available_width)
        total_lines = 0
        overflow = 0.0
        for line in self.lines:
            if not line:
                total_lines += 1
                continue
            line_count = 1
            used = 0.0
            for token in line:
                gap = token.gap_before if used > 0 else 0.0
                if used > 0 and used + gap + token.width > width:
                    line_count += 1
                    used = token.width
                else:
                    used += gap + token.width
                overflow += max(0.0, token.width - width)
            total_lines += line_count
        return WrapMeasurement(lines=max(1, total_lines), overflow_points=overflow)


@dataclass(frozen=True, slots=True)
class ColumnDemand:
    minimum_width: float
    preferred_width: float


@dataclass(frozen=True, slots=True)
class RowCostState:
    extra_lines: tuple[int, ...]
    extra_line_sum: int
    maximum_extra_lines: int
    second_extra_lines: int
    maximum_count: int
    overflow_cost: float


def calculate_column_widths(
    headers: list[str],
    rows: list[list[str]],
    *,
    available_width_points: float,
    cell_padding_points: float,
    measurer: FontTextMeasurer,
) -> list[float]:
    count = len(headers)
    if count <= 0:
        return []
    total_width = max(float(count), available_width_points)
    table_cells = _measure_table(headers, rows, measurer)
    demands = _column_demands(table_cells, cell_padding_points)
    floor = _structural_floor(total_width, count)
    minimum_targets = [max(floor, demand.minimum_width) for demand in demands]
    widths = minimum_targets if sum(minimum_targets) <= total_width + EPSILON else [floor] * count

    remaining = max(0.0, total_width - sum(widths))
    while remaining > EPSILON:
        step = 1.0 if remaining <= FINE_ALLOCATION_WINDOW_POINTS else COARSE_ALLOCATION_STEP_POINTS
        delta = min(step, remaining)
        if all(width >= demand.preferred_width - EPSILON for width, demand in zip(widths, demands)):
            extra = remaining / count
            widths = [width + extra for width in widths]
            break
        benefits = _allocation_benefits(widths, delta, table_cells, demands, cell_padding_points)
        best_column = max(
            range(count),
            key=lambda column: (
                benefits[column] / delta,
                _allocation_priority(widths[column], demands[column]),
                -column,
            ),
        )
        widths[best_column] += delta
        remaining -= delta
    return _to_percentages(widths)


def apply_column_widths(table: Any, percentages: list[float], document: Any) -> None:
    if not percentages:
        return
    available_twips = document_available_width_twips(document)
    widths = _percentages_to_twips(percentages, available_twips)
    table.autofit = False
    table_properties = table._tbl.tblPr
    layout = _get_or_add(table_properties, "w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    table_width = _get_or_add(table_properties, "w:tblW")
    table_width.set(qn("w:type"), "dxa")
    table_width.set(qn("w:w"), str(available_twips))

    grid = table._tbl.tblGrid
    if grid is None:
        grid = OxmlElement("w:tblGrid")
        table._tbl.insert(table._tbl.index(table_properties) + 1, grid)
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            if index >= len(widths):
                continue
            properties = cell._tc.get_or_add_tcPr()
            cell_width = _get_or_add(properties, "w:tcW")
            cell_width.set(qn("w:type"), "dxa")
            cell_width.set(qn("w:w"), str(widths[index]))


def set_cell_margins(cell: Any) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = _get_or_add(properties, "w:tcMar")
    for name, value in (
        ("top", CELL_MARGIN_TOP_TWIPS),
        ("bottom", CELL_MARGIN_BOTTOM_TWIPS),
        ("start", CELL_MARGIN_LEFT_TWIPS),
        ("end", CELL_MARGIN_RIGHT_TWIPS),
    ):
        margin = _get_or_add(margins, f"w:{name}")
        margin.set(qn("w:w"), str(value))
        margin.set(qn("w:type"), "dxa")


def set_repeat_header(row: Any) -> None:
    properties = row._tr.get_or_add_trPr()
    repeat = _get_or_add(properties, "w:tblHeader")
    repeat.set(qn("w:val"), "true")


def document_available_width_points(document: Any) -> float:
    return document_available_width_twips(document) / TWIPS_PER_POINT


def document_available_width_twips(document: Any) -> int:
    section = document.sections[0]
    available_emu = int(section.page_width) - int(section.left_margin) - int(section.right_margin)
    return max(1, round(available_emu / EMU_PER_TWIP))


def _measure_table(
    headers: list[str], rows: list[list[str]], measurer: FontTextMeasurer
) -> tuple[tuple[CellLayout, ...], ...]:
    count = len(headers)
    cache: dict[tuple[str, bool], CellLayout] = {}

    def measured(value: str, bold: bool) -> CellLayout:
        key = (value, bold)
        if key not in cache:
            cache[key] = _measure_cell(value, measurer, bold=bold)
        return cache[key]

    result: list[tuple[CellLayout, ...]] = [tuple(measured(value, True) for value in headers)]
    for row in rows:
        normalized = (row + [""] * count)[:count]
        result.append(tuple(measured(value, False) for value in normalized))
    return tuple(result)


def _measure_cell(text: str, measurer: FontTextMeasurer, *, bold: bool) -> CellLayout:
    measured_lines = tuple(_measure_line(line, measurer, bold=bold) for line in text.splitlines()) or ((),)
    widths = [token.width for line in measured_lines for token in line]
    preferred = max(
        (
            sum(token.width + (token.gap_before if index else 0.0) for index, token in enumerate(line))
            for line in measured_lines
        ),
        default=0.0,
    )
    return CellLayout(measured_lines, max(widths, default=0.0), preferred)


def _measure_line(text: str, measurer: FontTextMeasurer, *, bold: bool) -> tuple[MeasuredToken, ...]:
    tokens: list[MeasuredToken] = []
    word = ""
    pending_gap = 0.0

    def flush() -> None:
        nonlocal word, pending_gap
        if word:
            tokens.append(MeasuredToken(measurer.measure(word, bold=bold), pending_gap))
            word = ""
            pending_gap = 0.0

    for char in text:
        if char.isspace():
            flush()
            pending_gap += measurer.measure(char, bold=bold)
        elif is_east_asian_character(char):
            flush()
            tokens.append(MeasuredToken(measurer.measure(char, bold=bold), pending_gap))
            pending_gap = 0.0
        else:
            word += char
    flush()
    return tuple(tokens)


def _column_demands(
    table_cells: tuple[tuple[CellLayout, ...], ...], padding: float
) -> tuple[ColumnDemand, ...]:
    count = len(table_cells[0])
    return tuple(
        ColumnDemand(
            max(row[column].minimum_width for row in table_cells) + padding,
            max(row[column].preferred_width for row in table_cells) + padding,
        )
        for column in range(count)
    )


def _allocation_benefits(
    widths: list[float],
    delta: float,
    table_cells: tuple[tuple[CellLayout, ...], ...],
    demands: tuple[ColumnDemand, ...],
    padding: float,
) -> list[float]:
    content_widths = [max(1.0, width - padding) for width in widths]
    wraps = tuple(
        tuple(row[column].wrap(content_widths[column]) for column in range(len(widths)))
        for row in table_cells
    )
    states = tuple(_row_cost_state(row, content_widths) for row in wraps)
    benefits: list[float] = []
    for column, demand in enumerate(demands):
        next_width = max(1.0, widths[column] + delta - padding)
        benefit = _minimum_deficit_penalty(widths[column], demand) - _minimum_deficit_penalty(
            widths[column] + delta, demand
        )
        for row_index, row in enumerate(table_cells):
            state = states[row_index]
            old_wrap = wraps[row_index][column]
            next_wrap = row[column].wrap(next_width)
            old_extra = state.extra_lines[column]
            other_maximum = (
                state.second_extra_lines
                if old_extra == state.maximum_extra_lines and state.maximum_count == 1
                else state.maximum_extra_lines
            )
            next_extra = max(0, next_wrap.lines - 1)
            next_maximum = max(other_maximum, next_extra)
            next_sum = state.extra_line_sum - old_extra + next_extra
            next_overflow = (
                state.overflow_cost
                - _overflow_term(old_wrap.overflow_points, content_widths[column])
                + _overflow_term(next_wrap.overflow_points, next_width)
            )
            weight = HEADER_COST_WEIGHT if row_index == 0 else 1.0
            benefit += _row_cost(state.maximum_extra_lines, state.extra_line_sum, state.overflow_cost, weight)
            benefit -= _row_cost(next_maximum, next_sum, next_overflow, weight)
        benefits.append(max(0.0, benefit))
    return benefits


def _row_cost_state(wraps: tuple[WrapMeasurement, ...], widths: list[float]) -> RowCostState:
    extras = tuple(max(0, result.lines - 1) for result in wraps)
    ordered = sorted(extras, reverse=True)
    maximum = ordered[0] if ordered else 0
    return RowCostState(
        extras,
        sum(extras),
        maximum,
        ordered[1] if len(ordered) > 1 else 0,
        extras.count(maximum),
        sum(_overflow_term(result.overflow_points, widths[index]) for index, result in enumerate(wraps)),
    )


def _row_cost(maximum: int, total: int, overflow: float, weight: float) -> float:
    return weight * (maximum * ROW_WRAP_COST + total * CELL_WRAP_COST + overflow * OVERFLOW_COST)


def _overflow_term(overflow: float, width: float) -> float:
    return 0.0 if overflow <= 0 else (overflow / max(1.0, width)) ** 2


def _minimum_deficit_penalty(width: float, demand: ColumnDemand) -> float:
    deficit = max(0.0, demand.minimum_width - width)
    return 0.0 if deficit <= 0 else (deficit / max(1.0, demand.minimum_width)) ** 2 * MINIMUM_DEFICIT_COST


def _structural_floor(total_width: float, count: int) -> float:
    equal = total_width / count
    return min(equal, max(MIN_COLUMN_WIDTH_POINTS, min(MAX_STRUCTURAL_FLOOR_POINTS, equal * STRUCTURAL_FLOOR_RATIO)))


def _allocation_priority(width: float, demand: ColumnDemand) -> float:
    minimum_gap = max(0.0, demand.minimum_width - width) / max(1.0, demand.minimum_width)
    preferred_gap = max(0.0, demand.preferred_width - width) / max(1.0, demand.preferred_width)
    return minimum_gap * 4.0 + preferred_gap + 0.01 / max(1.0, width)


def _to_percentages(widths: list[float]) -> list[float]:
    total = sum(widths)
    result = [100.0 / len(widths) for _ in widths] if total <= 0 else [width / total * 100.0 for width in widths]
    result[-1] += 100.0 - sum(result)
    return result


def _percentages_to_twips(percentages: list[float], total: int) -> list[int]:
    normalized_total = sum(max(0.0, value) for value in percentages) or 100.0
    widths: list[int] = []
    used = 0
    for index, value in enumerate(percentages):
        width = max(1, total - used) if index == len(percentages) - 1 else max(1, round(total * max(0.0, value) / normalized_total))
        widths.append(width)
        used += width
    return widths


def _get_or_add(parent: Any, tag: str) -> Any:
    child = parent.find(qn(tag))
    if child is None:
        child = OxmlElement(tag)
        parent.append(child)
    return child

from __future__ import annotations

from dataclasses import dataclass

from .table_cell_layout import CellLayout, WrapMeasurement, measure_cell
from .text_measurement import TextMeasurer


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
class ColumnDemand:
    minimum_width: float
    preferred_width: float


@dataclass(frozen=True, slots=True)
class _RowCostState:
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
    measurer: TextMeasurer,
) -> list[float]:
    """Allocates table columns using measured minimum, preferred, and wrap widths."""
    count = len(headers)
    if count <= 0:
        return []
    total_width = max(float(count), available_width_points)
    table_cells = _measure_table(headers, rows, measurer)
    demands = _column_demands(table_cells, cell_padding_points)
    floor = _structural_floor(total_width, count)
    minimum_targets = [max(floor, demand.minimum_width) for demand in demands]
    if sum(minimum_targets) <= total_width + EPSILON:
        widths = minimum_targets
    else:
        widths = [floor for _ in range(count)]

    remaining = max(0.0, total_width - sum(widths))
    while remaining > EPSILON:
        step = (
            1.0
            if remaining <= FINE_ALLOCATION_WINDOW_POINTS
            else COARSE_ALLOCATION_STEP_POINTS
        )
        delta = min(step, remaining)
        if all(
            width >= demand.preferred_width - EPSILON
            for width, demand in zip(widths, demands)
        ):
            extra = remaining / count
            widths = [width + extra for width in widths]
            remaining = 0.0
            break
        benefits = _allocation_benefits(
            widths,
            delta,
            table_cells,
            demands,
            cell_padding_points,
        )
        best_column = 0
        best_key = (-float("inf"), -float("inf"), 0)
        for column in range(count):
            benefit_per_point = benefits[column] / delta
            tie_break = _allocation_priority(widths[column], demands[column])
            key = (benefit_per_point, tie_break, -column)
            if key > best_key:
                best_key = key
                best_column = column
        widths[best_column] += delta
        remaining -= delta
    return _to_percentages(widths)


def _measure_table(
    headers: list[str],
    rows: list[list[str]],
    measurer: TextMeasurer,
) -> tuple[tuple[CellLayout, ...], ...]:
    count = len(headers)
    cache: dict[tuple[str, bool], CellLayout] = {}

    def measure_value(value: str, *, bold: bool) -> CellLayout:
        key = (value, bold)
        layout = cache.get(key)
        if layout is None:
            layout = measure_cell(value, measurer, bold=bold)
            cache[key] = layout
        return layout

    table: list[tuple[CellLayout, ...]] = [
        tuple(measure_value(value, bold=True) for value in headers)
    ]
    for row in rows:
        normalized = (row + [""] * count)[:count]
        table.append(tuple(measure_value(value, bold=False) for value in normalized))
    return tuple(table)


def _column_demands(
    table_cells: tuple[tuple[CellLayout, ...], ...],
    padding: float,
) -> tuple[ColumnDemand, ...]:
    count = len(table_cells[0])
    return tuple(
        ColumnDemand(
            minimum_width=max(row[column].minimum_width for row in table_cells) + padding,
            preferred_width=max(row[column].preferred_width for row in table_cells) + padding,
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
    current_wraps = tuple(
        tuple(
            row[column].wrap(content_widths[column])
            for column in range(len(widths))
        )
        for row in table_cells
    )
    row_states = tuple(_row_cost_state(wraps, content_widths) for wraps in current_wraps)
    benefits: list[float] = []
    for column, demand in enumerate(demands):
        next_content_width = max(1.0, widths[column] + delta - padding)
        benefit = (
            _minimum_deficit_penalty(widths[column], demand)
            - _minimum_deficit_penalty(widths[column] + delta, demand)
        )
        for row_index, row in enumerate(table_cells):
            state = row_states[row_index]
            old_wrap = current_wraps[row_index][column]
            next_wrap = row[column].wrap(next_content_width)
            old_extra = state.extra_lines[column]
            next_extra = max(0, next_wrap.lines - 1)
            if old_extra == state.maximum_extra_lines and state.maximum_count == 1:
                other_maximum = state.second_extra_lines
            else:
                other_maximum = state.maximum_extra_lines
            next_maximum = max(other_maximum, next_extra)
            next_sum = state.extra_line_sum - old_extra + next_extra
            next_overflow = (
                state.overflow_cost
                - _overflow_term(old_wrap.overflow_points, content_widths[column])
                + _overflow_term(next_wrap.overflow_points, next_content_width)
            )
            row_weight = HEADER_COST_WEIGHT if row_index == 0 else 1.0
            current_cost = _row_cost(
                state.maximum_extra_lines,
                state.extra_line_sum,
                state.overflow_cost,
                row_weight,
            )
            next_cost = _row_cost(next_maximum, next_sum, next_overflow, row_weight)
            benefit += current_cost - next_cost
        benefits.append(max(0.0, benefit))
    return benefits


def _row_cost_state(
    wraps: tuple[WrapMeasurement, ...],
    content_widths: list[float],
) -> _RowCostState:
    extra_lines = tuple(max(0, result.lines - 1) for result in wraps)
    ordered = sorted(extra_lines, reverse=True)
    maximum = ordered[0] if ordered else 0
    second = ordered[1] if len(ordered) > 1 else 0
    return _RowCostState(
        extra_lines=extra_lines,
        extra_line_sum=sum(extra_lines),
        maximum_extra_lines=maximum,
        second_extra_lines=second,
        maximum_count=extra_lines.count(maximum),
        overflow_cost=sum(
            _overflow_term(result.overflow_points, content_widths[column])
            for column, result in enumerate(wraps)
        ),
    )


def _row_cost(
    maximum_extra_lines: int,
    extra_line_sum: int,
    overflow_cost: float,
    row_weight: float,
) -> float:
    return row_weight * (
        maximum_extra_lines * ROW_WRAP_COST
        + extra_line_sum * CELL_WRAP_COST
        + overflow_cost * OVERFLOW_COST
    )


def _overflow_term(overflow_points: float, content_width: float) -> float:
    if overflow_points <= 0:
        return 0.0
    return (overflow_points / max(1.0, content_width)) ** 2


def _minimum_deficit_penalty(width: float, demand: ColumnDemand) -> float:
    deficit = max(0.0, demand.minimum_width - width)
    if deficit <= 0:
        return 0.0
    return (deficit / max(1.0, demand.minimum_width)) ** 2 * MINIMUM_DEFICIT_COST


def _structural_floor(total_width: float, count: int) -> float:
    equal_width = total_width / count
    preferred_floor = max(
        MIN_COLUMN_WIDTH_POINTS,
        min(MAX_STRUCTURAL_FLOOR_POINTS, equal_width * STRUCTURAL_FLOOR_RATIO),
    )
    return min(equal_width, preferred_floor)


def _allocation_priority(width: float, demand: ColumnDemand) -> float:
    minimum_gap = max(0.0, demand.minimum_width - width) / max(1.0, demand.minimum_width)
    preferred_gap = max(0.0, demand.preferred_width - width) / max(1.0, demand.preferred_width)
    balance = 1.0 / max(1.0, width)
    return minimum_gap * 4.0 + preferred_gap + balance * 0.01


def _to_percentages(widths: list[float]) -> list[float]:
    total = sum(widths)
    if total <= 0:
        return [100.0 / len(widths) for _ in widths]
    percentages = [width / total * 100.0 for width in widths]
    percentages[-1] += 100.0 - sum(percentages)
    return percentages

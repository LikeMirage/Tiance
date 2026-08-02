from __future__ import annotations

import os

import pytest
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

from app.services.document_conversion.markdown_docx.table_cell_layout import measure_cell
from app.services.document_conversion.markdown_docx.table_layout import calculate_column_widths
from app.services.document_conversion.markdown_docx.text_measurement import FontTextMeasurer
from app.services.document_conversion.markdown_docx.word_table_layout import apply_column_widths


class DeterministicMeasurer:
    backend = "deterministic-test"

    def measure(self, text: str, *, role: str = "text", bold: bool = False) -> float:
        width = sum(
            10.0 if "\u3400" <= char <= "\u9fff" else 2.5 if char.isspace() else 5.0
            for char in text
        )
        return width * (1.1 if bold else 1.0)


def test_cell_layout_tracks_minimum_and_single_line_preferred_widths() -> None:
    measurer = DeterministicMeasurer()
    sentence = measure_cell("This is a long English sentence for wrapping.", measurer)
    unbreakable = measure_cell("Supercalifragilisticexpialidocious", measurer)

    assert sentence.minimum_width < sentence.preferred_width
    assert unbreakable.minimum_width == unbreakable.preferred_width
    assert sentence.wrap(50).lines > sentence.wrap(150).lines
    assert unbreakable.wrap(50).overflow_points > 0


def test_measured_wrap_cost_gives_long_content_more_space() -> None:
    widths = calculate_column_widths(
        ["ID", "说明", "状态"],
        [
            ["1", "The central limit theorem describes convergence for random variables.", "OK"],
            ["2", "短说明", "OK"],
        ],
        available_width_points=504.0,
        cell_padding_points=10.0,
        measurer=DeterministicMeasurer(),
    )

    assert sum(widths) == pytest.approx(100.0)
    assert widths[1] > widths[0] * 3
    assert widths[1] > widths[2] * 3


def test_equal_columns_remain_equal_after_filling_page_width() -> None:
    count = 30
    widths = calculate_column_widths(
        ["A"] * count,
        [["x"] * count],
        available_width_points=504.0,
        cell_padding_points=10.0,
        measurer=DeterministicMeasurer(),
    )

    assert sum(widths) == pytest.approx(100.0)
    assert max(widths) - min(widths) < 1e-9


def test_word_table_is_explicitly_centered_in_available_page_width() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=2)

    apply_column_widths(table, [50.0, 50.0], document)

    alignment = table._tbl.tblPr.find(qn("w:jc"))
    assert table.alignment == WD_TABLE_ALIGNMENT.CENTER
    assert alignment is not None
    assert alignment.get(qn("w:val")) == "center"


def test_formula_exposes_operator_breakpoints_without_losing_minimum_width() -> None:
    cell = measure_cell(
        r"损失函数 $\frac{1}{n}\sum_{i=1}^{n}(y_i-\hat{y}_i)^2$",
        DeterministicMeasurer(),
    )

    assert cell.minimum_width >= 18.0
    assert cell.preferred_width > cell.minimum_width
    assert cell.wrap(cell.minimum_width).lines > 1
    assert cell.wrap(cell.minimum_width / 2).overflow_points > 0


def test_windows_uses_real_gdi_font_measurement() -> None:
    with FontTextMeasurer(
        chinese_font="微软雅黑",
        english_font="Times New Roman",
        math_font="Cambria Math",
        size_points=10.5,
    ) as measurer:
        width = measurer.measure("中文 Hello 123")
        emoji_width = measurer.measure("🚀")
        backend = measurer.backend

    assert width > 0
    assert emoji_width > 0
    if os.name == "nt":
        assert backend == "windows-gdi"

from __future__ import annotations

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.shared import Pt

import markdown_tables
import word_formatting as formatting
import word_table_layout as table_formatting
from inline_writer import InlineWriter
from table_layout import calculate_column_widths
from text_measurement import FontTextMeasurer
from word_formatting import FontSettings
from word_template_model import ContentStyleProfile


TABLE_FONT_SIZE_POINTS = 10.5


class TableWriter:
    """Parses and writes one Markdown pipe table."""

    def __init__(
        self,
        document,
        fonts: FontSettings,
        inline: InlineWriter,
        *,
        content_style: ContentStyleProfile | None = None,
        table_sample: dict[str, object] | None = None,
    ) -> None:
        self._document = document
        self._fonts = fonts
        self._inline = inline
        self._content_style = content_style
        self._table_sample = table_sample
        self._font_size_points = (
            content_style.run.size_pt
            if content_style is not None and content_style.run.size_pt is not None
            else TABLE_FONT_SIZE_POINTS
        )
        self._measurer = FontTextMeasurer(
            chinese_font=self._fonts.chinese,
            english_font=self._fonts.english,
            math_font=self._fonts.math,
            size_points=self._font_size_points,
        )

    def close(self) -> None:
        self._measurer.close()

    def add(self, lines: list[str], start: int) -> int:
        table_lines, end_index = _collect_table_lines(lines, start)
        headers = markdown_tables.parse_table_row(table_lines[0])
        alignments = markdown_tables.parse_table_alignments(table_lines[1])
        rows = [
            markdown_tables.normalize_row(markdown_tables.parse_table_row(line), len(headers))
            for line in table_lines[2:]
        ]
        table = self._document.add_table(rows=len(rows) + 1, cols=len(headers))
        self._apply_table_profile(table)
        available_width_points = table_formatting.document_available_width_points(self._document)
        column_widths = calculate_column_widths(
            headers,
            rows,
            available_width_points=available_width_points,
            cell_padding_points=table_formatting.CELL_HORIZONTAL_PADDING_POINTS,
            measurer=self._measurer,
        )
        table_formatting.apply_column_widths(
            table,
            column_widths,
            self._document,
        )
        self._apply_table_alignment(table)
        margins = (
            self._table_sample.get("cell_margins_twips")
            if self._table_sample is not None
            else None
        )
        table_formatting.set_cell_margins(
            table,
            margins if isinstance(margins, dict) else None,
        )
        borders = (
            self._table_sample.get("table_borders")
            if self._table_sample is not None
            else None
        )
        table_formatting.set_table_borders(
            table,
            borders if isinstance(borders, dict) else None,
        )
        table_formatting.set_repeat_header(table.rows[0])
        self._write_header(
            table,
            headers,
            alignments,
            column_widths,
            available_width_points,
        )
        self._write_body(
            table,
            rows,
            alignments,
            column_widths,
            available_width_points,
        )
        return end_index

    def _write_header(
        self,
        table,
        headers: list[str],
        alignments: list[str],
        column_widths: list[float],
        available_width_points: float,
    ) -> None:
        for column, header in enumerate(headers):
            cell = table.rows[0].cells[column]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            table_formatting.set_cell_shading(cell, self._header_shading())
            paragraph = cell.paragraphs[0]
            formatting.normalize_table_paragraph(
                paragraph,
                style=self._content_style,
            )
            self._inline.write(
                paragraph,
                header,
                font_size=Pt(self._font_size_points),
                max_image_width=_cell_image_width(
                    column_widths,
                    column,
                    available_width_points,
                ),
            )
            for run in paragraph.runs:
                run.bold = True
            _finish_cell(
                paragraph,
                self._fonts,
                self._content_style,
                self._font_size_points,
            )
            formatting.apply_alignment(
                paragraph,
                markdown_tables.header_alignment(alignments, column),
            )

    def _write_body(
        self,
        table,
        rows: list[list[str]],
        alignments: list[str],
        column_widths: list[float],
        available_width_points: float,
    ) -> None:
        for row_index, row_data in enumerate(rows):
            for column, cell_text in enumerate(row_data):
                cell = table.rows[row_index + 1].cells[column]
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                paragraph = cell.paragraphs[0]
                formatting.normalize_table_paragraph(
                    paragraph,
                    style=self._content_style,
                )
                self._inline.write(
                    paragraph,
                    cell_text,
                    font_size=Pt(self._font_size_points),
                    max_image_width=_cell_image_width(
                        column_widths,
                        column,
                        available_width_points,
                    ),
                )
                _finish_cell(
                    paragraph,
                    self._fonts,
                    self._content_style,
                    self._font_size_points,
                )
                formatting.apply_alignment(
                    paragraph,
                    markdown_tables.body_alignment(alignments, column),
                )

    def _apply_table_profile(self, table) -> None:
        style_name = (
            self._table_sample.get("style_name")
            if self._table_sample is not None
            else None
        )
        try:
            table.style = (
                style_name
                if isinstance(style_name, str) and style_name
                else "Table Grid"
            )
        except KeyError:
            table.style = "Table Grid"

    def _apply_table_alignment(self, table) -> None:
        if self._table_sample is None:
            return
        alignment = self._table_sample.get("alignment")
        table_alignment = {
            "left": WD_TABLE_ALIGNMENT.LEFT,
            "center": WD_TABLE_ALIGNMENT.CENTER,
            "right": WD_TABLE_ALIGNMENT.RIGHT,
        }.get(alignment)
        if table_alignment is not None:
            table.alignment = table_alignment

    def _header_shading(self) -> str:
        if self._table_sample is None:
            return "F2F2F2"
        value = self._table_sample.get("first_cell_shading")
        return value if isinstance(value, str) and value else "F2F2F2"


def _collect_table_lines(lines: list[str], start: int) -> tuple[list[str], int]:
    table_lines: list[str] = []
    index = start
    while index < len(lines) and "|" in lines[index]:
        table_lines.append(lines[index])
        index += 1
    return table_lines, index - 1


def _finish_cell(
    paragraph,
    fonts: FontSettings,
    style: ContentStyleProfile | None,
    size_points: float,
) -> None:
    formatting.style_runs(
        paragraph.runs,
        fonts,
        style=style,
        default_size=Pt(size_points),
    )
    formatting.set_runs_default_size(paragraph.runs, Pt(size_points))


def _cell_image_width(
    column_widths: list[float],
    column: int,
    available_width_points: float,
):
    percentage = column_widths[column] if column < len(column_widths) else 0.0
    column_width = available_width_points * percentage / 100.0
    content_width = max(18.0, column_width - table_formatting.CELL_HORIZONTAL_PADDING_POINTS)
    return Pt(content_width)

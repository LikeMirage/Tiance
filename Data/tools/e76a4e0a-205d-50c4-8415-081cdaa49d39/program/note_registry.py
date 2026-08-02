from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import markdown_inline
from warning_collector import WarningCollector


class NoteRegistry:
    """Tracks Markdown note definitions and the Word note ids actually referenced."""

    def __init__(self, warnings: WarningCollector) -> None:
        self._warnings = warnings
        self._footnote_definitions: dict[str, str] = {}
        self._endnote_definitions: dict[str, str] = {}
        self._footnote_ids: dict[str, int] = {}
        self._endnote_ids: dict[str, int] = {}
        self.footnote_entries: list[tuple[int, str]] = []
        self.endnote_entries: list[tuple[int, str]] = []

    def load_definitions(
        self,
        footnotes: dict[str, str],
        endnotes: dict[str, str],
    ) -> None:
        self._footnote_definitions = _normalize_note_definitions(footnotes)
        self._endnote_definitions = _normalize_note_definitions(endnotes)

    def add_reference(self, paragraph, token: str) -> bool:
        label = token[2:-1].strip()
        if label.startswith("end:"):
            key = label[4:].strip()
            return self._add_reference(
                paragraph,
                token=token,
                key=key,
                definitions=self._endnote_definitions,
                ids=self._endnote_ids,
                entries=self.endnote_entries,
                element_name="endnoteReference",
                missing_message="尾注引用缺少定义",
            )
        return self._add_reference(
            paragraph,
            token=token,
            key=label,
            definitions=self._footnote_definitions,
            ids=self._footnote_ids,
            entries=self.footnote_entries,
            element_name="footnoteReference",
            missing_message="脚注引用缺少定义",
        )

    def _add_reference(
        self,
        paragraph,
        *,
        token: str,
        key: str,
        definitions: dict[str, str],
        ids: dict[str, int],
        entries: list[tuple[int, str]],
        element_name: str,
        missing_message: str,
    ) -> bool:
        if not key or key not in definitions:
            self._warnings.append(f"{missing_message}：{token}")
            return False
        note_id = ids.get(key)
        if note_id is None:
            note_id = len(ids) + 1
            ids[key] = note_id
            entries.append((note_id, definitions[key]))
        _append_reference_run(paragraph, element_name, note_id)
        return True


def _append_reference_run(paragraph, element_name: str, note_id: int) -> None:
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(
        qn("w:val"),
        "EndnoteReference" if element_name == "endnoteReference" else "FootnoteReference",
    )
    properties.append(style)
    run.append(properties)
    reference = OxmlElement(f"w:{element_name}")
    reference.set(qn("w:id"), str(note_id))
    run.append(reference)
    paragraph._p.append(run)


def _normalize_note_definitions(definitions: dict[str, str]) -> dict[str, str]:
    return {
        key: markdown_inline.normalize_typographic_double_quotes(value)
        for key, value in definitions.items()
    }

from __future__ import annotations

from app.services.document_conversion.markdown_docx.warning_collector import MAX_WARNING_COUNT, MAX_WARNING_LENGTH, WarningCollector


def test_warning_collector_normalizes_deduplicates_and_bounds_output() -> None:
    collector = WarningCollector()
    collector.append("  同一条\n警告  ")
    collector.append("同一条 警告")
    collector.append("x" * (MAX_WARNING_LENGTH + 20))
    for index in range(MAX_WARNING_COUNT + 5):
        collector.append(f"警告 {index}")

    messages = collector.messages()
    assert messages[0] == "同一条 警告"
    assert len(messages[1]) == MAX_WARNING_LENGTH
    assert messages[1].endswith("…")
    assert len(messages) == MAX_WARNING_COUNT + 1
    assert messages[-1] == "另有 8 条重复或超出上限的警告未展开。"

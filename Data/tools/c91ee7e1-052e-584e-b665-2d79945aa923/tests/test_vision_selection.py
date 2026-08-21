from __future__ import annotations

import json
from pathlib import Path
import sys


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
sys.path.insert(0, str(PROGRAM_ROOT))

from vision_selection import select_vision_images, should_force_ocr_rerun


def write_content_list(path: Path) -> None:
    payload = [
        {
            "type": "image",
            "img_path": f"images/page_{index}.jpg",
            "bbox": [0, 0, 1000, 1000],
            "page_idx": index,
        }
        for index in range(4)
    ]
    payload.append(
        {
            "type": "image",
            "img_path": "images/figure.jpg",
            "bbox": [120, 220, 700, 620],
            "page_idx": 1,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scanned_pages_are_skipped_but_figure_is_selected(tmp_path: Path) -> None:
    content_list = tmp_path / "content_list.json"
    write_content_list(content_list)
    paths = [f"document/auto/images/page_{index}.jpg" for index in range(4)]
    paths.append("document/auto/images/figure.jpg")

    selection = select_vision_images(
        paths,
        content_list_path=content_list,
        known_page_count=4,
        source_suffix=".pdf",
        analyze_full_page_images=False,
    )

    assert selection.mass_full_page_pattern is True
    assert selection.selected_paths == ("document/auto/images/figure.jpg",)
    assert len(selection.skipped_full_page_paths) == 4


def test_explicit_full_page_analysis_keeps_scanned_pages(tmp_path: Path) -> None:
    content_list = tmp_path / "content_list.json"
    write_content_list(content_list)
    paths = [f"images/page_{index}.jpg" for index in range(4)]
    selection = select_vision_images(
        paths,
        content_list_path=content_list,
        known_page_count=4,
        source_suffix=".pdf",
        analyze_full_page_images=True,
    )
    assert selection.selected_paths == tuple(paths)
    assert selection.skipped_full_page_paths == ()


def test_low_text_mass_full_pages_trigger_one_ocr_rerun(tmp_path: Path) -> None:
    content_list = tmp_path / "content_list.json"
    write_content_list(content_list)
    selection = select_vision_images(
        [f"images/page_{index}.jpg" for index in range(4)],
        content_list_path=content_list,
        known_page_count=4,
        source_suffix=".pdf",
        analyze_full_page_images=False,
    )
    assert should_force_ocr_rerun(
        selection=selection,
        markdown_text_chars=0,
        ocr_mode="auto",
        ocr_enabled=False,
    )
    assert not should_force_ocr_rerun(
        selection=selection,
        markdown_text_chars=0,
        ocr_mode="auto",
        ocr_enabled=True,
    )

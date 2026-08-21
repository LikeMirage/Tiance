from __future__ import annotations

from pathlib import Path
import sys


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
sys.path.insert(0, str(PROGRAM_ROOT))

from pdf_ocr_policy import decide_ocr


class FakeObject(dict):
    def get_object(self):
        return self


class FakePage(FakeObject):
    def __init__(self, text: str, *, has_image: bool) -> None:
        resources = FakeObject()
        if has_image:
            resources["/XObject"] = FakeObject({"image": FakeObject({"/Subtype": "/Image"})})
        super().__init__({"/Resources": resources})
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


def reader_factory(pages: list[FakePage]):
    return lambda _path: FakeReader(pages)


def test_auto_keeps_native_text_pdf_without_ocr(tmp_path: Path) -> None:
    pages = [FakePage("这是足够长的原生正文内容。" * 4, has_image=False) for _ in range(5)]
    decision = decide_ocr(tmp_path / "native.pdf", "auto", reader_factory=reader_factory(pages))
    assert decision.enabled is False
    assert decision.text_page_count == 5
    assert decision.scan_candidate_count == 0


def test_auto_enables_ocr_for_scanned_book(tmp_path: Path) -> None:
    pages = [FakePage("", has_image=True) for _ in range(12)]
    decision = decide_ocr(tmp_path / "scan.pdf", "auto", reader_factory=reader_factory(pages))
    assert decision.enabled is True
    assert decision.scan_candidate_count == 12


def test_auto_does_not_force_ocr_for_image_only_cover(tmp_path: Path) -> None:
    pages = [FakePage("", has_image=True)] + [
        FakePage("这是足够长的原生正文内容。" * 4, has_image=False) for _ in range(9)
    ]
    decision = decide_ocr(tmp_path / "cover.pdf", "auto", reader_factory=reader_factory(pages))
    assert decision.enabled is False
    assert decision.scan_candidate_count == 1


def test_image_input_uses_ocr_in_auto_mode(tmp_path: Path) -> None:
    decision = decide_ocr(tmp_path / "page.png", "auto")
    assert decision.enabled is True
    assert decision.page_count == 1

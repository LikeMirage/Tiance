from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from lxml import etree

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": WORD_NS, "m": MATH_NS}
TOOL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def call(root: Path, payload: dict[str, object]) -> dict[str, object]:
    env = os.environ.copy()
    env["TIANCE_WORKSPACE_ROOT"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TOOL_ROOT / "program"), str(REPOSITORY_ROOT / "1_PythonServer")]
    )
    completed = subprocess.run(
        [sys.executable, str(TOOL_ROOT / "program" / "main.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    return json.loads(completed.stdout)


def document_xml(path: Path) -> etree._Element:
    with ZipFile(path) as package:
        return etree.fromstring(package.read("word/document.xml"))


def test_create_uses_content_aware_table_widths_and_native_formula(tmp_path: Path) -> None:
    output = tmp_path / "result.docx"
    result = call(
        tmp_path,
        {
            "action": "create",
            "output_path": output.name,
            "elements": [
                {
                    "type": "table",
                    "rows": [
                        ["编号", "非常长的工作内容说明"],
                        ["1", "这一列需要明显更多宽度，以减少无意义换行。"],
                    ],
                },
                {"type": "equation", "latex": r"\sum_{i=1}^{N} x_i"},
            ],
        },
    )
    assert result["ok"] is True, result
    root = document_xml(output)
    assert root.xpath("count(.//w:tblLayout[@w:type='fixed'])", namespaces=NS) == 1
    widths = [int(value) for value in root.xpath(".//w:tblGrid[1]/w:gridCol/@w:w", namespaces=NS)]
    assert len(widths) == 2
    assert widths[1] > widths[0]
    assert root.xpath("count(.//m:oMath)", namespaces=NS) >= 1


def test_invalid_formula_is_preserved_as_text_with_warning(tmp_path: Path) -> None:
    output = tmp_path / "invalid.docx"
    result = call(
        tmp_path,
        {
            "action": "create",
            "output_path": output.name,
            "elements": [{"type": "equation", "latex": r"\frac{a{b}"}],
        },
    )
    assert result["ok"] is True
    assert any("花括号未配对" in warning for warning in result["warnings"])
    root = document_xml(output)
    assert "\\frac{a{b}" in "".join(root.itertext())

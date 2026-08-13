from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ROOT = TOOL_ROOT / "program"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def load_tool_module():
    sys.path.insert(0, str(PROGRAM_ROOT))
    sys.path.insert(0, str(REPOSITORY_ROOT / "1_PythonServer"))
    spec = importlib.util.spec_from_file_location("mineru_tool_main", PROGRAM_ROOT / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_preserve_structured_artifacts_accepts_prefixed_mineru_names(tmp_path: Path) -> None:
    module = load_tool_module()
    extracted = tmp_path / "extracted" / "document" / "auto"
    extracted.mkdir(parents=True)
    (extracted / "report_content_list.json").write_text('[{"page_idx": 2}]', encoding="utf-8")
    (extracted / "report_content_list_v2.json").write_text('{"pages": []}', encoding="utf-8")
    (extracted / "report_middle.json").write_text('{"pdf_info": []}', encoding="utf-8")
    (extracted / "report_model.json").write_text('[]', encoding="utf-8")

    output_dir = tmp_path / "result"
    preserved = module.preserve_structured_artifacts(tmp_path / "extracted", output_dir)

    assert set(preserved) == {"content_list", "content_list_v2", "middle", "model"}
    assert (output_dir / "structure" / "content_list.json").read_text(encoding="utf-8") == '[{"page_idx": 2}]'
    assert (output_dir / "structure" / "content_list_v2.json").is_file()
    assert (output_dir / "structure" / "middle.json").is_file()
    assert (output_dir / "structure" / "model.json").is_file()

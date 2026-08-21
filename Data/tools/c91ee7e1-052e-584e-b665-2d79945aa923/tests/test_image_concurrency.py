from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ROOT = TOOL_ROOT / "program"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def load_tool_module():
    sys.path.insert(0, str(PROGRAM_ROOT))
    sys.path.insert(0, str(REPOSITORY_ROOT / "1_PythonServer"))
    spec = importlib.util.spec_from_file_location("mineru_tool_image_test", PROGRAM_ROOT / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_image_analysis_has_no_total_limit_and_reuses_duplicates(tmp_path: Path) -> None:
    module = load_tool_module()
    extracted_root = tmp_path / "extracted"
    extracted_root.mkdir()
    relative_paths = []
    for index in range(60):
        path = extracted_root / f"image_{index}.png"
        path.write_bytes(f"unique-{index}".encode())
        relative_paths.append(path.name)
    duplicate = extracted_root / "duplicate.png"
    duplicate.write_bytes((extracted_root / "image_0.png").read_bytes())
    relative_paths.append(duplicate.name)

    active = 0
    peak = 0
    calls = 0
    lock = threading.Lock()

    def fake_analyze(image_path, root, _timeout, _config):
        nonlocal active, peak, calls
        with lock:
            active += 1
            calls += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"ok": True, "image_path": image_path.relative_to(root).as_posix(), "analysis": "ok"}

    module.analyze_single_image = fake_analyze
    options = SimpleNamespace(
        analyze_images=True,
        image_concurrency=50,
        vision_timeout_seconds=10,
        output_dir=tmp_path / "output",
    )
    options.output_dir.mkdir()
    results = module.analyze_images(options, extracted_root, [], object(), relative_paths)

    assert len(results) == 61
    assert calls == 60
    assert 1 < peak <= 50
    reused = [item for item in results if item.get("reused_from")]
    assert len(reused) == 1


def test_mineru_submission_sends_ocr_and_explicit_structure_switches(tmp_path: Path) -> None:
    module = load_tool_module()
    captured = {}

    def fake_post_json(_url, _headers, payload, _timeout, _service_name):
        captured.update(payload)
        return {"data": {"batch_id": "batch", "file_urls": ["https://upload.example/file"]}}

    module.post_json = fake_post_json
    options = SimpleNamespace(source_file=tmp_path / "scan.pdf", request_timeout_seconds=60)
    config = SimpleNamespace(
        mineru_model_version="pipeline",
        mineru_html_model_version="MinerU-HTML",
        mineru_base_url="https://mineru.net",
        mineru_api_key="test",
    )
    module.submit_mineru_task(options, config, is_ocr=True)

    assert captured["files"][0]["is_ocr"] is True
    assert captured["enable_formula"] is True
    assert captured["enable_table"] is True

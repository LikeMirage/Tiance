from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

import browser_capture
import browser_renderer
from latex_extensions import normalize_for_image, normalize_for_omml


def test_html_sanitizer_removes_execution_but_keeps_local_resources() -> None:
    safe = browser_renderer.sanitize_html_fragment(
        """<div onclick="alert(1)" style="background:url('file:///C:/image.png')">
<img src="data:image/png;base64,AAAA">
<script>alert(1)</script>
</div>"""
    )

    assert "file:///C:/image.png" in safe
    assert "data:image/png;base64,AAAA" in safe
    assert "onclick" not in safe
    assert "<script" not in safe


def test_browser_process_is_hidden_on_windows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **options):
        captured.update(options)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(browser_capture.subprocess, "run", fake_run)
    browser_capture._run_browser(
        Path("msedge.exe"),
        ["--headless=new"],
        deadline=time.monotonic() + 1,
    )

    if os.name == "nt":
        assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW
        startupinfo = captured["startupinfo"]
        assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == subprocess.SW_HIDE


def test_browser_budget_counts_render_time_instead_of_converter_age(
    tmp_path: Path,
    monkeypatch,
) -> None:
    moments = iter([100.0, 130.0, 132.0])
    captured: dict[str, object] = {}

    monkeypatch.setattr(browser_renderer.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(
        browser_renderer,
        "render_html_page_png",
        lambda page, output_path, *, timeout_seconds: captured.update(
            page=page,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        ),
    )
    budget = browser_renderer.BrowserRenderBudget(total_seconds=5.0)
    budget.render("<html></html>", tmp_path / "render.png")

    assert captured["timeout_seconds"] == 5.0


def test_katex_render_page_reuses_local_assets_and_inline_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        browser_renderer,
        "render_html_page_png",
        lambda page, output_path, *, timeout_seconds: captured.update(
            page=page,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        ),
    )

    browser_renderer.render_katex_png(
        r"x^2",
        tmp_path / "formula.png",
        display_mode=False,
    )

    page = str(captured["page"])
    assert browser_renderer.KATEX_JS_PATH.as_uri() in page
    assert browser_renderer.KATEX_CSS_PATH.as_uri() in page
    assert "displayMode: false" in page
    assert captured["timeout_seconds"] == browser_renderer.PER_RENDER_TIMEOUT_SECONDS


def test_diagram_normalization_is_isolated_from_formula_style_normalization() -> None:
    normalized, notices = normalize_for_image(
        r"\xymatrix{A\ar[r]^f\ar[d]_g&B\ar[d]^h\\C\ar[r]_k&D}"
    )

    assert notices == ()
    assert r"\xymatrix" not in normalized
    assert r"\begin{CD}" in normalized
    assert "@>{f}>>" in normalized
    assert "@VV{g}V" in normalized

    styled, style_notices = normalize_for_omml(r"\textcolor{red}{x}+\colorbox{yellow}{y}")
    assert r"\style{color:#FF0000}{x}" in styled
    assert r"\style{background:FFFF00}{y}" in styled
    assert len(style_notices) == 1


def test_diagram_normalization_rejects_unsupported_direction() -> None:
    with pytest.raises(ValueError, match="暂不支持 dr 方向箭头"):
        normalize_for_image(r"\xymatrix{A\ar[dr]^f&B\\C&D}")

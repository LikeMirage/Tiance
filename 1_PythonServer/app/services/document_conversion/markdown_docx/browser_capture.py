from __future__ import annotations

import html
import math
import os
import re
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


RENDER_TIMEOUT_SECONDS = 10
MIN_RENDER_DIMENSION = 64
MAX_RENDER_DIMENSION = 4096


def render_html_page_png(
    html_content: str,
    output_path: Path,
    *,
    timeout_seconds: float = RENDER_TIMEOUT_SECONDS,
) -> None:
    """Runs a local Chromium browser to measure and capture one prepared HTML page."""
    errors: list[str] = []
    with TemporaryDirectory(prefix="md2docx-render-html-") as temp_dir:
        html_path = Path(temp_dir) / "render.html"
        html_path.write_text(html_content, encoding="utf-8")
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        for browser_name, browser_path in _browser_candidates():
            try:
                width, height = _measure_rendered_page(browser_path, html_path, deadline)
                _capture_rendered_page(
                    browser_path,
                    html_path,
                    output_path,
                    width,
                    height,
                    deadline,
                )
                return
            except Exception as exc:
                errors.append(f"{browser_name}：{exc}")
    details = "；".join(errors) if errors else "未找到可用浏览器。"
    raise RuntimeError(details)


def _measure_rendered_page(
    browser_path: Path,
    html_path: Path,
    deadline: float,
) -> tuple[int, int]:
    completed = _run_browser(
        browser_path,
        [
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--virtual-time-budget=10000",
            "--dump-dom",
            html_path.as_uri(),
        ],
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise RuntimeError(_summarize_process_error(completed))
    attributes = _read_body_attributes(completed.stdout)
    error = _read_attribute(attributes, "data-error")
    if error:
        raise RuntimeError(html.unescape(error))
    if _read_attribute(attributes, "data-ready") != "true":
        raise RuntimeError("浏览器未完成渲染。")
    width = _read_int_attribute(attributes, "data-width")
    height = _read_int_attribute(attributes, "data-height")
    if width <= 1 or height <= 1:
        raise RuntimeError("渲染结果尺寸无效。")
    if width > MAX_RENDER_DIMENSION or height > MAX_RENDER_DIMENSION:
        raise RuntimeError(
            f"渲染内容尺寸 {width}×{height} 超过 {MAX_RENDER_DIMENSION} 像素限制。"
        )
    return _clamp_render_dimension(width), _clamp_render_dimension(height)


def _capture_rendered_page(
    browser_path: Path,
    html_path: Path,
    output_path: Path,
    width: int,
    height: int,
    deadline: float,
) -> None:
    completed = _run_browser(
        browser_path,
        [
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--virtual-time-budget=10000",
            f"--window-size={width},{height}",
            f"--screenshot={output_path}",
            html_path.as_uri(),
        ],
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise RuntimeError(_summarize_process_error(completed))
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError("浏览器没有生成 PNG 文件。")


def _run_browser(
    browser_path: Path,
    arguments: list[str],
    *,
    deadline: float,
) -> subprocess.CompletedProcess[str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("浏览器渲染超时。")
    windows_options: dict[str, Any] = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        windows_options = {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": startupinfo,
        }
    return subprocess.run(
        [str(browser_path), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, math.ceil(remaining)),
        check=False,
        **windows_options,
    )


@lru_cache(maxsize=1)
def _browser_candidates() -> tuple[tuple[str, Path], ...]:
    candidates: list[tuple[str, Path]] = []
    for browser_name, command in (("Microsoft Edge", "msedge"), ("Google Chrome", "chrome")):
        resolved = shutil.which(command)
        if resolved:
            candidates.append((browser_name, Path(resolved)))
    common_paths = (
        ("Microsoft Edge", Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge", Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")),
        ("Google Chrome", Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")),
        ("Google Chrome", Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")),
    )
    seen = {path.resolve(strict=False) for _, path in candidates}
    for browser_name, path in common_paths:
        resolved = path.resolve(strict=False)
        if path.is_file() and resolved not in seen:
            candidates.append((browser_name, path))
            seen.add(resolved)
    return tuple(candidates)


def _read_body_attributes(markup: str) -> str:
    match = re.search(r"<body\b([^>]*)>", markup, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _read_attribute(attributes: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]*)"', attributes)
    return match.group(1) if match else ""


def _read_int_attribute(attributes: str, name: str) -> int:
    try:
        return int(_read_attribute(attributes, name))
    except ValueError:
        return 0


def _clamp_render_dimension(value: int) -> int:
    return min(max(value, MIN_RENDER_DIMENSION), MAX_RENDER_DIMENSION)


def _summarize_process_error(completed: subprocess.CompletedProcess[str]) -> str:
    details = (completed.stderr or completed.stdout or "").strip()
    if not details:
        return f"浏览器退出码 {completed.returncode}"
    return re.sub(r"\s+", " ", details)[:500]

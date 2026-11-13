"""Load the tool's bundled native media module, independently of Tiance."""
from __future__ import annotations

import importlib
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path

from .common import ASRError


@lru_cache(maxsize=1)
def get_av():
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}-{sysconfig.get_platform().replace('-', '_')}"
    bundled = Path(__file__).resolve().parents[1] / "vendor" / tag
    use_bundled = sys.implementation.name == "cpython" and (bundled / "av/__init__.py").is_file()
    if use_bundled:
        sys.path.insert(0, str(bundled))
    try:
        module = importlib.import_module("av")
    except ImportError as exc:
        if use_bundled:
            message = "工具自带的媒体模块加载失败，请检查工具文件是否完整。"
        else:
            message = "当前 Python 环境没有匹配的自带媒体模块；请为此环境安装 av==16.0.1。"
        raise ASRError("MEDIA_RUNTIME_UNAVAILABLE", message) from exc
    if use_bundled and not Path(module.__file__).resolve().is_relative_to(bundled):
        raise ASRError("MEDIA_RUNTIME_CONFLICT", "当前进程已经加载其他 PyAV，请在独立 Python 进程中运行此工具。")
    return module

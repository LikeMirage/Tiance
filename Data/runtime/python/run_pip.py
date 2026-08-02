from __future__ import annotations

import runpy
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PIP_SITE_PACKAGES = RUNTIME_ROOT / "python-packages" / "pip" / "py313" / "site-packages"

if not PIP_SITE_PACKAGES.is_dir():
    raise SystemExit("内置 pip 不存在。")

sys.path.insert(0, str(PIP_SITE_PACKAGES))
runpy.run_module("pip", run_name="__main__")

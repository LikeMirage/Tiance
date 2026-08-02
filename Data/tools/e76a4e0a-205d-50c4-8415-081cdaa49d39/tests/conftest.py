from __future__ import annotations

import sys
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_DIR = TOOL_ROOT / "program"
DEPENDENCIES_DIR = TOOL_ROOT / "dependencies" / "py313" / "site-packages"

for path in (PROGRAM_DIR, DEPENDENCIES_DIR):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

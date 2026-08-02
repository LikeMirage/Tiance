from __future__ import annotations

import sys
from types import SimpleNamespace


sys.modules.setdefault("tiance_runtime", SimpleNamespace(run_tool=lambda function: None))

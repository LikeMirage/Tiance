from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LlmFunctionalModelSettings:
    settings_id: str
    version: int
    settings: dict[str, Any]
    created_at: str
    updated_at: str

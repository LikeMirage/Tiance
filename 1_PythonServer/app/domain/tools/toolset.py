from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Toolset:
    category_id: str
    name: str
    scope: str
    root_path: str
    readonly: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ToolFolder:
    project_id: str
    category_id: str
    name: str
    root_path: str
    created_at: str
    updated_at: str

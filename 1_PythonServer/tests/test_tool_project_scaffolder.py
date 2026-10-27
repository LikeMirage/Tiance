from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from app.domain.llm.chat import ChatClientCapability, ChatToolCall
from app.domain.project import ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage
from app.repositories.llm.functional_model_settings_repository import LlmFunctionalModelSettingsRepository
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.services.application.project_creation import ProjectCreationApplicationService
from app.services.document_conversion import MarkdownDocxService
from app.services.llm.functional_model_settings import LlmFunctionalModelSettingsService
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.project_files import ProjectFileService
from app.services.project.projects import ProjectService
from app.services.project.conversation_stream_events import client_tool_request_to_payload
from app.services.tools.client_tool_bridge import (
    ClientToolBridgeService, ClientToolResultPayload, client_tool_result_to_chat_tool_result,
)
from app.services.tools.tool_folder_files import ToolFolderFileService
from app.services.tools.tool_metadata import load_tool
from app.services.tools.tool_permissions import evaluate_tool_permissions
from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_projects import ToolProjectService
from app.services.tools.tool_registry import ToolRegistryService

APP_ROOT = Path(__file__).resolve().parents[2]
CREATOR = APP_ROOT / "Data/tools/34b16133-f310-4064-b71f-f0411d13ab1d"


def scaffold_files():
    index = json.loads((CREATOR / "assets/scaffold.json").read_text(encoding="utf-8"))
    return index, [
        (entry["target"], (CREATOR / entry["source"]).read_text(encoding="utf-8"))
        for entry in index["files"]
    ]


def make_services(tmp_path, monkeypatch):
    database = tmp_path / "tiance.db"
    ensure_database_schema(database)
    repository = ProjectRepository(database, file_catalogs=(
        FileProjectCatalog(tmp_path / "tools", project_kind=ProjectKind.TOOL),
    ))
    projects = ProjectService(repository, ProjectStorage(
        tmp_path / "projects", tools_root=tmp_path / "tools",
        roles_root=tmp_path / "roles", themes_root=tmp_path / "themes",
    ))
    conversations = ProjectConversationService(ProjectConversationRepository(repository))
    files = ProjectFileService(repository, FileWorkspaceStorage(), MarkdownDocxService())
    creation = ProjectCreationApplicationService(projects, conversations, files,
        LlmFunctionalModelSettingsService(LlmFunctionalModelSettingsRepository(database)))
    monkeypatch.setattr("app.services.application.project_creation.get_project_creation_application_service", lambda: creation)
    tools = ToolProjectService(projects, files, tmp_path / "tools")
    registry = ToolRegistryService(tools)
    tool_files = ToolFolderFileService(ToolProjectConfigStorage(), FileWorkspaceStorage(), registry, tools)
    return tools, registry, tool_files, conversations


def test_complete_scaffold_uses_existing_creation_and_file_services(tmp_path, monkeypatch):
    tools, registry, files, conversations = make_services(tmp_path, monkeypatch)
    category = tools.create_toolset(name="测试工具")
    folder = tools.create_tool_folder(category.category_id, name='订单"处理')
    assert {p.name for p in Path(folder.root_path).iterdir()} == {".Tiance"}
    assert len(conversations.list_sessions(folder.project_id)) == 1
    index, sources = scaffold_files()
    ordered = sorted(sources, key=lambda item: item[0] == ".tool/tool.json")
    for path, content in ordered:
        if path == ".tool/tool.json":
            manifest = json.loads(content)
            manifest.update(name="test_scaffold_tool", registration_name=folder.name)
            content = json.dumps(manifest, ensure_ascii=False)
        files.write_text_file(category.category_id, folder.project_id, path, content)
        if path != ".tool/tool.json":
            assert registry.list_entries() == ()
    entry = registry.get_entry("test_scaffold_tool")
    assert entry is not None and entry.enabled is False
    assert registry.get_enabled_entry("test_scaffold_tool") is None
    assert (Path(folder.root_path) / index["documentation"]).is_file()
    loaded = load_tool(folder.root_path)
    assert loaded.manifest["registration_name"] == folder.name

    # Exercise the real stdout protocol using the same host helper, in an unrelated cwd.
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT / "1_PythonServer"), "PYTHONIOENCODING": "utf-8"}
    for payload in ["{}", "[]", "not json"]:
        result = subprocess.run([sys.executable, str(Path(folder.root_path) / "program/main.py")],
            input=payload, text=True, encoding="utf-8", capture_output=True, cwd=tmp_path, env=env, timeout=10)
        assert result.returncode == 1
        assert json.loads(result.stdout)["ok"] is False
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=folder.root_path, capture_output=True, text=True, encoding="utf-8", env=env, timeout=15)
    assert result.returncode == 0, result.stderr


def test_creator_metadata_and_templates_are_current_standard_files():
    loaded = load_tool(str(CREATOR))
    assert loaded.name == "create_blank_tool"
    assert loaded.manifest["runtime"]["client_capability"] == {"name": "tool.projects", "min_version": 1}
    storage = ToolProjectConfigStorage()
    for root in (CREATOR, CREATOR / "assets/template"):
        for path in (root / ".tool").glob("*.json"):
            original = json.loads(path.read_text(encoding="utf-8"))
            normalized = json.loads(storage.normalize_standard_file_content(
                f".tool/{path.name}", path.read_text(encoding="utf-8")))
            assert normalized == original, path


@pytest.mark.parametrize("args,decision", [
    ({"action": "list_categories"}, "allow"),
    ({"action": "create_category", "name": "新分类"}, "ask"),
    ({"action": "create_tool", "name": "新工具", "category_id": "category"}, "ask"),
])
def test_creator_read_and_write_permissions(args, decision):
    schema = load_tool(str(CREATOR)).input_schema
    evaluation = evaluate_tool_permissions(tool_name="create_blank_tool", arguments=args,
        input_schema=schema, tool_root=str(CREATOR), workspace_root=None, project_id="caller")
    assert evaluation.decision == decision


@pytest.mark.parametrize("args,valid", [
    ({"action": "list_categories"}, True),
    ({"action": "create_category", "name": "新分类"}, True),
    ({"action": "create_tool", "name": "新工具", "category_id": "category", "call_name": "test_tool"}, True),
    ({}, False),
    ({"action": "create_tool", "category_id": "category"}, False),
    ({"action": "create_tool", "name": 1, "category_id": "category"}, False),
    ({"action": "create_tool", "name": "", "category_id": "category"}, False),
    ({"action": "create_tool", "name": "工具", "category_id": "category", "call_name": "bad name"}, False),
    ({"action": "create_tool", "name": "工具", "category_id": "category", "extra": True}, False),
    ({"action": "create_category", "name": "分类", "category_id": "category"}, False),
    ({"action": "list_categories", "name": "额外参数"}, False),
])
def test_creator_schema_checks_branch_and_root_constraints(args, valid):
    errors = validate_tool_arguments(args, load_tool(str(CREATOR)).input_schema)
    assert (not errors) is valid, errors


def test_client_request_preserves_executed_tool_identity_separate_from_caller():
    async def run():
        bridge = ClientToolBridgeService()
        request = await bridge.create_request(
            ChatToolCall(call_id="call", name="renamed_tool", arguments="{}"),
            project_id="caller-project", session_id="caller-session", timeout_seconds=60,
            tool_project_id="executed-tool-project", capability=ChatClientCapability("tool.projects", 1))
        payload = client_tool_request_to_payload(request)
        assert payload["project_id"] == "caller-project"
        assert payload["tool_project_id"] == "executed-tool-project"
        assert payload["client_capability"] == {"name": "tool.projects", "min_version": 1}
        assert await bridge.should_replay_request(request.request_id)
    asyncio.run(run())


def test_creator_output_contract_describes_final_client_result():
    call = ChatToolCall(call_id="call", name="create_blank_tool", arguments="{}")
    for result in [
        ClientToolResultPayload(ok=True, content={"action": "list_categories", "categories": []}),
        ClientToolResultPayload(ok=True, content={"action": "create_tool", "project": {},
            "enabled": False, "call_name": "new_tool", "template_version": "1.0.0", "files": [],
            "documentation_path": "docs/README.md", "manifest_path": ".tool/tool.json", "guidance": []}),
        ClientToolResultPayload(ok=False, content={"action": "create_tool", "created": False,
            "project": None, "status": "creation_outcome_unknown", "written_files": [],
            "attempted_file": None, "guidance": "先检查目标分类"}, error="响应丢失"),
    ]:
        converted = client_tool_result_to_chat_tool_result(call, result)
        payload = json.loads(converted.content)
        assert validate_tool_arguments(payload, load_tool(str(CREATOR)).output_schema) == []


def test_scaffold_documentation_links_and_inventory_are_complete():
    index, files = scaffold_files()
    assert len({path.casefold() for path, _ in files}) == len(files)
    contents = dict(files)
    assert index["documentation"] in contents
    for path, content in files:
        if not path.endswith(".md"):
            continue
        for link in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", content):
            if "://" not in link:
                target = (Path(path).parent / link).as_posix()
                assert target in contents, (path, link)

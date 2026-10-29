from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc
from dataclasses import replace
from tempfile import TemporaryFile

import pytest

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.domain.llm.chat import ChatToolCall
from app.infra.file_workspace.file_storage import FileWorkspaceStorage
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.repositories.project.project_repository import ProjectRepository
from app.services.tools.tool_execution_runtime import CapturedToolProcess, capture_command
from app.services.tools.tool_execution_results import completed_process_result


def test_repeated_project_lookup_reuses_catalogs_and_external_edits_invalidate(tmp_path, monkeypatch):
    catalogs = []
    for kind in ProjectKind:
        root = tmp_path / kind.value
        catalog = FileProjectCatalog(root, project_kind=kind)
        catalog.save_project_category(ProjectCategory("category", "category", True, 0, "now", "now", kind))
        # Write the complete fixture once; this is not a benchmark of catalog edits.
        payload = catalog._read_payload()
        payload["projects"] = [catalog._project_to_payload(Project(
            f"{kind.value}-{i}", f"name-{i}", str(root / f"{kind.value}-{i}"), False, i,
            "now", "now", "category", kind,
        )) for i in range(100)]
        catalog._write_payload(payload)
        catalogs.append(catalog)
    repository = ProjectRepository(tmp_path / "unused.db", file_catalogs=tuple(catalogs))
    calls = {"read": 0, "parse": 0}
    read, parse = FileProjectCatalog._read_payload, FileProjectCatalog._project_from_payload
    def counted_read(self):
        calls["read"] += 1
        return read(self)
    def counted_parse(self, item):
        calls["parse"] += 1
        return parse(self, item)
    monkeypatch.setattr(FileProjectCatalog, "_read_payload", counted_read)
    monkeypatch.setattr(FileProjectCatalog, "_project_from_payload", counted_parse)
    for _ in range(5):
        assert repository.get_project("provider-99").name == "name-99"
    assert calls == {"read": 7, "parse": 700}
    for _ in range(5):
        assert repository.get_project("provider-99")
    assert calls == {"read": 7, "parse": 700}
    target = catalogs[-1]
    payload = json.loads(target.catalog_path.read_text(encoding="utf-8"))
    payload["projects"][-1]["name"] = "external-name"
    replacement = target.root_path / "replacement.json"
    replacement.write_text(json.dumps(payload), encoding="utf-8")
    replacement.replace(target.catalog_path)
    assert repository.get_project("provider-99").name == "external-name"
    assert calls == {"read": 8, "parse": 800}
    changed = replace(repository.get_project("provider-99"), name="saved-name")
    target.save_project(changed)
    assert repository.get_project("provider-99").name == "saved-name"
    target.catalog_path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        repository.get_project("provider-99")


@pytest.mark.parametrize("inside", [False, True])
def test_search_never_follows_directory_links(tmp_path, inside):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "normal" if inside else tmp_path / "outside"
    target.mkdir()
    (target / "match.txt").write_text("data")
    link = root / "linked"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    nodes = FileWorkspaceStorage().list_tree(str(root), query="match")
    assert all(item.name != "linked" for item in nodes)
    assert [item.name for item in nodes] == (["normal"] if inside else [])


def test_large_tool_result_preserves_json_without_materializing_success_logs():
    size = 16 * 1024 * 1024
    source = '{ "ok": true, "value": "' + "x" * size + '" }\n'
    with TemporaryFile(mode="w+", encoding="utf-8", newline="") as stdout:
        stdout.write(source)
        class UnreadLogs:
            def seek(self, *_):
                pytest.fail("Successful result must not load an unused log stream")
        captured = CapturedToolProcess(0, stdout, UnreadLogs())
        tracemalloc.start()
        try:
            result = completed_process_result(ChatToolCall("call", "tool", "{}"), captured)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert result.ok and result.content == source
        assert peak < size * 3.2


def test_tool_capture_releases_files_on_consumer_error(tmp_path):
    with pytest.raises(RuntimeError, match="consumer"):
        with capture_command([sys.executable, "-c", "print('{}')"], "{}", tmp_path, os.environ.copy(), 10) as captured:
            assert captured.stdout.strip() == "{}"
            raise RuntimeError("consumer")
    assert captured.stdout_file.closed and captured.stderr_file.closed


def test_tool_failure_keeps_complete_stderr(tmp_path):
    log = "failure日志" * 10000
    with TemporaryFile(mode="w+", encoding="utf-8") as out, TemporaryFile(mode="w+", encoding="utf-8") as err:
        out.write('{"ok":false}')
        err.write(log)
        result = completed_process_result(ChatToolCall("call", "tool", "{}"), CapturedToolProcess(1, out, err))
    assert result.error == log


@pytest.mark.parametrize("standalone", [False, True])
def test_backslash_scanning_is_linear_and_preserves_escape_parity(standalone, monkeypatch):
    if standalone:
        root = Path(__file__).resolve().parents[2] / "Data/tools/e76a4e0a-205d-50c4-8415-081cdaa49d39/program"
        monkeypatch.syspath_prepend(str(root))
        spec = importlib.util.spec_from_file_location("tool_inline_regression", root / "markdown_inline.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
    else:
        from app.services.document_conversion.markdown_docx import markdown_inline as module
    class CountedText(str):
        accesses = 0
        def __getitem__(self, key):
            self.accesses += 1
            return super().__getitem__(key)
    text = CountedText("\\" * 16000 + "**bold**")
    tokens = list(module.tokenize_inline(text))
    assert tokens[-1].kind == "format" and tokens[-1].raw == "**bold**"
    assert "".join(item.raw for item in tokens) == text
    assert text.accesses < len(text) * 10
    escaped = list(module.tokenize_inline("\\" * 16001 + "**bold**"))
    assert not any(token.raw == "**bold**" for token in escaped if token.kind == "format")


def test_memory_operation_response_does_not_reload_or_return_all_records(monkeypatch):
    from app.api.routes.project import memory as route
    from app.schemas.project.project_memory import ProjectMemoryOperationRequest
    class Service:
        def apply_operation(self, **kwargs):
            assert kwargs["include_snapshot"] is False
            return {"scope": "project", "operation": "update", "memory_id": "one"}
        def list_memory_records(self, **kwargs):
            pytest.fail("Saving one record must not reload the entire memory list")
    monkeypatch.setattr(route, "get_project_memory_management_service", lambda: Service())
    result = route.apply_project_memory_operation("p", ProjectMemoryOperationRequest(
        scope="project", operation="update", memory_id="one", content="new", reason="edit",
    )).model_dump()
    assert result == {"project_id": "p", "scope": "project", "operation": "update", "memory_id": "one"}


def test_conversation_summary_omits_large_details_and_selected_detail_is_complete(tmp_path, monkeypatch):
    from app.repositories.project.conversation_repository import ProjectConversationRepository
    from app.services.project.project_conversations import ProjectConversationService
    from app.api.routes.project import conversations as route
    from fastapi.encoders import jsonable_encoder
    class Projects:
        def get_project(self, project_id):
            return Project(project_id, "project", str(tmp_path), False, 0, "now", "now")
    repository = ProjectConversationRepository(Projects())
    for i in range(100):
        session = repository.create_session("project-1", title=f"Session {i}", provider_id="p", model_id="m", reasoning_mode=None, settings={"system_prompt": "S" * 16384})
        repository.save_state("project-1", active_session_id=None, should_update_active_session=False,
            session_runtime_statuses={}, session_drafts={session.session_id: "D" * 8192}, session_references={})
    monkeypatch.setattr(route, "get_project_conversation_service", lambda: ProjectConversationService(repository))
    summary = route.list_project_conversation_summaries("project-1")
    assert len(summary["items"]) == 100
    assert all("settings" not in item for item in summary["items"])
    assert all("draft" not in item and "references" not in item for item in summary["session_states"].values())
    size = len(json.dumps(jsonable_encoder(summary)).encode())
    assert size < 160000
    detail = route.get_project_conversation_detail("project-1", session.session_id)
    assert detail["session"].settings.system_prompt == "S" * 16384
    assert detail["state"].draft == "D" * 8192
    assert len(repository.get_list_data("project-1", session_id=session.session_id)[1]) == 1

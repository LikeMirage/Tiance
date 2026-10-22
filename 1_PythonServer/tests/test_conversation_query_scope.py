from concurrent.futures import ThreadPoolExecutor
from json import dumps

import pytest

from app.domain.project import Project
from app.repositories.project import conversation_database as db
from app.repositories.project import conversation_stores as stores
from app.repositories.project.conversation_repository import ProjectConversationRepository


def _seed(conversations_dir, sessions):
    with db.transaction_for_conversations(conversations_dir) as connection:
        connection.executemany(
            "INSERT INTO conversation_sessions(session_id, payload_json) VALUES (?, ?)",
            [(session_id, dumps(payload)) for session_id, payload in sessions.items()],
        )


@pytest.mark.parametrize("requested,expected", [
    (None, {"a", "b", "c"}),
    (set(), set()),
    ({"a"}, {"a"}),
    ({"a", "c", "missing"}, {"a", "c"}),
    ({"missing"}, set()),
])
def test_state_selection_only_decodes_requested_rows(tmp_path, monkeypatch, requested, expected):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {key: {"sequence_number": i} for i, key in enumerate("abc", 1)})
    db.write_session_runtime_state(conversations, "a", "running", "runtime-time")
    db.write_session_draft(conversations, "a", "unsent draft", "draft-time")
    db.write_session_references(conversations, "a", [{"path": "notes.md"}], "reference-time")
    all_states = db.read_session_state_payloads(conversations)
    decoded_rows = []
    original = db._session_state_payloads_from_rows

    def decode(rows):
        decoded_rows.extend(rows)
        return original(rows)

    monkeypatch.setattr(db, "_session_state_payloads_from_rows", decode)
    result = db.read_session_state_payloads(conversations, requested)
    assert result == {key: all_states[key] for key in expected}
    assert len(decoded_rows) == len(expected)
    assert all_states["a"]["draft"] == "unsent draft"
    assert all_states["a"]["references"] == [{"path": "notes.md"}]
    assert all_states["b"]["runtime_status"] == "idle"


def test_empty_state_selection_does_not_open_database(tmp_path, monkeypatch):
    def unexpected(*args):
        raise AssertionError("An empty selection must not read a database")

    monkeypatch.setattr(db, "read_connection_for_path", unexpected)
    assert db.read_session_state_payloads(tmp_path / "conversations", set()) == {}


def test_state_selection_ignores_unrelated_invalid_reference_json(tmp_path):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {"a": {}, "b": {}})
    with db.transaction_for_conversations(conversations) as connection:
        connection.execute(
            "INSERT INTO conversation_session_references(session_id, payload_json, updated_at) VALUES (?, ?, ?)",
            ("b", "{invalid", "now"),
        )
    assert set(db.read_session_state_payloads(conversations, {"a"})) == {"a"}
    with pytest.raises(ValueError):
        db.read_session_state_payloads(conversations, {"b"})


def test_large_state_selection_uses_bound_ids_without_variable_limit_failure(tmp_path):
    conversations = tmp_path / ".Tiance" / "conversations"
    ids = {f"session-{i}" for i in range(1200)} | {"quote'\"中文", "'); DROP TABLE conversation_sessions; --"}
    _seed(conversations, {key: {} for key in ids | {"unrequested"}})
    with db.transaction_for_conversations(conversations) as connection:
        previous_limit = connection.setlimit(db.sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 4)
        try:
            result = db.read_session_state_payloads(conversations, ids)
        finally:
            connection.setlimit(db.sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit)
    assert set(result) == ids
    assert db.session_exists(conversations, "unrequested")


def test_missing_database_reads_do_not_create_workspace(tmp_path):
    conversations = tmp_path / "missing" / "conversations"
    assert db.read_session_state_payloads(conversations) == {}
    assert db.read_session_state_payloads(conversations, {"a"}) == {}
    assert db.read_next_session_sequence_number(conversations) == 1
    assert not conversations.parent.exists()


@pytest.mark.parametrize("numbers,expected", [
    ([], 1),
    ([1, 7, 3], 8),
    ([-5, -2], -1),
    (["17", 5], 18),
    ([True, False, None, "junk", 3.0, "1.2", {}, []], 1),
    ([2**70], 2**70 + 1),
    (["１２", 1], 13),
])
def test_next_sequence_preserves_existing_number_normalization(tmp_path, numbers, expected):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {str(i): {"sequence_number": value} for i, value in enumerate(numbers)})
    assert db.read_next_session_sequence_number(conversations) == expected


def test_numbering_does_not_decode_regular_session_payloads(tmp_path, monkeypatch):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {
        str(i): {"sequence_number": i, "settings": {"system_prompt": "x" * 10000}}
        for i in range(1, 51)
    })

    def unexpected(*args):
        raise AssertionError("Numbering must not decode complete regular sessions")

    monkeypatch.setattr(db, "_decode", unexpected)
    monkeypatch.setattr(stores, "_session_from_payload", unexpected)
    store = stores.ConversationSessionStore(None, state_store=stores.ConversationStateStore())
    assert store.next_sequence_number(conversations) == 51


def test_legacy_numbering_only_decodes_exceptional_records(tmp_path, monkeypatch):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {"regular": {"sequence_number": 20}, "legacy": {"sequence_number": "30"}, "missing": {}})
    decoded = []
    original = db._decode

    def decode(raw):
        payload = original(raw)
        decoded.append(payload)
        return payload

    monkeypatch.setattr(db, "_decode", decode)
    assert db.read_next_session_sequence_number(conversations) == 31
    assert len(decoded) == 2
    assert {"sequence_number": 20} not in decoded


def test_sequence_reads_current_transaction_and_rolls_back_with_creation(tmp_path):
    conversations = tmp_path / ".Tiance" / "conversations"
    _seed(conversations, {"a": {"sequence_number": 3}})
    with pytest.raises(RuntimeError):
        with db.transaction_for_conversations(conversations):
            db.write_session(conversations, "b", {"sequence_number": 8})
            assert db.read_next_session_sequence_number(conversations) == 9
            raise RuntimeError("cancel transaction")
    assert db.read_next_session_sequence_number(conversations) == 4
    db.delete_session(conversations, "a")
    assert db.read_next_session_sequence_number(conversations) == 1


def test_concurrent_session_creation_keeps_unique_sequential_numbers(tmp_path):
    class Projects:
        def get_project(self, project_id):
            return Project(project_id="project", name="project", root_path=str(tmp_path),
                           is_default=False, sort_order=0, created_at="now", updated_at="now")

    repository = ProjectConversationRepository(Projects())

    def create(_):
        return repository.create_session("project", title="new", provider_id=None,
                                         model_id=None, reasoning_mode=None).sequence_number

    with ThreadPoolExecutor(max_workers=4) as executor:
        numbers = list(executor.map(create, range(16)))
    assert sorted(numbers) == list(range(1, 17))

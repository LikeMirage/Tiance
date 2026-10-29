import asyncio
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import threading

import pytest
from tests import test_chat_stream_cancellation as f
from app.infra.database.schema import ensure_database_schema
from app.repositories.project import conversation_schema
from app.infra.file_workspace.file_storage import FileWorkspaceStorage
from app.infra.file_workspace import text_transaction
from app.domain.file_workspace import TextFileUpdate


def engine(chat, conversation, tools=None):
    return f.ProjectConversationStreamService(chat, conversation, f._FakeUsageService(),
        f._FakeNamingService(), f._FakeMemoryService(), tool_execution_service=tools,
        project_service=f._FakeProjectService())


def test_stop_preserves_completed_parallel_tool_results():
    async def run():
        completed = asyncio.Event()
        class Chat:
            async def stream(self, request):
                for call_id in ('fast', 'slow'):
                    yield f.ChatStreamEvent(kind=f.ChatStreamEventKind.TOOL_CALL,
                        tool_call=f.ChatToolCall(call_id=call_id, name='parallel_tool', arguments='{}'))
                yield f.ChatStreamEvent(kind=f.ChatStreamEventKind.DONE, finish_reason='tool_calls')
        class Tools(f._FakeToolExecutionService):
            def is_parallel_tool(self, name): return True
        conversation = f._FakeConversationService()
        service = engine(Chat(), conversation, Tools())
        async def execute(request, call, **kwargs):
            if call.call_id == 'slow': await asyncio.Event().wait()
            yield f.ChatStreamEvent(kind=f.ChatStreamEventKind.TOOL_RESULT,
                tool_result=f.ChatToolResult(call_id=call.call_id, name=call.name,
                    arguments='{}', ok=True, content='finished result'))
            completed.set()
        service._tool_loop._execute_tool_call_events_impl = execute
        async def consume():
            async for _ in service.stream_payloads(replace(f._request(), tools=(f._tool_definition('parallel_tool'),))): pass
        task = asyncio.create_task(consume())
        await asyncio.wait_for(completed.wait(), 3)
        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        fast = [m for m in conversation.appended if m.get('tool_call_id') == 'fast']
        assert len(fast) == 1
        assert fast[0]['status'] == 'done' and 'finished result' in fast[0]['content']
        slow = [m for m in conversation.appended if m.get('tool_call_id') == 'slow']
        assert len(slow) == 1 and slow[0]['status'] == 'cancelled'
    asyncio.run(run())


def test_repeated_stop_during_final_commit_waits_and_does_not_duplicate_reply():
    async def run():
        started, release = threading.Event(), threading.Event()
        class Chat:
            async def stream(self, request):
                yield f.ChatStreamEvent(kind=f.ChatStreamEventKind.DELTA, content='final reply')
                yield f.ChatStreamEvent(kind=f.ChatStreamEventKind.DONE, finish_reason='stop')
        class Conversations(f._FakeConversationService):
            def append_message(self, project_id, session_id, **kwargs):
                if kwargs.get('role') == 'assistant' and kwargs.get('status') == 'done':
                    started.set()
                    assert release.wait(5)
                return super().append_message(project_id, session_id, **kwargs)
        conversation = Conversations()
        service = engine(Chat(), conversation)
        async def consume():
            async for _ in service.stream_payloads(f._request()): pass
        task = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        replies = [m for m in conversation.appended if m['role'] == 'assistant']
        assert len(replies) == 1
        assert replies[0]['status'] == 'done' and replies[0]['content'] == 'final reply'
    asyncio.run(run())


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5, 7])
def test_project_old_schema_rejected_without_changing_any_records(version):
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE TABLE conversation_schema(version INTEGER)')
        db.execute('INSERT INTO conversation_schema VALUES (?)', (version,))
        db.execute('CREATE TABLE original_data(value TEXT)')
        db.execute("INSERT INTO original_data VALUES ('keep')")
        db.commit()
        before = '\n'.join(db.iterdump())
        for _ in range(2):
            with pytest.raises(RuntimeError, match='Unsupported'):
                conversation_schema.ensure_current_schema(db)
            assert '\n'.join(db.iterdump()) == before


def test_new_project_schema_failure_is_atomic_and_retry_succeeds(monkeypatch):
    statements = conversation_schema.SCHEMA_STATEMENTS
    with closing(sqlite3.connect(':memory:')) as db:
        monkeypatch.setattr(conversation_schema, 'SCHEMA_STATEMENTS', (*statements[:3], 'INVALID SQL'))
        with pytest.raises(sqlite3.OperationalError):
            conversation_schema.ensure_current_schema(db)
        assert db.execute('SELECT name FROM sqlite_master').fetchall() == []
        monkeypatch.setattr(conversation_schema, 'SCHEMA_STATEMENTS', statements)
        conversation_schema.ensure_current_schema(db)
        conversation_schema.ensure_current_schema(db)
        assert db.execute('SELECT version FROM conversation_schema').fetchall() == [(6,)]


def test_new_global_schema_failure_rolls_back_all_tables(tmp_path, monkeypatch):
    from app.infra.database import schema
    statements = schema.SCHEMA_STATEMENTS
    path = tmp_path / 'global.db'
    monkeypatch.setattr(schema, 'SCHEMA_STATEMENTS', (*statements[:3], 'INVALID SQL'))
    with pytest.raises(sqlite3.OperationalError):
        schema.ensure_database_schema(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT name FROM sqlite_master').fetchall() == []
    monkeypatch.setattr(schema, 'SCHEMA_STATEMENTS', statements)
    schema.ensure_database_schema(path)


def test_usage_unknown_schema_is_not_silently_repaired(tmp_path):
    from app.repositories.llm.usage_sqlite_store import UsageSqliteStore
    store = UsageSqliteStore(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as db:
        db.execute('CREATE TABLE existing_data(value TEXT)')
        db.execute("INSERT INTO existing_data VALUES ('keep')")
        db.commit()
        before = '\n'.join(db.iterdump())
    with pytest.raises(ValueError, match='No data was converted'):
        store.ensure_ready()
    with closing(sqlite3.connect(store.database_path)) as db:
        assert '\n'.join(db.iterdump()) == before


def test_project_read_rejects_old_schema_without_modifying_file(tmp_path):
    from app.repositories.project import conversation_database
    path = tmp_path / 'tiance.db'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE conversation_schema(version INTEGER)')
        db.execute('INSERT INTO conversation_schema VALUES (3)')
        db.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='Unsupported project'):
        with conversation_database.read_connection_for_path(path):
            pytest.fail('Old project schema must not reach the reader')
    with pytest.raises(RuntimeError, match='Unsupported project'):
        conversation_database.ensure_database(tmp_path)
    assert path.read_bytes() == before


def test_global_current_schema_and_unsupported_version(tmp_path):
    path = tmp_path / 'global.db'
    ensure_database_schema(path)
    ensure_database_schema(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name IN ('projects','project_categories')").fetchall() == []
        db.execute('UPDATE schema_migrations SET version=3')
        db.commit()
    with pytest.raises(RuntimeError, match='Unsupported global'):
        ensure_database_schema(path)


@pytest.mark.parametrize('existing_second', [False, True])
def test_batch_save_rolls_back_first_file_when_second_replace_fails(tmp_path, monkeypatch, existing_second):
    first, second = tmp_path / 'input.schema.json', tmp_path / 'tool.json'
    first.write_bytes(b'old-schema')
    before = first.stat().st_mtime_ns
    if existing_second: second.write_bytes(b'old-tool')
    replace_path = text_transaction.atomic_replace_path
    def fail_second(source, target):
        if target == second and 'rollback' not in source.name: raise OSError('injected second write failure')
        replace_path(source, target)
    monkeypatch.setattr(text_transaction, 'atomic_replace_path', fail_second)
    with pytest.raises(OSError, match='injected'):
        FileWorkspaceStorage().write_text_files(str(tmp_path), [TextFileUpdate(first.name,'new-schema'), TextFileUpdate(second.name,'new-tool')])
    assert first.read_bytes() == b'old-schema' and first.stat().st_mtime_ns == before
    assert second.read_bytes() == b'old-tool' if existing_second else not second.exists()
    assert not list(tmp_path.glob('.*.tmp'))


def test_batch_save_validates_all_paths_before_replacing(tmp_path):
    first = tmp_path / 'input.json';first.write_text('old')
    with pytest.raises(ValueError):
        FileWorkspaceStorage().write_text_files(str(tmp_path), [TextFileUpdate('input.json','new'), TextFileUpdate('../outside.json','escape')])
    assert first.read_text() == 'old'


def test_batch_save_metadata_failure_rolls_back_all_files(tmp_path):
    def fail(): raise ValueError('invalid tool registration')
    with pytest.raises(ValueError, match='registration'):
        FileWorkspaceStorage().write_text_files(str(tmp_path), [TextFileUpdate('a','new'), TextFileUpdate('b','new')], after_write=fail)
    assert not (tmp_path / 'a').exists() and not (tmp_path / 'b').exists()

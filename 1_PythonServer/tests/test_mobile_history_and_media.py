import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.services.mobile import history
from app.services.mobile.telegram_media import message_file
from app.services.mobile.telegram_transport import TelegramError
from app.repositories.project.conversation_history_repository import read_recent_history
from app.repositories.project.conversation_stores import ConversationMessageStore
from tests.test_conversation_message_turn import _message, _session_dir
from tests.test_mobile_access import repository, host

PEER = 'telegram:12:7:7'
TARGET = {'project_id': 'p', 'session_id': 's'}


async def ready(host):
    host.repository = host.repository.scoped('telegram:12')
    await host.put('peers', PEER, {'allowed': True, 'bot_id': 12, 'user_id': 7, 'chat_id': 7})
    await host.put('selection', PEER, TARGET)
    host.desktop.submit = AsyncMock(return_value='job')


async def drain(host):
    while host.work:
        await asyncio.gather(*list(host.work))


async def dispatch(host, number, **body):
    return await host.dispatch(str(number), {'channel': 'telegram:12', 'update': {'update_id': number, 'message': {
        'message_id': number, 'chat': {'id': 7, 'type': 'private'}, 'from': {'id': 7}, **body,
    }}})


def test_global_text_job_does_not_poison_scoped_file_staging(repository):
    scoped = repository.scoped('telegram:12')
    scoped.put('peers', PEER, {'allowed': True})
    key = PEER + ':p:s'
    repository.create_job('text', dict(TARGET, peer=PEER, references=[]), key)
    assert repository.record_connection('staged', key) is None
    refs = [{'reference': {'id': 'voice'}}]
    scoped.append_staged(key, refs)
    repository.create_job('file', dict(TARGET, peer=PEER, references=refs), key)
    assert scoped.get('staged', key) == []
    assert repository.record_connection('staged', key) == 'telegram:12'
    scoped.append_staged(key, refs)
    other = repository.scoped('telegram:13')
    other.put('peers', 'other', {})
    with pytest.raises(ValueError, match='当前连接'):
        repository.create_job('wrong', dict(TARGET, peer='other', references=refs), key)
    assert repository.get('jobs', 'wrong') is None  # Whole transaction rolls back.
    assert scoped.get('staged', key) == refs


def test_recovery_only_discards_owned_empty_unscoped_placeholder(repository):
    scoped = repository.scoped('telegram:12')
    scoped.put('peers', PEER, {})
    repository.put('staged', PEER + ':p:s', [])
    refs = [{'reference': {'id': 'keep'}}]
    repository.put('staged', PEER + ':p:nonempty', refs)
    repository.put('staged', 'telegram:13:7:7:p:s', [])
    repository.scoped('telegram:13').put('staged', PEER + ':p:foreign', [])
    scoped.discard_unowned_empty_staging()
    assert repository.get('staged', PEER + ':p:s') is None
    assert repository.get('staged', PEER + ':p:nonempty') == refs
    assert repository.get('staged', 'telegram:13:7:7:p:s') == []
    assert repository.record_connection('staged', PEER + ':p:foreign') == 'telegram:13'
    scoped.append_staged(PEER + ':p:s', refs)
    assert scoped.get('staged', PEER + ':p:s') == refs


@pytest.mark.parametrize('kind,mime,suffix', [
    ('voice', None, '.ogg'), ('voice', 'audio/mpeg', '.mp3'),
    ('audio', 'audio/mp4', '.m4a'), ('video', None, '.mp4'),
    ('video_note', None, '.mp4'), ('animation', 'image/gif', '.gif'),
    ('document', None, '.bin'),
])
def test_media_variants_get_correct_filename(kind, mime, suffix):
    media = {'file_id': 'original', 'mime_type': mime}
    result = message_file({'message_id': 10, kind: media})
    assert result['file_id'] == 'original' and result['file_name'].endswith(suffix)
    assert 'file_name' not in media
    assert message_file({'message_id': 11, kind: dict(media, file_name='真实文件.m4a')})['file_name'] == '真实文件.m4a'


def test_unsupported_and_failed_file_do_not_block_following_text(host):
    async def run():
        await ready(host)
        await dispatch(host, 1, sticker={'file_id': 'sticker'}, caption='must not submit without media')
        host.transport.download = AsyncMock(side_effect=TelegramError('test download failure'))
        await dispatch(host, 2, voice={'file_id': 'voice'})
        await drain(host)
        assert not host.downloads and not host.submissions
        await dispatch(host, 3, text='hello after failure')
        await drain(host)
        host.desktop.submit.assert_awaited_once()
        assert host.desktop.submit.call_args.args[2].startswith('hello after failure')
        assert await host.get('selection', PEER) == TARGET
        text = '\n'.join(''.join(o['parts']) for _, o in await host.records('outbox'))
        assert '不支持' in text and '文件接收失败' in text
    asyncio.run(run())


def test_inflight_failure_rejects_only_its_waiting_instruction(host):
    async def run():
        await ready(host)
        entered, release = asyncio.Event(), asyncio.Event()
        async def download(*args):
            entered.set()
            await release.wait()
            raise TelegramError('offline')
        host.transport.download = download
        await dispatch(host, 1, video_note={'file_id': 'circle'})
        await entered.wait()
        await dispatch(host, 2, text='analyze video')
        release.set()
        await drain(host)
        host.desktop.submit.assert_not_awaited()
        await dispatch(host, 3, text='unrelated text')
        await drain(host)
        host.desktop.submit.assert_awaited_once()
        assert not host.submissions and not host.downloads
    asyncio.run(run())


def test_clear_pending_download_allows_new_text_without_waiting(host):
    async def run():
        await ready(host)
        entered, release = asyncio.Event(), asyncio.Event()
        async def download(*args):
            entered.set()
            await release.wait()
            raise TelegramError('cancelled intake')
        host.transport.download = download
        await dispatch(host, 1, voice={'file_id': 'file'})
        await entered.wait()
        await host.clear_staging(PEER, TARGET)
        await dispatch(host, 2, text='text only')
        for _ in range(100):
            if host.desktop.submit.await_count:
                break
            await asyncio.sleep(.01)
        host.desktop.submit.assert_awaited_once()
        release.set()
        await drain(host)
        assert not host.downloads
    asyncio.run(run())


@pytest.mark.parametrize('kind,suffix', [('voice', '.ogg'), ('video_note', '.mp4'), ('video', '.mp4')])
def test_media_saved_as_original_file_and_referenced(host, kind, suffix):
    async def run():
        await ready(host)
        paths = []
        async def download(file_id, path):
            path.parent.mkdir(parents=True)
            path.write_bytes(b'original bytes')
            paths.append(path)
        host.transport.download = download
        await dispatch(host, 1, **{kind: {'file_id': 'original'}})
        await drain(host)
        host.desktop.submit.assert_not_awaited()
        await dispatch(host, 2, text='analyze this')
        await drain(host)
        refs = host.desktop.submit.call_args.args[3]
        assert len(refs) == 1 and refs[0]['reference']['fileName'].endswith(suffix)
        assert paths[0].read_bytes() == b'original bytes'
        assert '远程收件' in str(paths[0])
    asyncio.run(run())


def test_recent_history_returns_five_user_turns_without_tool_or_thinking_bodies(tmp_path):
    directory = _session_dir(tmp_path, 'session')
    messages = []
    for i in range(8):
        messages.append(replace(_message(f'u{i}', role='user', content=f'question-{i}'),
                                references=[{'reference': {'fileName': f'file-{i}.mp4', 'filePath': 'video.mp4'}}]))
        for j in range(10):
            messages.append(_message(f't{i}-{j}', role='tool', content='secret tool body' * 1000))
        messages.append(replace(_message(f'a{i}', role='assistant', content=f'answer-{i}' + '长内容' * 1500),
                                thinking_content='private thinking' * 1000))
    ConversationMessageStore().write_messages(directory, tuple(messages))
    turns = read_recent_history(directory, 5)
    assert [t['user_message_id'] for t in turns] == ['u3', 'u4', 'u5', 'u6', 'u7']
    assert turns[-1]['assistant_content'] == 'answer-7' + '长内容' * 1500
    assert turns[0]['references'][0]['reference']['fileName'] == 'file-3.mp4'
    assert 'secret tool body' not in json.dumps(turns)
    assert 'private thinking' not in json.dumps(turns)
    assert read_recent_history(_session_dir(tmp_path, 'other'), 5) == []


def test_history_keeps_unanswered_error_cancelled_and_running_turns(tmp_path):
    directory = _session_dir(tmp_path, 'session')
    ConversationMessageStore().write_messages(directory, (
        _message('u0', role='user', content='unanswered'),
        _message('u1', role='user', content='error'),
        _message('e1', role='error', status='error', content='local failure'),
        _message('u2', role='user', content='paused'),
        _message('a2', role='assistant', status='cancelled', content='partial answer'),
        _message('u3', role='user', content='running'),
        _message('a3', role='assistant', status='running', content='partial stream'),
        _message('u4', role='user', content='tools'),
        _message('a4', role='assistant', content='about to call tool'),
        _message('t4', role='tool', content='not a final answer'),
    ))
    turns = read_recent_history(directory, 5)
    assert turns[0]['assistant_content'] == ''
    assert turns[1]['errors'] == ['local failure']
    assert turns[2]['status'] == 'cancelled'
    assert turns[3]['status'] == 'running'
    assert turns[4]['assistant_content'] == ''


def test_history_reports_local_failure_and_pause_without_assistant_message(tmp_path):
    from app.repositories.project.conversation_database import begin_conversation_run, settle_conversation_run
    directory = _session_dir(tmp_path, 'session')
    ConversationMessageStore().write_messages(directory, (
        _message('failed', role='user', content='local failure before model'),
        _message('paused', role='user', content='cancelled before first token'),
    ))
    for user, status in [('failed', 'error'), ('paused', 'cancelled')]:
        begin_conversation_run(tmp_path / '.Tiance', run_id=user, session_id='session', user_message_id=user, started_at='2026-11-11')
        settle_conversation_run(tmp_path / '.Tiance', run_id=user, session_id='session', status=status,
                                error_code=None, error_message='preparation failed' if status == 'error' else None,
                                attempt_count=0, settled_at='2026-11-11')
    turns = read_recent_history(directory, 5)
    assert turns[0]['status'] == 'error' and turns[0]['errors'] == ['preparation failed']
    assert turns[1]['status'] == 'cancelled' and turns[1]['assistant_content'] == ''


def test_history_button_is_targeted_and_long_reply_is_not_truncated(host, monkeypatch):
    async def run():
        await ready(host)
        rows = await host.navigation.controls(PEER, TARGET)
        button = next(b for row in rows for b in row if b['text'] == '查看前5轮对话')
        action = await host.get('callbacks', button['callback_data'])
        await host.put('selection', PEER, dict(TARGET, session_id='other'))
        answer = '完整答复😀' * 2000
        catalog = NS(recent_history=lambda p,s,**kwargs: [dict(user_content=s, references=[], status='done', assistant_content=answer, errors=[])])
        monkeypatch.setattr(history, 'get_project_conversation_service', lambda: catalog)
        await host.navigation.action(PEER, **{k:v for k,v in action.items() if k != 'peer'})
        await drain(host)
        item = (await host.records('outbox'))[-1][1]
        assert item['target'] == TARGET and answer in ''.join(item['parts'])
        assert len(item['parts']) > 1
        assert (await host.get('selection', PEER))['session_id'] == 'other'
        host.desktop.submit.assert_not_awaited()
    asyncio.run(run())

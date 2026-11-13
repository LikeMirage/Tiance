"""Voice lifecycle tests, using owned local workers without cloud requests."""
import asyncio
import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
import httpx

from app.services.speech import jobs


@pytest.fixture(autouse=True)
def configured_network(monkeypatch):
    monkeypatch.setattr(jobs, 'get_network_proxy_url', lambda: None)
    monkeypatch.setattr(jobs, 'get_http_timeout', lambda: httpx.Timeout(10))


def service(tmp_path):
    return jobs.SpeechJobs(lambda project, session: tmp_path / project / session)


async def ready(svc):
    state = svc.create('project-a', 'conversation-a')
    root = svc.directory('project-a', 'conversation-a', state['id'])
    async def chunks():
        yield b'original recording'
    await svc.upload(root, chunks(), 'audio/webm;codecs=opus')
    return root


def test_real_worker_rejects_invalid_recording_before_cloud(tmp_path):
    async def run():
        svc = service(tmp_path)
        root = await ready(svc)
        svc.start(root)
        await asyncio.wait_for(asyncio.gather(*svc._active.values()), 30)
        result = svc.status(root)
        assert result['status'] == 'failed'
        assert (root / 'result.json').exists(), result
        assert 'InvalidDataError' in result['error'], result
        assert (root / 'source.webm').read_bytes() == b'original recording'
    asyncio.run(run())


def test_recording_owned_by_origin_and_terminal_result_retained(tmp_path, monkeypatch):
    async def run():
        svc = service(tmp_path)
        root = await ready(svc)
        assert (root / 'source.webm').read_bytes() == b'original recording'
        assert root.parent.parent.name == 'conversation-a'
        async def fake_worker(directory, config):
            svc.update(directory, status='completed', text='识别结果')
        monkeypatch.setattr(svc, '_recognize', fake_worker)
        svc.start(root)
        await asyncio.gather(*svc._active.values())
        await asyncio.sleep(0)
        assert not svc._active
        assert service(tmp_path).status(root)['text'] == '识别结果'
        assert service(tmp_path).status(root)['status'] == 'completed'
        await svc.cancel(root)
        assert svc.status(root)['text'] == ''
        assert (root / 'source.webm').exists()
    asyncio.run(run())


def test_cancel_before_worker_first_turn(tmp_path, monkeypatch):
    async def run():
        svc = service(tmp_path)
        root = await ready(svc)
        launched = []
        async def worker(*args):
            launched.append(True)
        monkeypatch.setattr(svc, '_recognize', worker)
        svc.start(root)
        await svc.cancel(root)
        assert not launched and not svc._active
        assert svc.status(root)['status'] == 'cancelled'
        with pytest.raises(Exception):
            svc.start(root)
    asyncio.run(run())


def test_cancel_upload_does_not_start_recognition(tmp_path):
    async def run():
        svc = service(tmp_path)
        state = svc.create('p', 's')
        root = svc.directory('p', 's', state['id'])
        started = asyncio.Event()
        async def chunks():
            yield b'partial'
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(svc.upload(root, chunks(), 'audio/ogg'))
        await started.wait()
        await svc.cancel(root)
        assert task.cancelled()
        assert svc.status(root)['status'] == 'cancelled'
        assert not svc._active
    asyncio.run(run())


def test_restart_marks_interrupted_only(tmp_path):
    svc = service(tmp_path)
    state = svc.create('p', 's')
    root = svc.directory('p', 's', state['id'])
    svc.update(root, status='recognizing')
    assert service(tmp_path).status(root)['status'] == 'failed'
    with pytest.raises(Exception):
        svc.directory('p', 's', '../escape')


def test_cancel_during_process_launch_reaps_owned_worker(tmp_path, monkeypatch):
    original_popen = subprocess.Popen
    launched = threading.Event()
    release = threading.Event()
    children = []
    def delayed_launch(*args, **kwargs):
        child = original_popen([sys.executable, '-c', 'import time; time.sleep(60)'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        children.append(child)
        launched.set()
        release.wait(5)
        return child
    monkeypatch.setattr(jobs.subprocess, 'Popen', delayed_launch)
    async def run():
        svc = service(tmp_path)
        root = await ready(svc)
        svc.start(root)
        task = svc._active[root]
        await asyncio.to_thread(launched.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # Repeated close/cancel must not lose a not-yet-returned handle.
        release.set()
        await svc.cancel(root)
        assert children and all(child.poll() is not None for child in children)
        assert svc.status(root)['status'] == 'cancelled'
    try:
        asyncio.run(run())
    finally:
        release.set()
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_worker_timeout_and_failure_are_persistent(tmp_path, monkeypatch):
    original_popen = subprocess.Popen
    monkeypatch.setattr(jobs.subprocess, 'Popen', lambda *a, **kw: original_popen(
        [sys.executable, '-c', 'import time;time.sleep(60)'], **kw))
    async def run():
        svc = service(tmp_path)
        root = await ready(svc)
        await svc._recognize(root, {'timeout_seconds': 0.1})
        state = svc.status(root)
        assert state['status'] == 'failed' and '超时' in state['error']
        assert (root / 'source.webm').exists()
    asyncio.run(run())

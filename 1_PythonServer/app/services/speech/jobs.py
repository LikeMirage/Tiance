"""Recording lifecycle, owned by its origin conversation rather than visible UI."""
from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.shutdown_tasks import finish_thread, shutdown_tasks
from app.infra.http_client import get_http_timeout, get_network_proxy_url
from app.repositories.project.conversation_stores import ConversationSessionStore, ConversationStateStore
from app.repositories.project.project_repository import get_project_repository
from .jianying_asr.common import write_json

FORMATS = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'm4a', 'audio/wav': 'wav'}
TERMINAL = {'completed', 'failed', 'cancelled'}
LAUNCHER = "import sys,runpy;sys.path[:0]=sys.argv[1:];runpy.run_module('app.services.speech.worker',run_name='__main__')"


class SpeechJobs:
    def __init__(self, session_directory=None):
        self._session_directory = session_directory
        # Only active work lives in memory. Completed records are read from disk.
        self._active: dict[Path, asyncio.Task] = {}

    def directory(self, project_id: str, session_id: str, job_id: str | None = None) -> Path:
        if job_id is not None and not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise NotFoundError('录音任务不存在。')
        if self._session_directory:
            base = self._session_directory(project_id, session_id)
        else:
            store = ConversationSessionStore(get_project_repository(), state_store=ConversationStateStore())
            base = store.require_session_dir(project_id, session_id, for_write=True)
        root = base / 'recordings'
        return root / job_id if job_id else root

    def create(self, project_id: str, session_id: str) -> dict:
        shutdown_tasks.require_accepting()
        job_id = uuid4().hex
        root = self.directory(project_id, session_id, job_id)
        root.mkdir(parents=True, exist_ok=False)
        state = {'id': job_id, 'status': 'created', 'created_at': datetime.now(UTC).isoformat(),
                 'project_id': project_id, 'session_id': session_id, 'directory': str(root)}
        write_json(root / 'recording.json', state)
        return state

    def read(self, root: Path) -> dict:
        try:
            return json.loads((root / 'recording.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise NotFoundError('录音任务不存在。') from None

    def update(self, root: Path, **patch) -> dict:
        state = self.read(root)
        state.update(patch)
        write_json(root / 'recording.json', state)
        return state

    def status(self, root: Path) -> dict:
        state = self.read(root)
        if state['status'] in {'uploading', 'recognizing'} and root not in self._active:
            state = self.update(root, status='failed', error='软件退出中断了识别，原录音仍保存在此会话中。')
        return state

    async def upload(self, root: Path, chunks, content_type: str) -> dict:
        extension = FORMATS.get(content_type.split(';', 1)[0].lower())
        if not extension:
            raise BadRequestError('不支持此录音格式。')
        if self.read(root)['status'] != 'created':
            raise ConflictError('录音任务已上传或取消。')
        task = asyncio.current_task()
        self._active[root] = task
        self.update(root, status='uploading')
        path = root / ('source.' + extension)
        count = 0
        try:
            with path.open('xb') as target:
                async for chunk in chunks:
                    await finish_thread(target.write, chunk)
                    count += len(chunk)
            if not count:
                raise BadRequestError('没有录到声音，请检查麦克风。')
            return self.update(root, status='ready', source=path.name, recording_path=str(path), bytes=count)
        except asyncio.CancelledError:
            self.update(root, status='cancelled')
            raise
        except Exception:
            self.update(root, status='failed', error='录音上传未完成。')
            raise
        finally:
            self._active.pop(root, None)

    def start(self, root: Path) -> dict:
        shutdown_tasks.require_accepting()
        state = self.read(root)
        if state['status'] != 'ready':
            raise ConflictError('此录音不能再次启动识别。')
        settings = get_settings()
        config = {'directory': str(root), 'source': state['source'],
                  'timeout_seconds': settings.speech_recognition_timeout_seconds,
                  'proxy': get_network_proxy_url(), 'network_timeout': get_http_timeout().as_dict()}
        state = self.update(root, status='recognizing')
        task = asyncio.create_task(self._recognize(root, config))
        self._active[root] = task
        task.add_done_callback(lambda done: self._forget(root, done))
        shutdown_tasks.track(task)
        return state

    def _forget(self, root: Path, task: asyncio.Task) -> None:
        if self._active.get(root) is task:
            self._active.pop(root, None)

    async def _recognize(self, root: Path, config: dict) -> None:
        process = None
        try:
            settings = get_settings()
            use_embedded = settings.embedded_python_file.is_file()
            paths = [str(Path(__file__).resolve().parents[3])]
            if use_embedded:
                paths.append(str(settings.backend_site_packages_path))
            paths.extend(p for p in sys.path if p and p not in paths)
            executable = str(settings.embedded_python_file) if use_embedded else sys.executable
            def launch():
                nonlocal process
                process = subprocess.Popen([executable, '-c', LAUNCHER, *paths], stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    process.stdin.write(json.dumps(config).encode('utf-8'))
                    process.stdin.close()
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            # The handle is assigned inside launch. Even repeated cancellation
            # waits for launch to settle before finally terminates the worker.
            async with asyncio.timeout(config['timeout_seconds']):
                await finish_thread(launch)
                while process.poll() is None:
                    await asyncio.sleep(0.2)
            result_path = root / 'result.json'
            if process.returncode != 0 or not result_path.is_file():
                raise RuntimeError('语音识别进程未正常完成，请检查后端语音依赖。')
            result = await finish_thread(lambda: json.loads(result_path.read_text(encoding='utf-8')))
            if result.get('ok'):
                self.update(root, status='completed', text=result['text'])
            else:
                self.update(root, status='failed', error=result.get('error', '语音识别失败。'))
        except asyncio.CancelledError:
            self.update(root, status='cancelled')
            raise
        except TimeoutError:
            self.update(root, status='failed', error='语音识别超时，已停止本次任务，录音已保留。')
        except Exception as exc:
            self.update(root, status='failed', error=str(exc))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                await finish_thread(process.wait)
            (root / 'recording.wav').unlink(missing_ok=True)
            self._active.pop(root, None)

    async def cancel(self, root: Path) -> dict:
        self.read(root)
        task = self._active.get(root)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._forget(root, task)
        # Cancellation also wins a race against an already completed response.
        return self.update(root, status='cancelled', text='')


speech_jobs = SpeechJobs()

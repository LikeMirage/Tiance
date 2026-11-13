"""Exercise the registered project routes with local recordings, without cloud ASR."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import speech
from app.api.router import api_router
from app.services.speech.jobs import SpeechJobs


def test_recording_http_lifecycle(tmp_path, monkeypatch):
    service = SpeechJobs(lambda project, session: tmp_path / project / session)
    monkeypatch.setattr(speech, 'speech_jobs', service)
    started = []

    def recognize(root):
        started.append(root)
        service.update(root, status='completed', text='测试转写')
        return service.status(root)

    monkeypatch.setattr(service, 'start', recognize)
    app = FastAPI()
    app.include_router(api_router)
    with TestClient(app) as client:
        base = '/api/projects/project-a/conversations/session-a/recordings'
        created = client.post(base)
        assert created.status_code == 200, created.text
        path = f"{base}/{created.json()['id']}"
        uploaded = client.put(f'{path}/audio', content=b'recorded audio', headers={'Content-Type': 'audio/webm;codecs=opus'})
        assert uploaded.status_code == 200, uploaded.text
        assert client.post(f'{path}/recognize').status_code == 200
        assert client.get(path).json()['text'] == '测试转写'
        assert client.delete(path).json()['status'] == 'cancelled'
        assert (started[0] / 'source.webm').read_bytes() == b'recorded audio'

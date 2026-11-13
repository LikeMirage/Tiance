import io
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
# Dev pytest may run with system Python; use the same independently installed
# backend media dependency as the packaged worker, never the tool's vendor.
PACKAGES = ROOT / 'runtime/python-packages/backend/py313/site-packages'
if PACKAGES.exists():
    sys.path.append(str(PACKAGES))

import av
import httpx
import pytest
from app.services.speech import worker
from app.services.speech.jianying_asr.common import Budget


def make_browser_recording(path):
    data = io.BytesIO()
    with av.open(data, 'w', format='webm', options={'live': '1'}) as container:
        stream = container.add_stream('libopus', rate=48000)
        stream.layout = 'mono'
        for number in range(50):
            frame = av.AudioFrame(format='s16', layout='mono', samples=960)
            frame.sample_rate = 48000
            frame.pts = number * 960
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    path.write_bytes(data.getvalue())


def test_unknown_duration_webm_is_normalized_locally(tmp_path):
    source = tmp_path / 'source.webm'
    make_browser_recording(source)
    with av.open(str(source)) as incoming:
        assert incoming.duration is None
    output = tmp_path / 'recording.wav'
    worker.normalize_recording(source, output, Budget(10))
    with av.open(str(output)) as result:
        assert abs(result.duration / av.time_base - 1) < .05
        assert result.streams.audio[0].sample_rate == 16000
    assert source.exists()


def test_worker_uses_own_core_explicit_network_and_preserves_original(tmp_path, monkeypatch):
    source = tmp_path / 'source.webm'
    make_browser_recording(source)
    options = []
    def fake_client(budget, **kwargs):
        options.append(kwargs)
        return object()
    def fake_run(payload, *, budget, client_factory):
        assert Path(payload['input_path']).is_file()
        assert payload['formats'] == ['json', 'txt']
        client_factory(budget, tdid='test-device')
        text = tmp_path / 'text.txt'
        text.write_text('你好\n第二句话', encoding='utf-8')
        return {'ok': True, 'data': {'files': [{'format': 'txt', 'path': str(text)}]}}
    monkeypatch.setattr(worker, 'run', fake_run)
    monkeypatch.setattr(worker, 'JianyingClient', fake_client)
    result = worker.recognize({'directory': str(tmp_path), 'source': source.name,
        'timeout_seconds': 10, 'proxy': 'http://127.0.0.1:1234',
        'network_timeout': {'connect': 10, 'read': 120, 'write': 120, 'pool': 10}})
    assert result['text'] == '你好\n第二句话'
    assert source.exists() and not (tmp_path / 'recording.wav').exists()
    assert options[0]['http_options'] == {'trust_env': False, 'proxy': 'http://127.0.0.1:1234'}
    assert options[0]['request_timeout'].read == 120
    assert options[0]['tdid'] == 'test-device'


def test_standalone_and_backend_cores_are_identical():
    sync = runpy.run_path(str(ROOT / 'scripts/sync-speech-core.py'))
    for relative in sync['FILES']:
        assert (sync['TOOL'] / relative).read_bytes() == (sync['BACKEND'] / relative).read_bytes(), relative


@pytest.mark.parametrize('connection_timeout', [False, True])
def test_recording_through_real_engine_and_client(tmp_path, monkeypatch, connection_timeout):
    # Mock only the remote service. The adapter, conversion, part coordinator,
    # client construction, upload protocol and result export all run for real.
    source = tmp_path / 'source.webm'
    make_browser_recording(source)
    requests = []
    identities = []

    async def remote(request):
        requests.append(request.url.path)
        if connection_timeout:
            raise httpx.ConnectTimeout('test timeout', request=request)
        if request.url.path.endswith('upload_sign'):
            return httpx.Response(200, json={'ret': '0', 'data': {
                'access_key_id': 'test-access', 'secret_access_key': 'test-secret',
                'session_token': 'test-token'}})
        if request.url.host == 'vod.bytedanceapi.com':
            return httpx.Response(200, json={'Result': {'UploadAddress': {
                'StoreInfos': [{'StoreUri': 'audio/test', 'UploadID': 'test-upload', 'Auth': 'test-auth'}],
                'UploadHosts': ['upload.test']}}})
        if request.url.host == 'upload.test':
            if request.method == 'PUT':
                assert len(await request.aread()) > 0
            return httpx.Response(200, json={'success': 0})
        if request.url.path.endswith('submit'):
            return httpx.Response(200, json={'ret': '0', 'data': {'id': 'test-task'}})
        assert request.url.path.endswith('query')
        return httpx.Response(200, json={'ret': '0', 'data': {'utterances': [
            {'text': '测试录音', 'start_time': 0, 'end_time': 900, 'words': []}]}})

    real_client = worker.JianyingClient
    def client_with_transport(budget, **kwargs):
        identities.append(kwargs.get('tdid'))
        return real_client(budget, transport=httpx.MockTransport(remote), **kwargs)

    monkeypatch.setattr(worker, 'JianyingClient', client_with_transport)
    result = worker.recognize({'directory': str(tmp_path), 'source': source.name,
        'timeout_seconds': 30, 'proxy': None,
        'network_timeout': {'connect': 10, 'read': 120, 'write': 120, 'pool': 10}})
    assert requests, result
    assert identities and all(identities)
    assert source.exists() and not (tmp_path / 'recording.wav').exists()
    if connection_timeout:
        assert not result['ok'] and result['error_code'] == 'TIMEOUT'
        assert result['data']['failed_parts'][0]['error_stage'] == 'uploading'
    else:
        assert result['ok'], result
        assert result['text'] == '测试录音'
        assert result['data']['statistics']['segments'] == 1
        assert requests[-1].endswith('query')
        assert all(Path(item['path']).is_file() for item in result['data']['files'])

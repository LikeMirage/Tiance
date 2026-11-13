"""Owned, cancellable process. Never imports or executes an installed tool."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

from app.services.speech.jianying_asr.client import JianyingClient
from app.services.speech.jianying_asr.common import Budget, error_details, write_json
from app.services.speech.jianying_asr.engine import run


def normalize_recording(source: Path, destination: Path, budget: Budget) -> None:
    # MediaRecorder WebM often has no duration in its header. Decode incrementally
    # into a finalized lossless file so duration and split boundaries are reliable.
    import av
    with av.open(str(source)) as incoming, av.open(str(destination), 'w', format='wav') as outgoing:
        if not incoming.streams.audio:
            raise ValueError('录音中没有音轨。')
        stream = outgoing.add_stream('pcm_s16le', rate=16000)
        stream.layout = 'mono'
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        for frame in incoming.decode(audio=0):
            budget.remaining()
            for converted in resampler.resample(frame):
                converted.pts = None
                for packet in stream.encode(converted):
                    outgoing.mux(packet)
        for converted in resampler.resample(None):
            converted.pts = None
            for packet in stream.encode(converted):
                outgoing.mux(packet)
        for packet in stream.encode(None):
            outgoing.mux(packet)


def recognize(config: dict) -> dict:
    root = Path(config['directory'])
    budget = Budget(config['timeout_seconds'])
    prepared = root / 'recording.wav'
    try:
        normalize_recording(root / config['source'], prepared, budget)
        def client_factory(part_budget, *, tdid):
            return JianyingClient(part_budget, tdid=tdid, http_options={
                'trust_env': False, 'proxy': config.get('proxy'),
            }, request_timeout=httpx.Timeout(**config['network_timeout']))
        result = run({'input_path': str(prepared), 'output_dir': str(root),
                      'formats': ['json', 'txt']}, budget=budget, client_factory=client_factory)
        if not result['ok']:
            return result
        text_file = next(item['path'] for item in result['data']['files'] if item['format'] == 'txt')
        result['text'] = Path(text_file).read_text(encoding='utf-8').strip()
        return result
    finally:
        # Keep the original recording and complete recognition results, not a
        # redundant decoded copy. Cancellation cleanup is also owned by service.
        prepared.unlink(missing_ok=True)


def main() -> None:
    config = json.loads(sys.stdin.buffer.read())
    try:
        result = recognize(config)
    except Exception as exc:
        code, message = error_details(exc)
        result = {'ok': False, 'error_code': code, 'error': message}
    write_json(Path(config['directory']) / 'result.json', result)


if __name__ == '__main__':
    main()

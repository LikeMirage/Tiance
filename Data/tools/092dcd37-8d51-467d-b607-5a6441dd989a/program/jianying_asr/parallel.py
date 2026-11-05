"""Bounded per-file parallel recognition; result order remains source order."""
from __future__ import annotations

import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import ASRError, error_details, write_json
from .export import segments
from .media import MAX_PARTS, prepare_part
from .signing import device_id


def recognize_parts(source, info, state, job_root, budget, client_factory):
    if not 1 <= len(state["parts"]) <= MAX_PARTS:
        raise ASRError("INVALID_PLAN", "分段计划必须为 1～20 段，不允许额外分段排队。")
    state_lock = threading.Lock()
    preparation_lock = threading.Lock()
    tdid = device_id()

    def update(part, *, warnings=(), final=False, **changes):
        # All workers share one checkpoint: serialize both mutation and replace.
        with state_lock:
            part.update(changes)
            for warning in warnings:
                if warning not in state["warnings"]:
                    state["warnings"].append(warning)
            # A timeout must still be recorded after its working budget expires.
            write_json(job_root / "job.json", state, budget=None if final else budget)

    def worker(index, part):
        stage = "preparing"
        client = None
        try:
            budget.remaining()
            # Each worker owns its HTTP connections; all parts of one job use
            # the same device identity and the same total deadline.
            with client_factory(budget, tdid=tdid) as client:
                with tempfile.TemporaryDirectory(prefix="jianying-asr-") as temporary:
                    # Audio decoding is serialized to keep CPU and memory bounded;
                    # uploads and cloud recognition overlap with subsequent cuts.
                    with preparation_lock:
                        budget.remaining()
                        update(part, status="preparing")
                        print(f"处理音频 {index}/{len(state['parts'])} 段，起点 {part['start_seconds']:.3f} 秒。", file=sys.stderr)
                        audio = prepare_part(source, info, part["start_seconds"],
                                             part["duration_seconds"], Path(temporary), budget)
                    processing = ("original" if audio == source else
                                  "aac_packet_copy" if audio.suffix == ".m4a" else "decoded_flac")
                    stage = "uploading"
                    update(part, status="uploading", audio_processing=processing, upload_bytes=audio.stat().st_size)
                    uri = client.upload(audio)
                # The upload is complete; no need to keep the temporary audio
                # on disk while waiting for the remote recognizer.
                stage = "submitting"
                update(part, status="submitting")
                task_id = client.submit(uri)
                stage = "processing"
                update(part, status="processing", task_id=task_id)
                response = client.poll(task_id)
                stage = "saving"
                raw_path = f"parts/{index:04d}.raw.json"
                write_json(job_root / raw_path, response, budget=budget)
                update(part, raw_result=raw_path)
                count = sum(1 for _ in segments(response, part["offset_ms"]))
                if not count:
                    client.warnings.append(f"第 {index} 段云端返回空转写结果；不能仅据此判断原音频没有语音。")
                update(part, status="completed", segments=count, warnings=client.warnings)
        except Exception as exc:
            code, message = error_details(exc)
            update(part, final=True, status="failed", error_code=code, error=message,
                   error_stage=stage, warnings=getattr(client, "warnings", ()))

    workers = len(state["parts"])
    state["max_concurrent_parts"] = MAX_PARTS
    state["concurrent_parts"] = workers
    write_json(job_root / "job.json", state, budget=budget)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="jianying-asr") as pool:
        futures = [pool.submit(worker, index, part) for index, part in enumerate(state["parts"], 1)]
        for future in as_completed(futures):
            # The worker records ordinary errors. Checkpoint failures propagate.
            future.result()
    failed = [part for part in state["parts"] if part["status"] == "failed"]
    if failed:
        raise ASRError(failed[0]["error_code"],
                       f"{len(failed)}/{len(state['parts'])} 个分段失败：{failed[0]['error']} 已保留成功分段和任务记录。")

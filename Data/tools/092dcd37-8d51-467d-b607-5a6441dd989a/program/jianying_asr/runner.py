from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from .client import JianyingClient
from .common import ASRError, Budget, error_details, write_json
from .export import FORMATS, write_outputs
from .media import MAX_PARTS, SEGMENT_SECONDS, plan_parts, probe
from .parallel import recognize_parts
from .silk import prepare_source


def validate(payload: dict) -> tuple[Path, Path, list[str]]:
    if not isinstance(payload, dict) or set(payload) - {"input_path", "output_dir", "formats"}:
        raise ASRError("INVALID_ARGUMENTS", "仅接受 input_path、output_dir、formats 三个参数。")
    for key in ("input_path", "output_dir"):
        if key in payload and (not isinstance(payload[key], str) or not payload[key].strip()):
            raise ASRError("INVALID_ARGUMENTS", f"{key} 必须是非空路径字符串。")
    if "input_path" not in payload:
        raise ASRError("INVALID_ARGUMENTS", "缺少 input_path。")
    formats = payload.get("formats", ["json"])
    if not isinstance(formats, list) or not formats or any(type(x) is not str or x not in FORMATS for x in formats):
        raise ASRError("INVALID_ARGUMENTS", "formats 必须是 json、txt、srt、ass 组成的非空数组。")
    if len(formats) != len(set(formats)):
        raise ASRError("INVALID_ARGUMENTS", "formats 中不能重复指定同一种格式。")
    root_value = os.environ.get("TIANCE_WORKSPACE_ROOT", "").strip()
    if not root_value and os.environ.get("TIANCE_TOOLS_ROOT") and (
        "output_dir" not in payload or not Path(payload["input_path"]).is_absolute()
        or not Path(payload["output_dir"]).is_absolute()
    ):
        raise ASRError("WORKSPACE_REQUIRED", "当前调用没有工作区，请提供绝对输入路径和输出目录。")
    workspace = Path(root_value or Path.cwd()).resolve()
    source = Path(payload["input_path"]).expanduser()
    destination = Path(payload.get("output_dir", str(workspace))).expanduser()
    source = (workspace / source).resolve()
    destination = (workspace / destination).resolve()
    if not source.is_file():
        raise ASRError("INPUT_NOT_FOUND", f"输入文件不存在或不是文件：{source}")
    if destination.exists() and not destination.is_dir():
        raise ASRError("INVALID_OUTPUT", "output_dir 必须是目录，不能是文件。")
    return source, destination, formats


def configured_budget() -> Budget:
    manifest = Path(__file__).resolve().parents[2] / ".tool" / "tool.json"
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))["runtime"]["timeout_seconds"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ASRError("CONFIG_ERROR", "无法读取 .tool/tool.json 的 runtime.timeout_seconds。") from exc
    return Budget(value)


def run(payload: dict, *, client_factory=JianyingClient, budget: Budget | None = None) -> dict:
    job_root = None
    state: dict = {}
    started = time.monotonic()
    try:
        source, output, formats = validate(payload)
        budget = budget or configured_budget()
        fingerprint = (source.stat().st_size, source.stat().st_mtime_ns)
        with prepare_source(source, budget) as prepared:
            info = probe(prepared)
            budget.remaining()
            output.mkdir(parents=True, exist_ok=True)
            # An exclusive job directory prevents overwrites and interleaved concurrent outputs.
            job_root = Path(tempfile.mkdtemp(prefix=source.stem + "_asr_", dir=output))
            (job_root / "parts").mkdir()
            state = {"schema_version": 3, "input_path": str(source), "source_bytes": fingerprint[0],
                     "source_mtime_ns": fingerprint[1], "duration_seconds": info.duration,
                     "target_segment_seconds": SEGMENT_SECONDS, "max_parts": MAX_PARTS,
                     "split_mode": "balanced", "formats": formats, "status": "running",
                     "parts": [], "files": [], "warnings": []}
            if prepared != source:
                state["source_decoding"] = "silk_v3_to_wav"
            for start, length in plan_parts(info.duration, frame_seconds=info.copy_frame_seconds):
                state["parts"].append({"part_number": len(state["parts"]) + 1,
                                       "start_seconds": start, "offset_ms": round(start * 1000),
                                       "duration_seconds": length, "status": "pending"})
            write_json(job_root / "job.json", state, budget=budget)
            recognize_parts(prepared, info, state, job_root, budget, client_factory)
            if fingerprint != (source.stat().st_size, source.stat().st_mtime_ns):
                raise ASRError("INPUT_CHANGED", "处理期间原文件被修改，已保留分段结果，但不能认定为同一份完整音频。")
            files, stats = write_outputs(job_root, source.stem, formats, state["parts"], budget)
            state.update(status="completed", files=files, statistics=stats, elapsed_seconds=round(time.monotonic() - started, 3))
            write_json(job_root / "job.json", state, budget=budget)
            return {"ok": True, "summary": "识别完成，完整结果已保存。" if stats["segments"] else "云端返回空转写结果，已保存。",
                    "data": {"input_path": str(source), "output_dir": str(job_root),
                             "duration_seconds": info.duration, "part_count": len(state["parts"]),
                             "files": files, "statistics": stats, "elapsed_seconds": state["elapsed_seconds"],
                             "job_file": str(job_root / "job.json"), "warnings": state["warnings"]}}
    except Exception as exc:
        # Network exceptions have already been sanitized by the client; never emit a traceback or auth URL.
        code, message = error_details(exc)
        result = {"ok": False, "error_code": code, "error": message}
        if job_root is not None:
            # If checkpoint/local failures interrupted coordination, do not leave
            # uncompleted parts looking active in a terminal job record.
            for part in state.get("parts", []):
                if part["status"] not in ("completed", "failed"):
                    part.update(error_stage=part["status"], status="failed", error_code=code, error=message)
            state.update(status="failed", error_code=code, error=message)
            try:
                write_json(job_root / "job.json", state)
            except OSError:
                result["checkpoint_error"] = "无法写入最终状态；此前已保存的分段文件仍位于结果目录。"
            result["data"] = {"output_dir": str(job_root), "job_file": str(job_root / "job.json"),
                              "completed_parts": sum(p["status"] == "completed" for p in state.get("parts", [])),
                              "total_parts": len(state.get("parts", [])),
                              "failed_parts": [{key: p[key] for key in
                                                ("part_number", "start_seconds", "duration_seconds", "task_id",
                                                 "error_stage", "error_code", "error") if key in p}
                                               for p in state.get("parts", []) if p["status"] == "failed"],
                              "warnings": state.get("warnings", [])}
        return result

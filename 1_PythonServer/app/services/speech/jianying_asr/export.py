from __future__ import annotations

import json
import math
from pathlib import Path

from .common import ASRError, atomic_replace

FORMATS = ("json", "txt", "srt", "ass")


def time_value(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ASRError("INVALID_TIMESTAMPS", "识别结果包含无效时间戳；原始结果已保留。")
    return round(value)


def segments(response: dict, offset_ms: int):
    items = response.get("data", {}).get("utterances")
    if not isinstance(items, list):
        raise ASRError("INVALID_RESPONSE", "识别结果缺少句段列表。")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ASRError("INVALID_RESPONSE", "识别结果包含无效句段；原始结果已保留。")
        segment = {"text": item["text"], "startMs": time_value(item.get("start_time")) + offset_ms,
                   "endMs": time_value(item.get("end_time")) + offset_ms}
        if "words" in item and item["words"] is not None:
            if not isinstance(item["words"], list):
                raise ASRError("INVALID_RESPONSE", "识别结果词级列表格式错误。")
            words = []
            for word in item["words"]:
                if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                    raise ASRError("INVALID_RESPONSE", "识别结果包含无效词条。")
                words.append({"text": word["text"], "startMs": time_value(word.get("start_time")) + offset_ms,
                              "endMs": time_value(word.get("end_time")) + offset_ms})
            segment["words"] = words
        yield segment


def all_segments(parts: list[dict], root: Path):
    for part in parts:
        if part["status"] != "completed":
            raise ASRError("INCOMPLETE_RESULT", "存在未完成的音频分段，不能生成完整结果。")
        with (root / part["raw_result"]).open(encoding="utf-8") as source:
            yield from segments(json.load(source), part["offset_ms"])


def subtitle_time(ms: int, *, ass=False) -> str:
    units = ms // 10 if ass else ms
    fraction_base = 100 if ass else 1000
    seconds, fraction = divmod(units, fraction_base)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return (f"{hour}:{minute:02}:{second:02}.{fraction:02}" if ass else
            f"{hour:02}:{minute:02}:{second:02},{fraction:03}")


ASS_HEADER = """[Script Info]
Title: JianYing subtitles
ScriptType: v4.00+
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,14,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,2,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_outputs(root: Path, stem: str, formats: list[str], parts: list[dict], budget) -> tuple[list[dict], dict]:
    paths = {fmt: root / f"{stem}.{fmt}" for fmt in formats}
    from contextlib import ExitStack
    stats = {"segments": 0, "words": 0, "text_characters": 0, "non_positive_word_durations": 0}
    with ExitStack() as stack:
        streams = {fmt: stack.enter_context(path.with_suffix(path.suffix + ".tmp").open(
            "w", encoding="utf-8", newline="\n")) for fmt, path in paths.items()}
        if "json" in streams:
            streams["json"].write("[\n")
        if "ass" in streams:
            streams["ass"].write(ASS_HEADER)
        for index, segment in enumerate(all_segments(parts, root), 1):
            budget.remaining()
            text, start, end = segment["text"], segment["startMs"], segment["endMs"]
            stats["segments"] += 1
            stats["text_characters"] += len(text)
            stats["words"] += len(segment.get("words", []))
            stats["non_positive_word_durations"] += sum(w["endMs"] <= w["startMs"] for w in segment.get("words", []))
            if "json" in streams:
                if index > 1:
                    streams["json"].write(",\n")
                json.dump(segment, streams["json"], ensure_ascii=False, allow_nan=False)
            if "txt" in streams:
                streams["txt"].write(text + "\n")
            if "srt" in streams:
                streams["srt"].write(f"{index}\n{subtitle_time(start)} --> {subtitle_time(end)}\n{text}\n\n")
            if "ass" in streams:
                escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                escaped = escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
                streams["ass"].write(f"Dialogue: 0,{subtitle_time(start, ass=True)},{subtitle_time(end, ass=True)},Default,,0,0,0,,{escaped}\n")
        if "json" in streams:
            streams["json"].write("\n]\n")
    for path in paths.values():
        atomic_replace(path.with_suffix(path.suffix + ".tmp"), path, budget=budget)
    files = [{"format": fmt, "path": str(path), "bytes": path.stat().st_size} for fmt, path in paths.items()]
    return files, stats

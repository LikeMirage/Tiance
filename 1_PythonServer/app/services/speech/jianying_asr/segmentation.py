"""Move balanced cut points into nearby pauses without changing audio or part count."""
from __future__ import annotations

import math
from fractions import Fraction

from .media_runtime import get_av

SEARCH_SECONDS = 15.0
MIN_PAUSE_SECONDS = 0.35
EDGE_GUARD_SECONDS = 0.08
ANALYSIS_RATE = 8000
FRAME_SAMPLES = 160  # 20 ms, only for analysis; uploaded audio keeps its format/rate.


def _levels(source, start, end, budget):
    """Read just a cut's neighbourhood, retaining the original audio timeline.

    Check each channel separately: mixing opposite-phase stereo to mono could
    turn speech into apparent silence. No NumPy or external VAD is required.
    """
    av = get_av()
    levels = []
    with av.open(str(source)) as reader:
        stream = reader.streams.audio[0]
        origin = stream.start_time * stream.time_base if stream.start_time is not None else None
        if origin is not None and start > 1:
            try:
                reader.seek(int((origin + Fraction(str(start - 1))) / stream.time_base),
                            stream=stream, backward=True)
            except av.error.FFmpegError:
                # Reopen after a failed seek; the decoder's position is unknown.
                return _levels_from_start(source, start, end, budget)
        levels = _decode_levels(reader, stream, origin, start, end, budget)
    return levels


def _levels_from_start(source, start, end, budget):
    av = get_av()
    with av.open(str(source)) as reader:
        stream = reader.streams.audio[0]
        origin = stream.start_time * stream.time_base if stream.start_time is not None else None
        return _decode_levels(reader, stream, origin, start, end, budget)


def _decode_levels(reader, stream, origin, start, end, budget):
    av = get_av()
    resampler = None
    levels = []

    def consume(frame):
        budget.remaining()
        if frame.pts is None or frame.time_base is None:
            raise ValueError("Missing analysis timestamp")
        left = float(frame.pts * frame.time_base - origin)
        right = left + frame.samples / ANALYSIS_RATE
        # Whole windows only. Partial edges must not manufacture a quiet gap.
        if left < start - 1e-6 or right > end + 1e-6:
            return
        channels = len(frame.layout.channels)
        samples = memoryview(frame.planes[0]).cast("h")[:frame.samples * channels]
        power = max(sum(value * value for value in samples[channel::channels]) / frame.samples
                    for channel in range(channels))
        db = 10 * math.log10(max(power / (32768 ** 2), 1e-12))
        levels.append((left, right, db))

    for frame in reader.decode(stream):
        budget.remaining()
        if frame.pts is None or frame.time_base is None:
            raise ValueError("Missing source timestamp")
        if origin is None:
            origin = frame.pts * frame.time_base
        left = float(frame.pts * frame.time_base - origin)
        if left > end + 0.1:
            break
        # In unseekable files, decode to the window without resampling the prefix.
        if left + frame.samples / frame.sample_rate < start - 1:
            continue
        if resampler is None:
            resampler = av.AudioResampler(format="s16", layout=frame.layout,
                                         rate=ANALYSIS_RATE, frame_size=FRAME_SAMPLES)
        for output in resampler.resample(frame):
            consume(output)
    if resampler is not None:
        for output in resampler.resample(None):
            consume(output)
    return levels


def _pauses(levels):
    if not levels:
        return [], None
    ordered = sorted(db for _, _, db in levels)
    floor = ordered[len(ordered) // 10]
    speech = ordered[min(len(ordered) - 1, len(ordered) * 9 // 10)]
    # Require both an absolute quiet level and a substantial drop from speech.
    # Flat continuous speech/noise therefore does not get a forced "pause".
    threshold = (-100.0 if ordered[-1] <= -100 else
                 min(-32.0, speech - 12.0, max(-60.0, floor + 6.0)))
    pauses = []
    run_start = run_end = None

    def finish():
        if run_start is not None and run_end - run_start >= MIN_PAUSE_SECONDS - 1e-6:
            pauses.append((run_start, run_end))

    for left, right, db in levels:
        # Never treat missing timestamps/audio as silence or bridge a loud frame.
        if run_end is not None and abs(left - run_end) > 0.005:
            finish()
            run_start = run_end = None
        if db <= threshold:
            if run_start is None:
                run_start = left
            run_end = right
        else:
            finish()
            run_start = run_end = None
    finish()
    return pauses, threshold


def refine_parts(source, info, parts, budget):
    """Return adjacent parts and auditable decisions; retain original cuts if unsure."""
    decisions = []
    boundaries = [start for start, _ in parts] + [sum(parts[-1])]
    av = get_av() if len(parts) > 1 else None
    for index in range(1, len(parts)):
        budget.remaining()
        target = parts[index][0]
        radius = min(SEARCH_SECONDS, parts[index - 1][1] / 4, parts[index][1] / 4)
        decision = {"target_seconds": target, "actual_seconds": target,
                    "search_start_seconds": target - radius, "search_end_seconds": target + radius,
                    "reason": "no_pause"}
        try:
            levels = _levels(source, target - radius, target + radius, budget)
            pauses, threshold = _pauses(levels)
            decision["threshold_dbfs"] = threshold
            candidates = []
            for left, right in pauses:
                cut = (left + right) / 2
                if left + EDGE_GUARD_SECONDS <= target <= right - EDGE_GUARD_SECONDS:
                    cut = target
                if info.copy_frame_seconds is not None:
                    quantum = Fraction(info.copy_frame_seconds)
                    cut = float(round(Fraction(str(cut)) / quantum) * quantum)
                if left + EDGE_GUARD_SECONDS <= cut <= right - EDGE_GUARD_SECONDS:
                    candidates.append((abs(cut - target), cut, left, right))
            if candidates:
                _, cut, left, right = min(candidates)
                boundaries[index] = cut
                decision.update(actual_seconds=cut, reason="silence",
                                silence_start_seconds=left, silence_end_seconds=right)
        except (av.error.FFmpegError, OSError, ValueError) as exc:
            # This optimisation is optional. A decoder that cannot analyse a
            # window must not break an otherwise supported packet-copy upload.
            # Budget/cancellation ASRError deliberately propagates.
            decision.update(reason="analysis_unavailable", error_type=type(exc).__name__)
        decisions.append(decision)
    return ([(left, right - left) for left, right in zip(boundaries, boundaries[1:])],
            {"search_radius_seconds": SEARCH_SECONDS, "minimum_pause_seconds": MIN_PAUSE_SECONDS,
             "boundaries": decisions})

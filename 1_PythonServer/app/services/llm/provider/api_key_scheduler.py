# API Key 调度器
# 加权轮询调度算法，在多 API Key 之间按权重均匀分配请求

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic


@dataclass(frozen=True, slots=True)
class ProviderRuntimeApiKey:
    key_id: str
    api_key: str
    api_key_hint: str | None
    poll_weight: int


@dataclass(slots=True)
class _ProviderRotationState:
    signature: tuple[tuple[str, int], ...]
    total_weight: int
    next_position: int


class ProviderApiKeyScheduler:
    def __init__(self) -> None:
        self._states: dict[str, _ProviderRotationState] = {}
        self._selected_at: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def select_next(
        self,
        provider_id: str,
        candidates: tuple[ProviderRuntimeApiKey, ...],
    ) -> ProviderRuntimeApiKey | None:
        active_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.poll_weight > 0 and candidate.api_key
        )
        if not active_candidates:
            with self._lock:
                self._states.pop(provider_id, None)
            return None

        signature = tuple(
            (candidate.key_id, candidate.poll_weight)
            for candidate in active_candidates
        )
        total_weight = sum(candidate.poll_weight for candidate in active_candidates)

        with self._lock:
            state = self._states.get(provider_id)
            if (
                state is None
                or state.signature != signature
                or state.total_weight != total_weight
            ):
                state = _ProviderRotationState(
                    signature=signature,
                    total_weight=total_weight,
                    next_position=0,
                )
                self._states[provider_id] = state

            selected_position = state.next_position
            state.next_position = (selected_position + 1) % total_weight

        selected_candidate = _select_candidate_at_position(active_candidates, selected_position)
        self._record_selection(provider_id, selected_candidate.key_id)
        return selected_candidate

    def get_rpm(self, *, provider_id: str, key_id: str) -> int:
        now = monotonic()
        with self._lock:
            timestamps = self._selected_at.get((provider_id, key_id))
            if timestamps is None:
                return 0
            _prune_old_timestamps(timestamps, now)
            return len(timestamps)

    def _record_selection(self, provider_id: str, key_id: str) -> None:
        now = monotonic()
        with self._lock:
            timestamps = self._selected_at.setdefault((provider_id, key_id), deque())
            timestamps.append(now)
            _prune_old_timestamps(timestamps, now)


def _select_candidate_at_position(
    candidates: tuple[ProviderRuntimeApiKey, ...],
    position: int,
) -> ProviderRuntimeApiKey:
    current_offset = 0
    for candidate in candidates:
        current_offset += candidate.poll_weight
        if position < current_offset:
            return candidate

    return candidates[-1]


def _prune_old_timestamps(timestamps: deque[float], now: float) -> None:
    cutoff = now - 60
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()


@lru_cache
def get_provider_api_key_scheduler() -> ProviderApiKeyScheduler:
    return ProviderApiKeyScheduler()

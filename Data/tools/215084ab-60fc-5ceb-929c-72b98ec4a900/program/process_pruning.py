from __future__ import annotations

from process_repository import (
    EXECUTION_ID_PATTERN,
    FINAL_STATES,
    ORPHANED_STATE,
    ProcessRepository,
    ProcessRepositoryError,
)


def prune_process_records(
    repository: ProcessRepository,
    *,
    older_than_seconds: int,
    dry_run: bool,
) -> dict[str, object]:
    if not repository.execution_root.is_dir():
        return _result(
            dry_run=dry_run,
            older_than_seconds=older_than_seconds,
            scanned=0,
            candidates=[],
            removed=[],
            skipped=[],
            failed=[],
        )

    execution_ids = sorted(
        directory.name
        for directory in repository.execution_root.iterdir()
        if directory.is_dir()
        and EXECUTION_ID_PATTERN.fullmatch(directory.name)
    )
    candidates: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []

    for execution_id in execution_ids:
        try:
            snapshot = repository.get_process(execution_id)
        except ProcessRepositoryError as exc:
            failed.append(_failure_item(execution_id, exc))
            continue

        age_seconds = snapshot.data.get("record_age_seconds")
        if snapshot.data.get("liveness_status") == "held":
            skipped.append(
                {
                    "execution_id": execution_id,
                    "state": snapshot.state,
                    "reason": "liveness_lock_held",
                }
            )
            continue
        if snapshot.state not in FINAL_STATES and snapshot.state != ORPHANED_STATE:
            skipped.append(
                {
                    "execution_id": execution_id,
                    "state": snapshot.state,
                    "reason": "active_or_unconfirmed",
                }
            )
            continue
        if not isinstance(age_seconds, (int, float)) or age_seconds < older_than_seconds:
            skipped.append(
                {
                    "execution_id": execution_id,
                    "state": snapshot.state,
                    "reason": "too_recent",
                    "record_age_seconds": age_seconds,
                }
            )
            continue

        candidate = {
            "execution_id": execution_id,
            "state": snapshot.state,
            "record_age_seconds": age_seconds,
        }
        candidates.append(candidate)
        if dry_run:
            continue
        try:
            removed_directory = repository.cleanup(execution_id)
        except ProcessRepositoryError as exc:
            failed.append(_failure_item(execution_id, exc))
            continue
        removed.append(
            {
                **candidate,
                "removed_execution_directory": str(removed_directory),
            }
        )

    return _result(
        dry_run=dry_run,
        older_than_seconds=older_than_seconds,
        scanned=len(execution_ids),
        candidates=candidates,
        removed=removed,
        skipped=skipped,
        failed=failed,
    )


def _failure_item(
    execution_id: str,
    error: ProcessRepositoryError,
) -> dict[str, object]:
    return {
        "execution_id": execution_id,
        "code": error.code,
        "message": error.message,
    }


def _result(
    *,
    dry_run: bool,
    older_than_seconds: int,
    scanned: int,
    candidates: list[dict[str, object]],
    removed: list[dict[str, object]],
    skipped: list[dict[str, object]],
    failed: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "dry_run": dry_run,
        "older_than_seconds": older_than_seconds,
        "scanned": scanned,
        "candidate_count": len(candidates),
        "removed_count": len(removed),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "candidates": candidates if dry_run else [],
        "removed": removed,
        "skipped": skipped,
        "failed": failed,
    }

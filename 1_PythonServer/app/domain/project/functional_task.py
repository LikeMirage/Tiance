from collections.abc import Mapping


def failed_in_source_run(task: Mapping, source_run_id: str | None) -> bool:
    """A failed automatic task is not retried by the same parent tool loop.

    A new parent run or an explicit manual request may try again. Successful
    tasks do not suppress later threshold crossings in a long-running task.
    """
    trigger = task.get("trigger")
    return bool(
        source_run_id
        and task.get("status") == "failed"
        and isinstance(trigger, Mapping)
        and trigger.get("source_run_id") == source_run_id
    )

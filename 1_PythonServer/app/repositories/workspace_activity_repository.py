from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.infra.database import database_connection, database_transaction

CONVERSATION_CREATED = "conversation_created"
USER_MESSAGE_SENT = "user_message_sent"
AI_RUN_ELAPSED_MS = "ai_run_elapsed_ms"


class WorkspaceActivityRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def record_conversation_created(
        self,
        *,
        session_id: str,
        created_at: str,
    ) -> None:
        self._record_activity(
            activity_type=CONVERSATION_CREATED,
            source_id=session_id,
            occurred_at=created_at,
        )

    def record_user_message_sent(
        self,
        *,
        message_id: str,
        sent_at: str,
    ) -> None:
        self._record_activity(
            activity_type=USER_MESSAGE_SENT,
            source_id=message_id,
            occurred_at=sent_at,
        )

    def record_ai_run_elapsed(
        self,
        *,
        user_message_id: str,
        elapsed_ms: int,
        finished_at: str,
    ) -> None:
        self._record_activity(
            activity_type=AI_RUN_ELAPSED_MS,
            source_id=user_message_id,
            amount=max(0, int(elapsed_ms)),
            occurred_at=finished_at,
        )

    def _record_activity(
        self,
        *,
        activity_type: str,
        source_id: str,
        occurred_at: str,
        amount: int = 1,
    ) -> None:
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO workspace_activity_records (
                    activity_type,
                    source_id,
                    amount,
                    occurred_at
                ) VALUES (?, ?, ?, ?)
                """,
                (activity_type, source_id, amount, occurred_at),
            )

    def count_conversations_created(self) -> int:
        return self._count_activity(CONVERSATION_CREATED)

    def count_user_messages_sent(self) -> int:
        return self._count_activity(USER_MESSAGE_SENT)

    def sum_ai_run_elapsed_ms(self) -> int:
        with database_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM workspace_activity_records
                WHERE activity_type = ?
                """,
                (AI_RUN_ELAPSED_MS,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def _count_activity(self, activity_type: str) -> int:
        with database_connection(self._database_path) as connection:
            baseline = connection.execute(
                """
                SELECT baseline_count, starts_at
                FROM workspace_activity_baselines
                WHERE activity_type = ?
                """,
                (activity_type,),
            ).fetchone()
            if baseline is None:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM workspace_activity_records
                    WHERE activity_type = ?
                    """,
                    (activity_type,),
                ).fetchone()
                return int(row["total"] if row is not None else 0)
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM workspace_activity_records
                WHERE activity_type = ? AND occurred_at > ?
                """,
                (activity_type, str(baseline["starts_at"])),
            ).fetchone()
        return int(baseline["baseline_count"]) + int(row["total"] if row is not None else 0)

    def set_conversation_baseline(self, count: int) -> int:
        now = datetime.now(UTC).isoformat()
        safe_count = max(0, int(count))
        with database_transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO workspace_activity_baselines (
                    activity_type,
                    baseline_count,
                    starts_at,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(activity_type) DO UPDATE SET
                    baseline_count = excluded.baseline_count,
                    starts_at = excluded.starts_at,
                    updated_at = excluded.updated_at
                """,
                (CONVERSATION_CREATED, safe_count, now, now),
            )
        return safe_count


@lru_cache
def get_workspace_activity_repository() -> WorkspaceActivityRepository:
    return WorkspaceActivityRepository(get_settings().app_database_file)

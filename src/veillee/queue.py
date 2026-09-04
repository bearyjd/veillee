"""The transcription queue.

Design constraints, all of which are tested:

* Idempotent. Enqueueing the same recording twice leaves one job. A recording
  that already has a transcript on disk is never re-queued.
* Survives restart. A job left in 'running' because the worker was killed is
  returned to 'pending' at startup rather than being lost.
* Backs off. Failures retry on an exponential schedule and dead-letter after a
  fixed number of attempts instead of spinning forever.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from .models import QueueJob
from .storage.paths import utc_now_iso

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_DEAD = "dead"

BACKOFF_BASE_SECONDS = 15
BACKOFF_CAP_SECONDS = 3600


def backoff_delay(attempts: int) -> int:
    """Seconds to wait before retry number `attempts`."""
    return min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), BACKOFF_CAP_SECONDS)


def enqueue(connection: sqlite3.Connection, recording_id: str) -> bool:
    """Add a recording to the queue. Returns True if a new job was created."""
    now = utc_now_iso()
    cursor = connection.execute(
        "INSERT INTO transcription_queue "
        "(recording_id, state, attempts, next_attempt_at, created, updated) "
        "VALUES (?, ?, 0, ?, ?, ?) "
        "ON CONFLICT(recording_id) DO NOTHING",
        (recording_id, STATE_PENDING, now, now, now),
    )
    return cursor.rowcount > 0


def requeue(connection: sqlite3.Connection, recording_id: str) -> None:
    """Force a recording back to pending, clearing any dead-letter state."""
    now = utc_now_iso()
    connection.execute(
        "INSERT INTO transcription_queue "
        "(recording_id, state, attempts, next_attempt_at, created, updated) "
        "VALUES (?, ?, 0, ?, ?, ?) "
        "ON CONFLICT(recording_id) DO UPDATE SET "
        "state=excluded.state, attempts=0, next_attempt_at=excluded.next_attempt_at, "
        "last_error=NULL, updated=excluded.updated",
        (recording_id, STATE_PENDING, now, now, now),
    )


def recover_stale(connection: sqlite3.Connection) -> int:
    """Return jobs orphaned by a killed worker to the pending state."""
    now = utc_now_iso()
    cursor = connection.execute(
        "UPDATE transcription_queue SET state = ?, updated = ? WHERE state = ?",
        (STATE_PENDING, now, STATE_RUNNING),
    )
    return cursor.rowcount


def claim_next(connection: sqlite3.Connection) -> QueueJob | None:
    """Atomically take the next due job, or None if there is nothing to do."""
    now = utc_now_iso()
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT * FROM transcription_queue "
            "WHERE state = ? AND next_attempt_at <= ? "
            "ORDER BY next_attempt_at, id LIMIT 1",
            (STATE_PENDING, now),
        ).fetchone()
        if row is None:
            connection.execute("COMMIT")
            return None
        connection.execute(
            "UPDATE transcription_queue SET state = ?, updated = ? WHERE id = ?",
            (STATE_RUNNING, now, row["id"]),
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    return QueueJob(
        id=int(row["id"]),
        recording_id=str(row["recording_id"]),
        state=STATE_RUNNING,
        attempts=int(row["attempts"]),
        next_attempt_at=str(row["next_attempt_at"]),
        last_error=row["last_error"],
    )


def complete(connection: sqlite3.Connection, job_id: int) -> None:
    """Mark a job finished."""
    connection.execute(
        "UPDATE transcription_queue SET state = ?, last_error = NULL, updated = ? WHERE id = ?",
        (STATE_DONE, utc_now_iso(), job_id),
    )


def fail(connection: sqlite3.Connection, job: QueueJob, error: str, max_attempts: int) -> str:
    """Record a failure, scheduling a retry or dead-lettering. Returns the new state."""
    attempts = job.attempts + 1
    dead = attempts >= max_attempts
    state = STATE_DEAD if dead else STATE_PENDING
    next_attempt = datetime.now(UTC) + timedelta(seconds=backoff_delay(attempts))
    connection.execute(
        "UPDATE transcription_queue SET state = ?, attempts = ?, next_attempt_at = ?, "
        "last_error = ?, updated = ? WHERE id = ?",
        (
            state,
            attempts,
            next_attempt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error[:1000],
            utc_now_iso(),
            job.id,
        ),
    )
    return state


def depth(connection: sqlite3.Connection) -> dict[str, int]:
    """Count of jobs by state, for /healthz."""
    rows = connection.execute(
        "SELECT state, COUNT(*) AS n FROM transcription_queue GROUP BY state"
    ).fetchall()
    counts = {state: 0 for state in (STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_DEAD)}
    for row in rows:
        counts[str(row["state"])] = int(row["n"])
    return counts

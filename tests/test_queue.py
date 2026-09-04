"""The transcription queue: idempotent, restart-safe, and it gives up eventually."""

from __future__ import annotations

from veillee import queue as q
from veillee.config import Settings
from veillee.db import closing_connection


class TestIdempotency:
    def test_enqueueing_twice_creates_one_job(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            assert q.enqueue(connection, "rec-1") is True
            assert q.enqueue(connection, "rec-1") is False
            assert q.depth(connection)["pending"] == 1

    def test_a_claimed_job_is_not_handed_out_twice(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-1")
            first = q.claim_next(connection)
            second = q.claim_next(connection)
        assert first is not None
        assert second is None

    def test_completing_a_job_removes_it_from_pending(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-1")
            job = q.claim_next(connection)
            assert job is not None
            q.complete(connection, job.id)
            depth = q.depth(connection)
        assert depth["done"] == 1
        assert depth["pending"] == 0


class TestRestartRecovery:
    def test_a_job_orphaned_by_a_killed_worker_comes_back(self, settings: Settings) -> None:
        """This is what happens when the worker container is killed mid-job."""
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-1")
            claimed = q.claim_next(connection)
            assert claimed is not None
            assert q.depth(connection)["running"] == 1

        # The worker dies here. A new one starts and reconciles.
        with closing_connection(settings.db_path) as connection:
            recovered = q.recover_stale(connection)
            assert recovered == 1
            assert q.depth(connection)["pending"] == 1
            assert q.claim_next(connection) is not None

    def test_recovery_is_safe_when_nothing_was_orphaned(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            assert q.recover_stale(connection) == 0


class TestBackoffAndDeadLettering:
    def test_failures_back_off_exponentially_and_are_capped(self) -> None:
        delays = [q.backoff_delay(n) for n in range(1, 10)]
        assert delays[0] == q.BACKOFF_BASE_SECONDS
        assert delays == sorted(delays)
        assert max(delays) <= q.BACKOFF_CAP_SECONDS

    def test_a_job_dead_letters_after_the_configured_attempts(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-doomed")
            state = ""
            for _ in range(settings.max_attempts):
                job = q.claim_next(connection)
                if job is None:
                    # Backoff has pushed it into the future; force it due again.
                    connection.execute(
                        "UPDATE transcription_queue SET next_attempt_at = '2000-01-01T00:00:00Z'"
                    )
                    job = q.claim_next(connection)
                assert job is not None
                state = q.fail(connection, job, "ffmpeg said no", settings.max_attempts)
            assert state == q.STATE_DEAD
            assert q.depth(connection)["dead"] == 1

    def test_a_failed_job_records_why(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-1")
            job = q.claim_next(connection)
            assert job is not None
            q.fail(connection, job, "the model would not load", settings.max_attempts)
            row = connection.execute(
                "SELECT last_error, attempts FROM transcription_queue WHERE recording_id = 'rec-1'"
            ).fetchone()
        assert "would not load" in row["last_error"]
        assert row["attempts"] == 1

    def test_requeue_revives_a_dead_job(self, settings: Settings) -> None:
        with closing_connection(settings.db_path) as connection:
            q.enqueue(connection, "rec-1")
            job = q.claim_next(connection)
            assert job is not None
            q.fail(connection, job, "boom", max_attempts=1)
            assert q.depth(connection)["dead"] == 1

            q.requeue(connection, "rec-1")

            assert q.depth(connection)["pending"] == 1
            revived = q.claim_next(connection)
            assert revived is not None
            assert revived.attempts == 0


def test_a_job_not_yet_due_is_not_claimed(settings: Settings) -> None:
    with closing_connection(settings.db_path) as connection:
        q.enqueue(connection, "rec-1")
        connection.execute(
            "UPDATE transcription_queue SET next_attempt_at = '2999-01-01T00:00:00Z'"
        )
        assert q.claim_next(connection) is None

"""The transcription worker.

Runs in its own container. Drains the queue, one job at a time, forever. Every
failure is recorded against the job rather than crashing the loop: a worker that
dies on a bad file stops transcribing everything else too.
"""

from __future__ import annotations

import logging
import signal
import sqlite3
import time
from pathlib import Path
from types import FrameType

from . import queue as queue_module
from .config import Settings, load_settings
from .db import closing_connection, initialise
from .models import Recording
from .repository import get_recording
from .storage import audio as audio_storage
from .storage.gitrepo import autocommit
from .transcribe import TranscriptionError, transcribe, write_transcript

logger = logging.getLogger(__name__)


class Worker:
    """Drains the queue until asked to stop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.running = True

    def request_stop(self, signum: int, frame: FrameType | None) -> None:
        logger.info("worker stopping after the current job (signal %s)", signum)
        self.running = False

    def run_once(self, connection: sqlite3.Connection) -> bool:
        """Handle at most one job. Returns True if work was done."""
        job = queue_module.claim_next(connection)
        if job is None:
            return False

        recording = get_recording(connection, job.recording_id)
        if recording is None:
            queue_module.fail(
                connection, job, "recording is not in the index", self.settings.max_attempts
            )
            return True

        try:
            self._transcribe_job(connection, job.recording_id, recording)
            queue_module.complete(connection, job.id)
            logger.info("transcribed %s", job.recording_id)
        except (TranscriptionError, OSError) as exc:
            state = queue_module.fail(connection, job, str(exc), self.settings.max_attempts)
            logger.error(
                "transcription of %s failed (attempt %d, now %s): %s",
                job.recording_id, job.attempts + 1, state, exc,
            )
        return True

    def _transcribe_job(
        self, connection: sqlite3.Connection, recording_id: str, recording: Recording
    ) -> None:
        flac = Path(recording.flac_path)
        paths = audio_storage.transcript_paths(self.settings, recording_id)
        paths["markdown"].parent.mkdir(parents=True, exist_ok=True)

        transcription = transcribe(self.settings, flac)
        write_transcript(
            self.settings,
            transcription,
            recording_id=recording_id,
            question_id=recording.question_id,
            created=recording.created,
            markdown_path=paths["markdown"],
            json_path=paths["json"],
        )
        connection.execute(
            "UPDATE recordings SET transcript_path = ? WHERE recording_id = ?",
            (str(paths["markdown"]), recording_id),
        )
        autocommit(
            self.settings.data_dir,
            f"transcript: {recording_id} added",
            enabled=self.settings.git_autocommit,
        )

    def run(self) -> None:
        """The loop. Idles politely when there is nothing to do."""
        initialise(self.settings.db_path)
        with closing_connection(self.settings.db_path) as connection:
            recovered = queue_module.recover_stale(connection)
            if recovered:
                logger.info("returned %d interrupted job(s) to the queue", recovered)

            while self.running:
                try:
                    did_work = self.run_once(connection)
                except sqlite3.Error as exc:
                    logger.error("queue error, backing off: %s", exc)
                    did_work = False
                if not did_work:
                    time.sleep(self.settings.worker_poll_seconds)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    settings = load_settings()
    settings.ensure_dirs()
    worker = Worker(settings)
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    logger.info(
        "worker starting: backend=%s model=%s",
        settings.transcription_backend, settings.whisper_model,
    )
    worker.run()
    return 0

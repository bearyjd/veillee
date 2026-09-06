"""The SQLite index.

This database is a convenience, never the source of truth. It can be deleted at
any moment and rebuilt with `veillee reindex` from `data/` alone. Nothing is
stored here that does not also exist in a file on disk, with one deliberate
exception: the transcription queue, whose state is itself derivable (a recording
without a transcript file needs one).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    question_id    TEXT PRIMARY KEY,
    question_text  TEXT NOT NULL,
    chapter_slug   TEXT NOT NULL,
    chapter_order  INTEGER NOT NULL,
    body           TEXT NOT NULL,
    status         TEXT NOT NULL,
    created        TEXT NOT NULL,
    updated        TEXT NOT NULL,
    word_count     INTEGER NOT NULL,
    custom         INTEGER NOT NULL DEFAULT 0,
    path           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS answers_by_chapter ON answers (chapter_order, question_id);
CREATE INDEX IF NOT EXISTS answers_by_updated ON answers (updated DESC);

CREATE TABLE IF NOT EXISTS recordings (
    recording_id        TEXT PRIMARY KEY,
    question_id         TEXT NOT NULL,
    created             TEXT NOT NULL,
    duration_seconds    REAL NOT NULL DEFAULT 0,
    device              TEXT NOT NULL DEFAULT '',
    original_path       TEXT NOT NULL,
    flac_path           TEXT NOT NULL,
    opus_path           TEXT NOT NULL,
    sidecar_path        TEXT NOT NULL,
    sha256_original     TEXT NOT NULL,
    sha256_flac         TEXT NOT NULL,
    sha256_opus         TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'upload',
    transcript_path     TEXT,
    transcript_reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS recordings_by_question ON recordings (question_id, created);

CREATE TABLE IF NOT EXISTS photographs (
    photo_id        TEXT PRIMARY KEY,
    question_id     TEXT NOT NULL,
    created         TEXT NOT NULL,
    caption         TEXT NOT NULL DEFAULT '',
    original_path   TEXT NOT NULL,
    view_path       TEXT NOT NULL,
    sidecar_path    TEXT NOT NULL,
    sha256_original TEXT NOT NULL,
    sha256_view     TEXT NOT NULL,
    width           INTEGER NOT NULL DEFAULT 0,
    height          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS photographs_by_question ON photographs (question_id, created);

CREATE TABLE IF NOT EXISTS transcription_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id    TEXT NOT NULL UNIQUE,
    state           TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error      TEXT,
    created         TEXT NOT NULL,
    updated         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS queue_by_state ON transcription_queue (state, next_attempt_at);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the index in WAL mode with sane durability settings.

    `check_same_thread=False` is required and safe here. FastAPI resolves a sync
    dependency on a worker thread but may run the handler on the event loop
    thread, so one connection legitimately crosses threads within a single
    request. It is never shared *between* requests and never used concurrently:
    each request opens its own connection and closes it on the way out.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        db_path, timeout=30.0, isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialise(db_path: Path) -> None:
    """Create the schema if it is not already there."""
    with closing_connection(db_path) as connection:
        connection.executescript(SCHEMA)


@contextmanager
def closing_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection and always close it, even on error."""
    connection = connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside a single immediate transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default

"""Runtime configuration. Everything has a working default; nothing is required."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path("data")
DEFAULT_DB_PATH = Path("veillee.db")


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot, read once at startup."""

    data_dir: Path
    db_path: Path
    questions_dir: Path
    passcode: str | None
    secret_key: str
    transcription_backend: str
    whisper_model: str
    whisper_compute_type: str
    whisper_device: str
    remote_base_url: str | None
    remote_api_key: str | None
    remote_model: str
    git_autocommit: bool
    max_upload_bytes: int
    worker_poll_seconds: float
    max_attempts: int

    @property
    def answers_dir(self) -> Path:
        return self.data_dir / "answers"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def revisions_dir(self) -> Path:
        return self.data_dir / ".revisions"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / ".trash"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / ".uploads"

    @property
    def custom_questions_path(self) -> Path:
        return self.data_dir / "custom_questions.yaml"

    def ensure_dirs(self) -> None:
        for path in (
            self.answers_dir,
            self.audio_dir,
            self.transcripts_dir,
            self.revisions_dir,
            self.trash_dir,
            self.uploads_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Build settings from the environment. Safe to call repeatedly."""
    data_dir = _env_path("VEILLEE_DATA_DIR", DEFAULT_DATA_DIR)
    passcode = os.environ.get("VEILLEE_PASSCODE") or None
    return Settings(
        data_dir=data_dir,
        db_path=_env_path("VEILLEE_DB_PATH", DEFAULT_DB_PATH),
        questions_dir=_env_path("VEILLEE_QUESTIONS_DIR", Path("questions")),
        passcode=passcode,
        secret_key=os.environ.get("VEILLEE_SECRET_KEY") or "veillee-local-tailnet-only",
        transcription_backend=os.environ.get("VEILLEE_TRANSCRIPTION_BACKEND", "local"),
        whisper_model=os.environ.get("VEILLEE_WHISPER_MODEL", "small"),
        whisper_compute_type=os.environ.get("VEILLEE_WHISPER_COMPUTE_TYPE", "int8"),
        whisper_device=os.environ.get("VEILLEE_WHISPER_DEVICE", "cpu"),
        remote_base_url=os.environ.get("VEILLEE_REMOTE_BASE_URL") or None,
        remote_api_key=os.environ.get("VEILLEE_REMOTE_API_KEY") or None,
        remote_model=os.environ.get("VEILLEE_REMOTE_MODEL", "whisper-1"),
        git_autocommit=_env_bool("VEILLEE_GIT_AUTOCOMMIT", True),
        max_upload_bytes=_env_int("VEILLEE_MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024),
        worker_poll_seconds=float(os.environ.get("VEILLEE_WORKER_POLL_SECONDS", "3.0")),
        max_attempts=_env_int("VEILLEE_MAX_ATTEMPTS", 5),
    )

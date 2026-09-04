"""Shared fixtures.

Every test gets its own data directory and its own database. Nothing here
touches the real archive.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from veillee.config import Settings, load_settings
from veillee.db import initialise
from veillee.questions import QuestionBank, load_bank

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """An isolated archive and index, with git auto-commit on so it is exercised."""
    monkeypatch.setenv("VEILLEE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VEILLEE_DB_PATH", str(tmp_path / "veillee.db"))
    monkeypatch.setenv("VEILLEE_QUESTIONS_DIR", str(REPO_ROOT / "questions"))
    monkeypatch.setenv("VEILLEE_GIT_AUTOCOMMIT", "0")
    resolved = load_settings()
    resolved.ensure_dirs()
    initialise(resolved.db_path)
    return resolved


@pytest.fixture
def bank(settings: Settings) -> QuestionBank:
    return load_bank(settings.questions_dir, settings.custom_questions_path)


@pytest.fixture
def sample_wav() -> Path:
    path = FIXTURES / "sample.wav"
    if not path.exists():
        pytest.skip("tests/fixtures/sample.wav is missing")
    return path


@pytest.fixture
def sample_m4a() -> Path:
    path = FIXTURES / "sample.m4a"
    if not path.exists():
        pytest.skip("tests/fixtures/sample.m4a is missing")
    return path


class LiveServer:
    """A real uvicorn process, driven over real HTTP."""

    def __init__(self, base_url: str, data_dir: Path, db_path: Path) -> None:
        self.base_url = base_url
        self.data_dir = data_dir
        self.db_path = db_path

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_json(self, path: str) -> dict:
        response = httpx.get(self.url(path), timeout=30)
        response.raise_for_status()
        return dict(response.json())


def _start_server(tmp_path: Path, extra_env: dict[str, str] | None = None) -> Iterator[LiveServer]:
    """Start the real application in its own process on a free port."""
    port = free_port()
    data_dir = tmp_path / "data"
    db_path = tmp_path / "veillee.db"

    environment = {
        **os.environ,
        "VEILLEE_DATA_DIR": str(data_dir),
        "VEILLEE_DB_PATH": str(db_path),
        "VEILLEE_QUESTIONS_DIR": str(REPO_ROOT / "questions"),
        "VEILLEE_GIT_AUTOCOMMIT": "0",
        **(extra_env or {}),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "veillee.cli", "serve", "--port", str(port)],
        env=environment,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            raise RuntimeError(f"server exited during startup:\n{output}")
        try:
            if httpx.get(f"{base_url}/healthz", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        process.kill()
        raise RuntimeError("server did not become healthy in 60 seconds")

    try:
        yield LiveServer(base_url, data_dir, db_path)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[LiveServer]:
    yield from _start_server(tmp_path)


@pytest.fixture
def live_server_with_passcode(tmp_path: Path) -> Iterator[LiveServer]:
    """The optional single passcode, so its page can be tested too."""
    yield from _start_server(
        tmp_path,
        {"VEILLEE_PASSCODE": "seanchai", "VEILLEE_SECRET_KEY": "test-key-not-a-secret"},
    )

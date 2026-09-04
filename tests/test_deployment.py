"""Deployment promises: the bind address, and the shell scripts.

`make verify` never used to touch scripts/, so `up.sh`, `backup.sh` and
`morning-check.sh` could rot silently between runs. These cover the parts that
can be exercised without containers; the container path itself is covered by
scripts/smoke.sh, which `make verify` runs as its final gate.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import yaml

from tests.conftest import REPO_ROOT, LiveServer, free_port
from veillee.cli import build_parser

SCRIPTS = REPO_ROOT / "scripts"


def _run(script: str, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None):
    return subprocess.run(
        [str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, **(env or {})},
        check=False,
    )


class TestItListensOnlyOnLoopback:
    def test_the_serve_command_defaults_to_127_0_0_1(self) -> None:
        args = build_parser().parse_args(["serve"])
        assert args.host == "127.0.0.1"

    def test_compose_publishes_only_to_loopback(self) -> None:
        """Binding 0.0.0.0 would put his memoirs on the LAN."""
        compose = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
        published = [
            port for service in compose["services"].values() for port in service.get("ports", [])
        ]
        assert published, "no published ports found; check the compose file"
        for port in published:
            assert str(port).startswith("127.0.0.1:"), f"{port} is not loopback-only"

    def test_the_readme_warns_against_funnel_before_anything_else(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        head = readme[:600]
        assert "funnel" in head.lower()
        assert "never" in head.lower()


class TestRuntimeDetection:
    """scripts/runtime.sh decides the uid that keeps data/ readable by a human."""

    def _source(self, snippet: str, cwd: Path) -> str:
        result = subprocess.run(
            ["bash", "-c", f"source {SCRIPTS / 'runtime.sh'}; {snippet}"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_it_reports_a_usable_run_as_value(self, tmp_path: Path) -> None:
        value = self._source("detect_run_as", tmp_path)
        assert value == "0" or ":" in value

    def test_configured_port_survives_a_missing_env_file(self, tmp_path: Path) -> None:
        """It returned non-zero once, which killed up.sh under `set -e`."""
        out = self._source('set -e; p="$(configured_port)"; echo "[${p}]"', tmp_path)
        assert out == "[]"

    def test_write_env_file_records_both_values(self, tmp_path: Path) -> None:
        self._source("write_env_file .env 1000:1000 8123", tmp_path)
        written = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "VEILLEE_RUN_AS=1000:1000" in written
        assert "VEILLEE_PORT=8123" in written

    def test_it_keeps_settings_a_person_added_by_hand(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("VEILLEE_PASSCODE=seanchai\n", encoding="utf-8")
        self._source("write_env_file .env 0 8123", tmp_path)
        written = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "VEILLEE_PASSCODE=seanchai" in written
        assert "VEILLEE_PORT=8123" in written

    def test_it_does_not_duplicate_on_a_second_write(self, tmp_path: Path) -> None:
        for port in ("8123", "8124"):
            self._source(f"write_env_file .env 0 {port}", tmp_path)
        written = (tmp_path / ".env").read_text(encoding="utf-8")
        assert written.count("VEILLEE_PORT=") == 1
        assert "VEILLEE_PORT=8124" in written

    def test_it_avoids_a_port_that_is_already_taken(self, tmp_path: Path) -> None:
        import socket

        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            busy = taken.getsockname()[1]
            chosen = self._source(f"find_free_port {busy}", tmp_path)
        assert chosen != str(busy)

    def test_it_keeps_a_port_that_is_free(self, tmp_path: Path) -> None:
        port = free_port()
        assert self._source(f"find_free_port {port}", tmp_path) == str(port)


class TestBackup:
    def test_it_writes_both_an_archive_and_an_index_copy(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        (data / "answers").mkdir(parents=True)
        (data / "answers" / "012-x.md").write_text("his words", encoding="utf-8")
        database = data / "veillee.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.commit()
        connection.close()

        result = _run(
            "backup.sh",
            env={
                "VEILLEE_DATA_DIR": str(data),
                "VEILLEE_DB_PATH": str(database),
                "VEILLEE_BACKUP_DIR": str(tmp_path / "backups"),
            },
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        backups = tmp_path / "backups"
        assert list(backups.glob("veillee-data-*.tar.gz"))
        assert list(backups.glob("veillee-db-*.sqlite"))

    def test_the_archive_actually_contains_his_words(self, tmp_path: Path) -> None:
        import tarfile

        data = tmp_path / "data"
        (data / "answers").mkdir(parents=True)
        (data / "answers" / "012-x.md").write_text("She baked on a Saturday", encoding="utf-8")

        _run(
            "backup.sh",
            env={
                "VEILLEE_DATA_DIR": str(data),
                "VEILLEE_DB_PATH": str(data / "nope.db"),
                "VEILLEE_BACKUP_DIR": str(tmp_path / "backups"),
            },
            cwd=tmp_path,
        )
        tarball = next((tmp_path / "backups").glob("veillee-data-*.tar.gz"))
        with tarfile.open(tarball) as archive:
            names = archive.getnames()
        assert any(name.endswith("012-x.md") for name in names)

    def test_it_records_the_backup_so_healthz_can_report_it(self, tmp_path: Path) -> None:
        """/healthz claims to show the last successful backup. Only this writes it."""
        data = tmp_path / "data"
        data.mkdir(parents=True)
        database = data / "veillee.db"
        sqlite3.connect(database).close()

        _run(
            "backup.sh",
            env={
                "VEILLEE_DATA_DIR": str(data),
                "VEILLEE_DB_PATH": str(database),
                "VEILLEE_BACKUP_DIR": str(tmp_path / "backups"),
            },
            cwd=tmp_path,
        )

        connection = sqlite3.connect(database)
        row = connection.execute("SELECT value FROM meta WHERE key = 'last_backup'").fetchone()
        connection.close()
        assert row is not None and row[0].endswith("Z")


class TestMorningCheck:
    def test_it_passes_against_a_running_site(self, live_server: LiveServer) -> None:
        port = live_server.base_url.rsplit(":", 1)[1]
        result = _run(
            "morning-check.sh",
            env={"VEILLEE_PORT": port, "VEILLEE_NO_AUTOSTART": "1"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout
        assert "write and read back: ok" in result.stdout

    def test_it_puts_the_probe_question_back(self, live_server: LiveServer) -> None:
        """It writes to a real question. It must not leave its own words there."""
        import httpx

        original = "What would you like said about you, in his own words."
        httpx.post(
            live_server.url("/api/answer/q120"), json={"body": original}, timeout=30
        ).raise_for_status()

        port = live_server.base_url.rsplit(":", 1)[1]
        _run("morning-check.sh", env={"VEILLEE_PORT": port, "VEILLEE_NO_AUTOSTART": "1"})

        after = httpx.get(live_server.url("/api/answer/q120"), timeout=30).json()["body"]
        assert after == original, "the morning check overwrote a real answer"

    def test_it_fails_clearly_when_nothing_is_running(self, tmp_path: Path) -> None:
        result = _run(
            "morning-check.sh",
            env={"VEILLEE_PORT": str(free_port()), "VEILLEE_NO_AUTOSTART": "1"},
        )
        assert result.returncode == 1
        assert "FAIL" in result.stdout
        assert "up.sh" in result.stdout


class TestUpScript:
    def test_it_picks_a_free_port_and_records_it_without_touching_containers(
        self, tmp_path: Path
    ) -> None:
        """Runs up.sh against a stub runtime, so no container is ever started."""
        work = tmp_path / "repo"
        work.mkdir()
        (work / "scripts").mkdir()
        for name in ("up.sh", "runtime.sh"):
            (work / "scripts" / name).write_text(
                (SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
            (work / "scripts" / name).chmod(0o755)
        (work / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

        stub_bin = tmp_path / "bin"
        stub_bin.mkdir()
        stub = stub_bin / "podman"
        stub.write_text('#!/usr/bin/env bash\necho "$@" >> "$STUB_LOG"\nexit 0\n', encoding="utf-8")
        stub.chmod(0o755)
        log = tmp_path / "stub.log"

        result = subprocess.run(
            [str(work / "scripts" / "up.sh")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(work),
            env={
                **os.environ,
                "PATH": f"{stub_bin}:{os.environ['PATH']}",
                "STUB_LOG": str(log),
            },
            check=False,
        )

        assert result.returncode == 0, result.stderr
        env_file = (work / ".env").read_text(encoding="utf-8")
        assert "VEILLEE_RUN_AS=" in env_file
        assert "VEILLEE_PORT=" in env_file
        assert "compose up -d --build" in log.read_text(encoding="utf-8")
        assert "NEVER use tailscale funnel" in result.stdout

    def test_it_reuses_a_port_already_chosen(self, tmp_path: Path) -> None:
        """A bookmarked URL must keep working across restarts."""
        work = tmp_path / "repo"
        work.mkdir()
        (work / "scripts").mkdir()
        for name in ("up.sh", "runtime.sh"):
            (work / "scripts" / name).write_text(
                (SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
            (work / "scripts" / name).chmod(0o755)
        (work / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        chosen = free_port()
        (work / ".env").write_text(f"VEILLEE_PORT={chosen}\n", encoding="utf-8")

        stub_bin = tmp_path / "bin"
        stub_bin.mkdir()
        (stub_bin / "podman").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (stub_bin / "podman").chmod(0o755)

        result = subprocess.run(
            [str(work / "scripts" / "up.sh")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(work),
            env={**os.environ, "PATH": f"{stub_bin}:{os.environ['PATH']}"},
            check=False,
        )
        assert f"VEILLEE_PORT={chosen}" in (work / ".env").read_text(encoding="utf-8")
        assert str(chosen) in result.stdout


def test_the_dockerfile_bakes_the_transcription_model_in() -> None:
    """So the first recording of the morning is not waiting on a download."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "WhisperModel" in dockerfile
    assert "HF_HOME" in dockerfile


def test_healthz_shape_is_what_the_morning_check_reads(live_server: LiveServer) -> None:
    payload = json.loads(
        subprocess.run(
            ["curl", "-s", live_server.url("/healthz")],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    )
    for key in ("status", "disk", "queue", "last_backup", "problems"):
        assert key in payload

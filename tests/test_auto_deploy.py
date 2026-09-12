"""The deploy timer must never restart the app out from under a recording.

Chunks land in .uploads/<id>/ while he is still speaking, and are assembled
only when he presses stop. Restarting between those two moments throws away
whatever has not been assembled - which is to say, the part of the story he
was in the middle of telling.

Doing nothing is always an acceptable outcome for this script. That is the
whole design, and these are the tests that keep it that way.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "auto-deploy.sh"


def run(data_dir: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "VEILLEE_DATA_DIR": str(data_dir),
            # A compose command that would fail loudly if it were ever reached.
            "VEILLEE_COMPOSE": "false",
            **env,
        },
        cwd=SCRIPT.parent.parent,
        timeout=60,
    )


class TestItRefusesWhileHeIsTalking:
    def test_a_fresh_chunk_stops_the_deploy(self, tmp_path: Path) -> None:
        uploads = tmp_path / ".uploads" / "20260911-2030-c001"
        uploads.mkdir(parents=True)
        (uploads / "00007.part").write_bytes(b"mid-sentence")

        result = run(tmp_path)

        assert result.returncode == 0, result.stderr
        assert "in flight" in result.stdout, result.stdout

    def test_it_says_so_rather_than_failing_silently(self, tmp_path: Path) -> None:
        """A timer nobody reads still has to leave a trace of why it did nothing."""
        uploads = tmp_path / ".uploads" / "session"
        uploads.mkdir(parents=True)
        (uploads / "00001.part").write_bytes(b"x")

        assert "leaving it alone" in run(tmp_path).stdout


class TestItProceedsWhenNobodyIsRecording:
    def test_an_empty_uploads_directory_is_not_a_recording(self, tmp_path: Path) -> None:
        (tmp_path / ".uploads").mkdir()
        result = run(tmp_path)
        # It got past the guard, so it tried to talk to docker - which is
        # `false` here. Reaching that point is the assertion.
        assert "in flight" not in result.stdout

    def test_a_stale_chunk_does_not_block_forever(self, tmp_path: Path) -> None:
        """An abandoned session must not wedge deployment permanently."""
        uploads = tmp_path / ".uploads" / "abandoned"
        uploads.mkdir(parents=True)
        (uploads / "00001.part").write_bytes(b"old")

        # Nothing touched in the last 0 minutes: the window is exclusive.
        result = run(tmp_path, VEILLEE_QUIET_MINUTES="0")
        assert "in flight" not in result.stdout

    def test_no_uploads_directory_at_all_is_fine(self, tmp_path: Path) -> None:
        assert "in flight" not in run(tmp_path).stdout


class TestFailureIsAlwaysSafe:
    def test_a_failed_pull_leaves_the_running_version_alone(self, tmp_path: Path) -> None:
        """A registry outage must not take the site down."""
        (tmp_path / ".uploads").mkdir()
        result = run(tmp_path)
        assert result.returncode == 0, "a failed pull should not be an error exit"
        assert "leaving the running version alone" in result.stdout

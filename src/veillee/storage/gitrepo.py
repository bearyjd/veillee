"""`data/` is its own git repository, auto-committed on save, never auto-pushed.

Git problems must not take the site down mid-sentence, so nothing here raises
into a request. But a swallowed failure would mean silently losing history, so
every failure is logged and the most recent one is exposed on /healthz.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

COMMIT_NAME = "Veillee"
COMMIT_EMAIL = "veillee@localhost"
_TIMEOUT_SECONDS = 30

GITIGNORE = """\
# The index is rebuildable from these files; do not version it.
*.db
*.db-wal
*.db-shm

# Partially received uploads. Real files land elsewhere once assembled.
.uploads/
"""


@dataclass(frozen=True)
class GitStatus:
    """Outcome of the most recent git interaction."""

    enabled: bool
    ok: bool
    detail: str


_last_status = GitStatus(enabled=False, ok=True, detail="no commit attempted yet")


def last_status() -> GitStatus:
    """The most recent git outcome, for /healthz to report."""
    return _last_status


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def ensure_repo(data_dir: Path) -> bool:
    """Make sure data/ is a git repo with an identity. Returns True if usable."""
    global _last_status
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not (data_dir / ".git").exists():
            created = _run(["init", "-q", "-b", "main"], data_dir)
            if created.returncode != 0:
                _last_status = GitStatus(True, False, f"git init failed: {created.stderr.strip()}")
                logger.error("could not initialise git repo in %s: %s", data_dir, created.stderr)
                return False
        # Identity is set on the repo itself so a container without global
        # config can still commit.
        _run(["config", "user.name", COMMIT_NAME], data_dir)
        _run(["config", "user.email", COMMIT_EMAIL], data_dir)
        gitignore = data_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE, encoding="utf-8")
        _last_status = GitStatus(True, True, "repository ready")
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        _last_status = GitStatus(True, False, f"git unavailable: {exc}")
        logger.error("git is not usable in %s: %s", data_dir, exc)
        return False


def commit_all(data_dir: Path, message: str) -> bool:
    """Stage everything under data/ and commit. Never raises; never pushes."""
    global _last_status
    try:
        staged = _run(["add", "-A", "."], data_dir)
        if staged.returncode != 0:
            _last_status = GitStatus(True, False, f"git add failed: {staged.stderr.strip()}")
            logger.error("git add failed in %s: %s", data_dir, staged.stderr)
            return False

        committed = _run(["commit", "-q", "-m", message], data_dir)
        if committed.returncode != 0:
            combined = f"{committed.stdout}{committed.stderr}"
            if "nothing to commit" in combined or "nothing added" in combined:
                _last_status = GitStatus(True, True, "nothing to commit")
                return True
            _last_status = GitStatus(True, False, f"git commit failed: {combined.strip()[:200]}")
            logger.error("git commit failed in %s: %s", data_dir, combined)
            return False

        _last_status = GitStatus(True, True, f"committed: {message}")
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        _last_status = GitStatus(True, False, f"git error: {exc}")
        logger.error("git commit raised in %s: %s", data_dir, exc)
        return False


def autocommit(data_dir: Path, message: str, *, enabled: bool) -> bool:
    """Entry point used by request handlers."""
    global _last_status
    if not enabled:
        _last_status = GitStatus(False, True, "auto-commit disabled")
        return False
    if not ensure_repo(data_dir):
        return False
    return commit_all(data_dir, message)

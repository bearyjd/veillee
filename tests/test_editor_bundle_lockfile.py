"""The committed editor bundle must be reproducible from a committed lockfile."""

from __future__ import annotations

import json
import subprocess

from tests.conftest import REPO_ROOT

EDITOR_DIR = REPO_ROOT / "build" / "editor"
LOCKFILE = EDITOR_DIR / "package-lock.json"


def test_editor_lockfile_is_committed_and_matches_package_json() -> None:
    assert LOCKFILE.is_file(), "build/editor/package-lock.json must exist"
    package = json.loads((EDITOR_DIR / "package.json").read_text())
    root = json.loads(LOCKFILE.read_text())["packages"][""]
    assert root["dependencies"] == package["dependencies"]
    assert root["devDependencies"] == package["devDependencies"]


def test_editor_lockfile_is_not_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(LOCKFILE)],
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1, "package-lock.json is gitignored"

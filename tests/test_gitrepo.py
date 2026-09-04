"""`data/` is its own git repository, auto-committed on save, never pushed.

This backs a "nothing is ever lost" promise, so it needs a test that actually
runs git. Note the fixture: the rest of the suite disables auto-commit for
speed, which means a test using the ordinary `settings` fixture would assert
nothing at all here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from veillee.config import Settings
from veillee.questions import QuestionBank, load_bank
from veillee.storage import gitrepo
from veillee.storage.answers import write_answer

REPO_SOURCE = Path(__file__).resolve().parent.parent / "src" / "veillee"


def _git(data_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=data_dir, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def _log(data_dir: Path) -> list[str]:
    output = _git(data_dir, "log", "--format=%s")
    return output.splitlines() if output else []


class TestTheArchiveIsAGitRepository:
    def test_ensure_repo_creates_one_with_an_identity(self, git_settings: Settings) -> None:
        assert gitrepo.ensure_repo(git_settings.data_dir) is True
        assert (git_settings.data_dir / ".git").exists()
        # A container has no global git config; the repo must carry its own.
        assert _git(git_settings.data_dir, "config", "user.name") == gitrepo.COMMIT_NAME
        assert _git(git_settings.data_dir, "config", "user.email") == gitrepo.COMMIT_EMAIL

    def test_ensure_repo_is_idempotent(self, git_settings: Settings) -> None:
        assert gitrepo.ensure_repo(git_settings.data_dir) is True
        assert gitrepo.ensure_repo(git_settings.data_dir) is True

    def test_it_ignores_the_rebuildable_index(self, git_settings: Settings) -> None:
        gitrepo.ensure_repo(git_settings.data_dir)
        ignored = (git_settings.data_dir / ".gitignore").read_text(encoding="utf-8")
        assert "*.db" in ignored
        assert ".uploads/" in ignored


class TestAutoCommitOnSave:
    def test_saving_an_answer_produces_a_commit(
        self, git_settings: Settings, bank: QuestionBank
    ) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        write_answer(git_settings, question, "Bread and turf smoke.")

        assert (
            gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True) is True
        )
        assert _log(git_settings.data_dir) == ["answer: q012 updated"]

    def test_the_committed_file_contains_his_words(self, git_settings: Settings) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        write_answer(git_settings, question, "She baked on a Saturday night.")
        gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True)

        committed = _git(git_settings.data_dir, "show", "--name-only", "--format=")
        answer_files = [line for line in committed.splitlines() if line.endswith(".md")]
        assert answer_files and "012-" in answer_files[0]
        blob = _git(git_settings.data_dir, "show", f"HEAD:{answer_files[0]}")
        assert "Saturday night" in blob

    def test_each_save_is_its_own_commit(self, git_settings: Settings) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        for index in range(3):
            write_answer(git_settings, question, f"Version {index}.")
            gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True)

        assert len(_log(git_settings.data_dir)) == 3

    def test_a_second_commit_with_no_change_is_not_an_error(self, git_settings: Settings) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        write_answer(git_settings, question, "Only once.")
        gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True)

        assert (
            gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True) is True
        )
        assert gitrepo.last_status().ok is True
        assert len(_log(git_settings.data_dir)) == 1

    def test_disabled_means_disabled(self, git_settings: Settings) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        write_answer(git_settings, question, "Not to be committed.")

        assert gitrepo.autocommit(git_settings.data_dir, "nope", enabled=False) is False
        assert not (git_settings.data_dir / ".git").exists()

    def test_a_git_failure_is_reported_and_never_raised(self, tmp_path: Path) -> None:
        """A broken git must not take the site down mid-sentence."""
        blocked = tmp_path / "not-a-directory"
        blocked.write_text("this is a file, not a directory", encoding="utf-8")

        assert gitrepo.autocommit(blocked, "answer: q012 updated", enabled=True) is False
        status = gitrepo.last_status()
        assert status.ok is False
        assert status.detail, "a failure must say what went wrong, for /healthz"


class TestItIsNeverPushed:
    def test_no_remote_is_ever_configured(self, git_settings: Settings) -> None:
        question = load_bank(git_settings.questions_dir).by_id("q012")
        assert question is not None
        write_answer(git_settings, question, "His words stay here.")
        gitrepo.autocommit(git_settings.data_dir, "answer: q012 updated", enabled=True)

        assert _git(git_settings.data_dir, "remote") == ""

    def test_no_code_path_can_invoke_git_push(self) -> None:
        """Where his private words travel is not a decision the software makes.

        Parses each module and inspects string *literals* rather than grepping,
        so the word appearing in a comment or docstring - as it does, promising
        the opposite - cannot mask a real call.
        """
        import ast

        offenders: list[str] = []
        for path in REPO_SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # "remote" is a legitimate word here (the transcription
                    # backend is named that); "push" is not, in any form.
                    if node.value == "push" or node.value.startswith("push "):
                        offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == [], f"a git push argument appears at {offenders}"


def test_auto_commit_happens_over_real_http(live_server_with_git) -> None:
    """End to end: a save through the running app leaves a commit behind."""
    import httpx

    httpx.post(
        live_server_with_git.url("/api/answer/q012"),
        json={"body": "Committed by the running application."},
        timeout=30,
    ).raise_for_status()

    messages = _log(live_server_with_git.data_dir)
    assert "answer: q012 updated" in messages
    assert _git(live_server_with_git.data_dir, "remote") == ""

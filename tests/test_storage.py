"""The archive on disk: frontmatter, atomic writes, revisions, trash."""

from __future__ import annotations

import pytest

from veillee.config import Settings
from veillee.models import STATUS_ANSWERED, STATUS_SKIPPED
from veillee.questions import QuestionBank
from veillee.storage import frontmatter
from veillee.storage.answers import (
    answer_path,
    atomic_write,
    list_revisions,
    load_answer,
    move_to_trash,
    read_answer,
    restore_revision,
    revision_history,
    serialise,
    write_answer,
)
from veillee.storage.paths import answer_relpath, count_words, slugify


class TestFrontmatter:
    def test_round_trips_exactly(self) -> None:
        metadata = {"question_id": "q001", "question_text": "Who?", "word_count": 2}
        body = "A line.\n\nAnother line."
        parsed_meta, parsed_body = frontmatter.loads(frontmatter.dumps(metadata, body))
        assert parsed_meta == metadata
        assert parsed_body == body

    def test_survives_a_body_containing_the_delimiter(self) -> None:
        body = "Before.\n\n---\n\nAfter."
        _, parsed_body = frontmatter.loads(frontmatter.dumps({"question_id": "q1"}, body))
        assert parsed_body == body

    def test_preserves_apostrophes_and_accents(self) -> None:
        text = "What did your mother's kitchen smell like? Veillée, Ó Súilleabháin."
        metadata, body = frontmatter.loads(frontmatter.dumps({"question_text": text}, text))
        assert metadata["question_text"] == text
        assert body == text

    def test_empty_body_is_allowed(self) -> None:
        metadata, body = frontmatter.loads(frontmatter.dumps({"question_id": "q1"}, ""))
        assert body == ""

    @pytest.mark.parametrize(
        "bad",
        ["no frontmatter here", "---\nquestion_id: q1\nbody with no close", "---\n- a\n- b\n---\n"],
    )
    def test_refuses_malformed_documents(self, bad: str) -> None:
        # Silently accepting a half-parsed file would mean a silently truncated answer.
        with pytest.raises(frontmatter.FrontmatterError):
            frontmatter.loads(bad)


class TestPaths:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("What did your mother's kitchen smell like?", "what-did-your-mother-s-kitchen-smell"),
            ("Veillée and Ó Súilleabháin", "veillee-and-o-suilleabhain"),
            ("!!!", "untitled"),
        ],
    )
    def test_slugify(self, text: str, expected: str) -> None:
        assert slugify(text).startswith(expected[:20])

    def test_answer_path_is_stable_and_readable(self) -> None:
        path = answer_relpath(2, "childhood-and-home", "q012", "The house you grew up in")
        assert path.parts[0] == "02-childhood-and-home"
        assert path.name.startswith("012-the-house-you-grew-up-in")

    def test_count_words(self) -> None:
        assert count_words("one two  three\nfour") == 4


class TestWritingAnswers:
    def test_writes_a_readable_file_and_reads_it_back(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        written = write_answer(settings, question, "Bread and turf smoke.")

        assert written.path.exists()
        reloaded = read_answer(written.path)
        assert reloaded.body == "Bread and turf smoke."
        assert reloaded.question_id == "q012"
        assert reloaded.word_count == 4
        assert reloaded.chapter_slug == question.chapter_slug

    def test_every_save_keeps_a_revision_of_what_was_there_before(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None

        for index in range(6):
            write_answer(settings, question, f"Version {index}.")

        revisions = list_revisions(settings, "q012")
        # Five overwrites of an existing file means five revisions; the first
        # save had nothing to preserve.
        assert len(revisions) == 5
        preserved = {read_answer(path).body for path in revisions}
        assert preserved == {f"Version {index}." for index in range(5)}

    def test_revision_history_lists_earlier_versions_newest_first(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        for index in range(4):
            write_answer(settings, question, f"Version {index} of the story.")

        history = revision_history(settings, "q012")

        assert [entry.body for entry in history] == [
            "Version 2 of the story.",
            "Version 1 of the story.",
            "Version 0 of the story.",
        ]
        assert history[0].word_count == 5
        assert history[0].saved_at.startswith("20")

    def test_restore_revision_brings_back_old_body_and_keeps_current(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        for index in range(3):
            write_answer(settings, question, f"Version {index} of the story.")
        target = revision_history(settings, "q012")[-1]
        assert target.body == "Version 0 of the story."

        restored = restore_revision(settings, question, target.stamp)

        assert restored.body == "Version 0 of the story."
        assert load_answer(settings, question).body == "Version 0 of the story."  # type: ignore[union-attr]
        bodies = {read_answer(path).body for path in list_revisions(settings, "q012")}
        assert "Version 2 of the story." in bodies

    @pytest.mark.parametrize("stamp", ["nope", "../../etc/passwd", "", "20200101-000000-000000"])
    def test_restore_revision_rejects_unknown_stamps(
        self, settings: Settings, bank: QuestionBank, stamp: str
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        write_answer(settings, question, "One.")
        write_answer(settings, question, "Two.")
        with pytest.raises(LookupError):
            restore_revision(settings, question, stamp)
        assert load_answer(settings, question).body == "Two."  # type: ignore[union-attr]

    def test_revision_history_is_empty_without_revisions(self, settings: Settings) -> None:
        assert revision_history(settings, "q999") == []

    def test_revision_history_honours_limit_and_skips_unreadable_files(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        for index in range(5):
            write_answer(settings, question, f"Version {index}.")
        (settings.revisions_dir / "q012" / "99999999-999999-999999.md").write_text(
            "not frontmatter"
        )

        history = revision_history(settings, "q012", limit=2)

        assert [entry.body for entry in history] == ["Version 3.", "Version 2."]

    def test_revision_history_skips_empty_and_consecutive_duplicate_bodies(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        for body in ("Alpha.", "Alpha.", "", "Beta.", "Beta.", "Gamma.", "Final."):
            write_answer(settings, question, body)

        history = revision_history(settings, "q012")

        assert [entry.body for entry in history] == ["Gamma.", "Beta.", "Alpha."]

    def test_revision_history_survives_null_metadata(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        for index in range(3):
            write_answer(settings, question, f"Version {index}.")
        (settings.revisions_dir / "q012" / "99999999-999999-999999.md").write_text(
            "---\nquestion_id: q012\nquestion_text: Q\nword_count: null\n"
            "chapter_order: null\n---\nBroken metadata.\n"
        )

        history = revision_history(settings, "q012")

        assert [entry.body for entry in history] == ["Version 1.", "Version 0."]

    def test_rapid_saves_do_not_collide(self, settings: Settings, bank: QuestionBank) -> None:
        """Autosave fires every five seconds; revision names must never clash."""
        question = bank.by_id("q001")
        assert question is not None
        for index in range(40):
            write_answer(settings, question, f"Rapid {index}.")
        assert len(list_revisions(settings, "q001")) == 39

    def test_created_is_preserved_across_saves(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q002")
        assert question is not None
        first = write_answer(settings, question, "One.")
        second = write_answer(settings, question, "Two.")
        assert second.created == first.created

    def test_status_can_be_recorded_without_losing_the_body(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q003")
        assert question is not None
        write_answer(settings, question, "Half an answer.")
        write_answer(settings, question, "Half an answer.", status=STATUS_SKIPPED)
        reloaded = load_answer(settings, question)
        assert reloaded is not None
        assert reloaded.status == STATUS_SKIPPED
        assert reloaded.body == "Half an answer."

    def test_rejects_an_unknown_status(self, settings: Settings, bank: QuestionBank) -> None:
        question = bank.by_id("q004")
        assert question is not None
        with pytest.raises(ValueError):
            write_answer(settings, question, "Body.", status="invented")

    def test_serialise_round_trips(self, settings: Settings, bank: QuestionBank) -> None:
        question = bank.by_id("q005")
        assert question is not None
        answer = write_answer(settings, question, "Some words.")
        assert serialise(answer) == answer.path.read_text(encoding="utf-8")


class TestAtomicWriteAndTrash:
    def test_write_is_atomic_and_leaves_no_temp_files(self, tmp_path) -> None:
        target = tmp_path / "nested" / "file.md"
        atomic_write(target, "hello")
        assert target.read_text() == "hello"
        assert list(target.parent.glob(".tmp-*")) == []

    def test_deleting_moves_to_trash_rather_than_unlinking(
        self, settings: Settings, bank: QuestionBank
    ) -> None:
        question = bank.by_id("q012")
        assert question is not None
        write_answer(settings, question, "Words that must survive deletion.")
        path = answer_path(settings, question)

        destination = move_to_trash(settings, path)

        assert destination is not None
        assert not path.exists()
        assert destination.exists()
        assert "must survive" in destination.read_text(encoding="utf-8")

    def test_trashing_a_missing_file_is_not_an_error(self, settings: Settings) -> None:
        assert move_to_trash(settings, settings.data_dir / "nope.md") is None


def test_unreadable_frontmatter_names_the_file(settings: Settings, bank: QuestionBank) -> None:
    question = bank.by_id("q012")
    assert question is not None
    write_answer(settings, question, "Fine.")
    path = answer_path(settings, question)
    path.write_text("this file has been corrupted", encoding="utf-8")
    with pytest.raises(frontmatter.FrontmatterError):
        read_answer(path)


def test_answered_status_constant_is_the_default(settings: Settings, bank: QuestionBank) -> None:
    question = bank.by_id("q006")
    assert question is not None
    assert write_answer(settings, question, "Body.").status == STATUS_ANSWERED


def test_the_committed_test_fixtures_are_present() -> None:
    """A missing fixture must fail the build, never silently skip a test."""
    from tests.conftest import FIXTURES

    for name in (
        "sample.wav",
        "sample.m4a",
        "axe.min.js",
        "sample-photo.jpg",
        "sample-photo-rotated.jpg",
    ):
        assert (FIXTURES / name).exists(), f"{name} is not committed"


def test_transcript_revisions_dir_matches_save_revision(settings: Settings) -> None:
    from veillee.storage import audio as audio_storage
    from veillee.storage.answers import save_revision

    source = settings.data_dir / "t.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")
    saved = save_revision(settings, audio_storage.transcript_revision_key("rec1"), source)
    assert saved is not None
    assert saved.parent == audio_storage.transcript_revisions_dir(settings, "rec1")

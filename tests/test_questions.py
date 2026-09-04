"""The question bank. These guard the content as much as the code."""

from __future__ import annotations

from pathlib import Path

import pytest

from veillee.config import Settings
from veillee.questions import (
    QuestionBankError,
    append_custom_question,
    load_bank,
    load_custom_questions,
)

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"


class TestTheBank:
    def test_there_are_a_hundred_and_twenty_questions(self) -> None:
        assert len(load_bank(QUESTIONS_DIR).questions) == 120

    def test_there_are_fourteen_chapters(self) -> None:
        assert len(load_bank(QUESTIONS_DIR).chapters) == 14

    def test_every_id_is_unique(self) -> None:
        ids = [question.id for question in load_bank(QUESTIONS_DIR).questions]
        assert len(set(ids)) == len(ids)

    def test_chapters_are_numbered_one_to_fourteen(self) -> None:
        orders = sorted(chapter.order for chapter in load_bank(QUESTIONS_DIR).chapters)
        assert orders == list(range(1, 15))

    def test_no_question_is_a_yes_or_no_question(self) -> None:
        """Closed questions end the conversation; that is the whole risk here."""
        openers = ("did you", "do you", "was there", "were you", "is there", "have you", "are you")
        for question in load_bank(QUESTIONS_DIR).questions:
            first_clause = question.text.lower().split(",")[0]
            assert not first_clause.startswith(openers), f"{question.id} is closed: {question.text}"

    def test_every_question_ends_with_a_question_mark_or_is_an_instruction(self) -> None:
        for question in load_bank(QUESTIONS_DIR).questions:
            text = question.text.strip()
            assert text.endswith("?") or text.lower().startswith(
                ("tell me", "walk me", "talk me", "describe", "name ")
            ), f"{question.id} reads oddly: {text}"

    def test_hints_are_a_single_sentence(self) -> None:
        for question in load_bank(QUESTIONS_DIR).questions:
            if question.hint:
                assert question.hint.count(".") <= 2, f"{question.id} hint is too long"

    def test_lookup_by_id_and_by_chapter(self) -> None:
        bank = load_bank(QUESTIONS_DIR)
        question = bank.by_id("q012")
        assert question is not None
        assert question.chapter_slug == "childhood-and-home"
        assert question in bank.in_chapter("childhood-and-home")
        assert bank.by_id("q999") is None


class TestHisOwnQuestions:
    def test_a_custom_question_is_stored_in_the_archive(self, settings: Settings) -> None:
        append_custom_question(settings.custom_questions_path, "c001", "What happened to the dog?")

        loaded = load_custom_questions(settings.custom_questions_path)

        assert len(loaded) == 1
        assert loaded[0].id == "c001"
        assert loaded[0].custom is True

    def test_custom_questions_join_the_bank(self, settings: Settings) -> None:
        append_custom_question(settings.custom_questions_path, "c001", "What about the dog?")
        bank = load_bank(QUESTIONS_DIR, settings.custom_questions_path)

        assert len(bank.questions) == 121
        assert len(bank.chapters) == 15
        assert bank.next_custom_id() == "c002"

    def test_missing_custom_file_simply_means_none(self, settings: Settings) -> None:
        assert load_custom_questions(settings.custom_questions_path) == []

    def test_ids_do_not_collide_after_several_are_added(self, settings: Settings) -> None:
        path = settings.custom_questions_path
        for _ in range(4):
            bank = load_bank(QUESTIONS_DIR, path)
            append_custom_question(path, bank.next_custom_id(), "Another thought.")
        ids = [q.id for q in load_custom_questions(path)]
        assert ids == ["c001", "c002", "c003", "c004"]


class TestMalformedBanks:
    def test_a_missing_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(QuestionBankError):
            load_bank(tmp_path / "nope")

    def test_an_empty_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(QuestionBankError):
            load_bank(tmp_path)

    def test_a_question_without_text_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "01-x.yaml").write_text(
            "chapter:\n  order: 1\n  slug: x\n  title: X\nquestions:\n  - id: q001\n",
            encoding="utf-8",
        )
        with pytest.raises(QuestionBankError):
            load_bank(tmp_path)

    def test_a_chapter_without_a_title_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "01-x.yaml").write_text(
            "chapter:\n  order: 1\n  slug: x\nquestions: []\n", encoding="utf-8"
        )
        with pytest.raises(QuestionBankError):
            load_bank(tmp_path)

    def test_duplicate_ids_across_files_are_rejected(self, tmp_path: Path) -> None:
        for name, slug in (("01-a.yaml", "a"), ("02-b.yaml", "b")):
            (tmp_path / name).write_text(
                f"chapter:\n  order: 1\n  slug: {slug}\n  title: T\n"
                "questions:\n  - id: q001\n    text: Same id?\n",
                encoding="utf-8",
            )
        with pytest.raises(QuestionBankError):
            load_bank(tmp_path)

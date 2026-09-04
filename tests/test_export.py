"""Export: a folder that opens from a USB stick in ten years."""

from __future__ import annotations

import json
import shutil

from veillee.config import Settings
from veillee.db import closing_connection
from veillee.export import export, verify_manifest
from veillee.index import reindex
from veillee.ingest import ingest_recording
from veillee.questions import QuestionBank
from veillee.storage.answers import write_answer


def _prepare(settings: Settings, bank: QuestionBank, sample_m4a) -> None:
    for question in bank.questions[:3]:
        write_answer(settings, question, f"Answer for {question.id}.\n\nAnd more of it.")
    staged = settings.data_dir / "clip.m4a"
    shutil.copy2(sample_m4a, staged)
    with closing_connection(settings.db_path) as connection:
        ingest_recording(
            settings,
            connection,
            question_id=bank.questions[0].id,
            source_path=staged,
            original_suffix=".m4a",
        )
    reindex(settings)


class TestExport:
    def test_manifest_verifies_against_what_was_written(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        assert verify_manifest(result.directory) == []

    def test_manifest_notices_tampering(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")

        (result.directory / "veillee-book.md").write_text("replaced", encoding="utf-8")

        problems = verify_manifest(result.directory)
        assert any("veillee-book.md" in problem for problem in problems)

    def test_the_three_promised_artifacts_are_there(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")

        assert (result.directory / "veillee-book.md").exists()
        assert (result.directory / "index.html").exists()
        assert (result.directory / "manifest.json").exists()

    def test_the_book_is_ordered_by_chapter(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        book = (result.directory / "veillee-book.md").read_text(encoding="utf-8")

        assert book.startswith("# Veillée")
        assert "## Ancestors and the crossing" in book
        assert bank.questions[0].text in book

    def test_the_html_site_is_self_contained(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        """It must open from a USB stick with no network at all."""
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        page = (result.directory / "index.html").read_text(encoding="utf-8")

        assert "http://" not in page.replace('lang="en"', "")
        assert "https://" not in page
        assert "<audio" in page

    def test_audio_referenced_by_the_site_is_actually_present(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        page = (result.directory / "index.html").read_text(encoding="utf-8")

        clips = list((result.directory / "audio").glob("*.opus"))
        assert clips
        for clip in clips:
            assert f"audio/{clip.name}" in page

    def test_the_archive_itself_is_copied_in(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        assert list((result.directory / "answers").rglob("*.md"))

    def test_manifest_checksums_every_file(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        result = export(settings, tmp_path / "exports")
        manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))

        on_disk = {
            str(path.relative_to(result.directory))
            for path in result.directory.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        assert {entry["path"] for entry in manifest["files"]} == on_disk
        assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])

    def test_export_does_not_modify_the_archive(
        self, settings: Settings, bank: QuestionBank, sample_m4a, tmp_path
    ) -> None:
        _prepare(settings, bank, sample_m4a)
        before = {
            path: path.stat().st_mtime for path in settings.data_dir.rglob("*") if path.is_file()
        }
        export(settings, tmp_path / "exports")
        after = {
            path: path.stat().st_mtime for path in settings.data_dir.rglob("*") if path.is_file()
        }
        assert before == after

"""Photographs.

The picture he takes is kept exactly as he took it. Everything else - the
screen copy, the caption, the index row - is derived and replaceable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from veillee.config import Settings
from veillee.db import closing_connection
from veillee.index import reindex
from veillee.ingest import IngestError, ingest_photograph
from veillee.storage import photos as photo_storage
from veillee.storage.audio import sha256_file


def _staged(settings: Settings, source: Path, name: str) -> Path:
    destination = settings.data_dir / name
    shutil.copy2(source, destination)
    return destination


class TestTakingAPhotographIn:
    def test_the_original_is_kept_byte_for_byte(
        self, settings: Settings, sample_photo: Path
    ) -> None:
        """He photographed a framed print. That file is the artefact."""
        before = sha256_file(sample_photo)
        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "in.jpg"),
                original_suffix=".jpg",
                caption="The Weller farmhouse",
            )
        assert photo.sha256_original == before
        assert sha256_file(Path(photo.original_path)) == before

    def test_a_screen_copy_is_derived(self, settings: Settings, sample_photo: Path) -> None:
        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "in.jpg"),
                original_suffix=".jpg",
            )
        view = Path(photo.view_path)
        assert view.exists()
        with Image.open(view) as image:
            assert image.format == "JPEG"
            assert max(image.size) <= photo_storage.VIEW_MAX_EDGE
        assert photo.width and photo.height

    def test_the_caption_travels_with_it(self, settings: Settings, sample_photo: Path) -> None:
        caption = "Michael and Sarah Beary at Weller, about 1905"
        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "in.jpg"),
                original_suffix=".jpg",
                caption=caption,
            )
        payload = json.loads(Path(photo.sidecar_path).read_text(encoding="utf-8"))
        assert payload["caption"] == caption
        assert photo_storage.read_sidecar(Path(photo.sidecar_path)).caption == caption

    def test_a_sideways_photograph_is_stood_upright(
        self, settings: Settings, sample_photo_rotated: Path
    ) -> None:
        """A phone photo of a framed picture is nearly always rotated.

        Without honouring the EXIF tag, his great-grandparents would be shown
        on their side by any viewer that ignores it.
        """
        with Image.open(sample_photo_rotated) as original:
            assert original.size == (1200, 800)
            assert original.getexif().get(274) == 6

        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo_rotated, "in.jpg"),
                original_suffix=".jpg",
            )

        with Image.open(photo.view_path) as view:
            assert view.height > view.width, "the view copy was not rotated upright"
            assert not view.getexif().get(274), "the orientation tag should be spent, not passed on"

    def test_checksums_verify(self, settings: Settings, sample_photo: Path) -> None:
        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "in.jpg"),
                original_suffix=".jpg",
            )
        assert photo_storage.verify_photograph(photo) == []

    def test_a_corrupted_view_copy_is_noticed(self, settings: Settings, sample_photo: Path) -> None:
        with closing_connection(settings.db_path) as connection:
            photo = ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "in.jpg"),
                original_suffix=".jpg",
            )
        Path(photo.view_path).write_bytes(b"not an image")
        assert any("checksum" in p for p in photo_storage.verify_photograph(photo))


class TestRefusals:
    def test_a_file_that_is_not_an_image_is_refused_kindly(self, settings: Settings) -> None:
        junk = settings.data_dir / "notes.jpg"
        junk.write_bytes(b"this is not a photograph" * 200)
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(IngestError) as caught:
                ingest_photograph(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=junk,
                    original_suffix=".jpg",
                )
        assert "photograph" in str(caught.value).lower()

    def test_a_refusal_leaves_no_half_made_record(self, settings: Settings) -> None:
        junk = settings.data_dir / "notes.jpg"
        junk.write_bytes(b"still not a photograph" * 200)
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(IngestError):
                ingest_photograph(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=junk,
                    original_suffix=".jpg",
                )
        assert not list(settings.photographs_dir.rglob("*.json"))
        assert not list(settings.photographs_dir.rglob("*.jpg"))

    def test_the_rejected_file_still_goes_to_the_trash(self, settings: Settings) -> None:
        """Even a file we cannot read was given to us on purpose."""
        junk = settings.data_dir / "notes.jpg"
        junk.write_bytes(b"unreadable" * 400)
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(IngestError):
                ingest_photograph(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=junk,
                    original_suffix=".jpg",
                )
        assert list(settings.trash_dir.rglob("*.jpg"))

    def test_an_empty_file_is_refused(self, settings: Settings) -> None:
        empty = settings.data_dir / "empty.jpg"
        empty.write_bytes(b"")
        with closing_connection(settings.db_path) as connection:
            with pytest.raises(IngestError):
                ingest_photograph(
                    settings,
                    connection,
                    question_id="q012",
                    source_path=empty,
                    original_suffix=".jpg",
                )


class TestTheIndexIsStillDisposable:
    def test_photographs_survive_the_database_being_deleted(
        self, settings: Settings, sample_photo: Path
    ) -> None:
        with closing_connection(settings.db_path) as connection:
            ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "a.jpg"),
                original_suffix=".jpg",
                caption="One",
            )
            ingest_photograph(
                settings,
                connection,
                question_id="q013",
                source_path=_staged(settings, sample_photo, "b.jpg"),
                original_suffix=".jpg",
                caption="Two",
            )
        reindex(settings)
        with closing_connection(settings.db_path) as connection:
            before = [
                tuple(r) for r in connection.execute("SELECT * FROM photographs ORDER BY photo_id")
            ]

        for suffix in ("", "-wal", "-shm"):
            settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)
        report = reindex(settings)

        assert report.ok
        assert report.photographs == 2
        with closing_connection(settings.db_path) as connection:
            after = [
                tuple(r) for r in connection.execute("SELECT * FROM photographs ORDER BY photo_id")
            ]
        assert after == before

    def test_captions_survive_the_rebuild(self, settings: Settings, sample_photo: Path) -> None:
        """The caption is the only part a record could never reconstruct."""
        with closing_connection(settings.db_path) as connection:
            ingest_photograph(
                settings,
                connection,
                question_id="q012",
                source_path=_staged(settings, sample_photo, "a.jpg"),
                original_suffix=".jpg",
                caption="The only person who knew who was in it",
            )
        for suffix in ("", "-wal", "-shm"):
            settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)
        reindex(settings)

        with closing_connection(settings.db_path) as connection:
            caption = connection.execute("SELECT caption FROM photographs").fetchone()["caption"]
        assert caption == "The only person who knew who was in it"

"""Two promises about transcripts, both of them about dignity.

A machine transcript of an elderly man with an Irish accent will get his own
mother's name wrong. He must never be shown that. And when his son corrects one,
the machine's original wording must survive, because an edit is a judgement and
judgements should be checkable.
"""

from __future__ import annotations

import shutil

import httpx
import pytest

from tests.conftest import LiveServer
from veillee.config import Settings
from veillee.db import closing_connection
from veillee.ingest import ingest_recording
from veillee.storage import audio as audio_storage
from veillee.storage.frontmatter import loads

WRONG_WORDS = "Her name was Bridget Mulcahy of Ballyvourney"


def _recording_with_transcript(server: LiveServer, sample_m4a, text: str = WRONG_WORDS) -> str:
    with sample_m4a.open("rb") as handle:
        recording_id = httpx.post(
            server.url("/api/upload/q012"),
            files={"file": ("clip.m4a", handle, "audio/m4a")},
            timeout=120,
        ).json()["recording_id"]

    year, month = recording_id[:4], recording_id[4:6]
    path = server.data_dir / "transcripts" / year / month / f"{recording_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nrecording_id: {recording_id}\nquestion_id: q012\n"
        "created: '2026-09-04T00:00:00Z'\nbackend: local\nmodel: small\n"
        f"reviewed: false\n---\n\n[00:00:00] {text}\n",
        encoding="utf-8",
    )
    return recording_id


class TestHeIsNeverShownATranscript:
    @pytest.mark.parametrize(
        "path", ["/", "/chapters", "/chapter/childhood-and-home", "/question/q012", "/answers"]
    )
    def test_no_page_of_his_contains_the_machine_words(
        self, live_server: LiveServer, sample_m4a, path: str
    ) -> None:
        _recording_with_transcript(live_server, sample_m4a)
        page = httpx.get(live_server.url(path), timeout=30).text
        assert WRONG_WORDS not in page
        assert "Ballyvourney" not in page

    def test_the_question_page_offers_the_audio_but_not_the_words(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        page = httpx.get(live_server.url("/question/q012"), timeout=30).text
        assert f"/audio/{recording_id}.opus" in page, "he cannot play his own recording back"
        assert WRONG_WORDS not in page

    def test_there_is_no_route_that_serves_a_transcript_to_him(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        """Only /admin may show one."""
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        for path in (f"/transcript/{recording_id}", f"/transcripts/{recording_id}"):
            assert httpx.get(live_server.url(path), timeout=30).status_code == 404

    def test_the_admin_view_does_show_it_marked_unreviewed(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        recording_id = _recording_with_transcript(live_server, sample_m4a)

        listing = httpx.get(live_server.url("/admin"), timeout=30).text
        assert "not yet reviewed" in listing

        detail = httpx.get(live_server.url(f"/admin/transcript/{recording_id}"), timeout=30).text
        assert WRONG_WORDS in detail
        assert "Not yet reviewed" in detail
        assert "mistakes and all" in detail


class TestEditingPreservesTheMachineOriginal:
    def test_the_first_edit_keeps_the_machine_wording_beside_it(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        corrected = "Her name was Bridget Mulcahy of Baile Bhuirne"

        response = httpx.post(
            live_server.url(f"/admin/transcript/{recording_id}"),
            data={"body": f"[00:00:00] {corrected}", "reviewed": "yes"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 303

        year, month = recording_id[:4], recording_id[4:6]
        folder = live_server.data_dir / "transcripts" / year / month
        edited = (folder / f"{recording_id}.md").read_text(encoding="utf-8")
        machine = (folder / f"{recording_id}.machine.md").read_text(encoding="utf-8")

        assert corrected in edited
        assert WRONG_WORDS not in edited
        assert WRONG_WORDS in machine, "the machine's original wording was lost"

    def test_the_edit_is_recorded_in_the_history(self, live_server: LiveServer, sample_m4a) -> None:
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        httpx.post(
            live_server.url(f"/admin/transcript/{recording_id}"),
            data={"body": "[00:00:00] Corrected.", "reviewed": "yes"},
            timeout=30,
            follow_redirects=False,
        )
        year, month = recording_id[:4], recording_id[4:6]
        path = live_server.data_dir / "transcripts" / year / month / f"{recording_id}.md"
        metadata, _ = loads(path.read_text(encoding="utf-8"))

        kinds = [entry["kind"] for entry in metadata["history"]]
        assert "machine_original" in kinds
        assert "edit" in kinds
        assert metadata["reviewed"] is True

    def test_a_second_edit_does_not_overwrite_the_machine_original(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        """The one that matters: correcting a correction must not erase it."""
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        for body in ("[00:00:00] First correction.", "[00:00:00] Second correction."):
            httpx.post(
                live_server.url(f"/admin/transcript/{recording_id}"),
                data={"body": body, "reviewed": "yes"},
                timeout=30,
                follow_redirects=False,
            )

        year, month = recording_id[:4], recording_id[4:6]
        folder = live_server.data_dir / "transcripts" / year / month
        machine = (folder / f"{recording_id}.machine.md").read_text(encoding="utf-8")
        edited = (folder / f"{recording_id}.md").read_text(encoding="utf-8")

        assert WRONG_WORDS in machine, "the second edit overwrote the machine original"
        assert "First correction" not in machine
        assert "Second correction" in edited

    def test_every_edit_also_leaves_a_revision(self, live_server: LiveServer, sample_m4a) -> None:
        recording_id = _recording_with_transcript(live_server, sample_m4a)
        for body in ("[00:00:00] One.", "[00:00:00] Two."):
            httpx.post(
                live_server.url(f"/admin/transcript/{recording_id}"),
                data={"body": body},
                timeout=30,
                follow_redirects=False,
            )
        revisions = list(
            (live_server.data_dir / ".revisions" / f"transcript-{recording_id}").glob("*.md")
        )
        assert len(revisions) == 2


def test_a_transcript_written_by_the_worker_is_not_reviewed(settings: Settings, sample_m4a) -> None:
    from veillee.transcribe import Segment, Transcription, render_markdown

    staged = settings.data_dir / "in.m4a"
    shutil.copy2(sample_m4a, staged)
    with closing_connection(settings.db_path) as connection:
        recording = ingest_recording(
            settings,
            connection,
            question_id="q012",
            source_path=staged,
            original_suffix=".m4a",
        )
    rendered = render_markdown(
        Transcription((Segment(0.0, 1.0, "words"),), "en", "local", "small"),
        recording_id=recording.recording_id,
        question_id="q012",
        created=recording.created,
    )
    metadata, _ = loads(rendered)
    assert metadata["reviewed"] is False
    assert audio_storage.transcript_paths(settings, recording.recording_id)["markdown"]

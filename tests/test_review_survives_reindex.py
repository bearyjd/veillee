"""A review is work a person did, and the index has to be able to see it.

Marking a transcript reviewed means somebody sat with the audio and the text
and checked the machine against the man. That judgement was written into the
transcript's own frontmatter and nowhere else, while `reindex` read the flag
from the audio sidecar, where it was never written. So the index said
unreviewed for ever, `/admin` kept asking for work already done, and
rebuilding the index - the operation this whole archive is founded on -
confirmed the wrong answer rather than correcting it.

The filesystem is supposed to be authoritative. It was: the fact was on disk
the whole time, in the file that records it. Nothing read it.
"""

from __future__ import annotations

import shutil

import httpx

from tests.conftest import LiveServer
from veillee.config import Settings
from veillee.db import closing_connection
from veillee.index import reindex
from veillee.storage.frontmatter import dumps, loads


def _reviewed_in_index(settings: Settings, recording_id: str) -> int:
    with closing_connection(settings.db_path) as connection:
        row = connection.execute(
            "SELECT transcript_reviewed FROM recordings WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
    return int(row["transcript_reviewed"])


class TestReindexReadsTheReview:
    def test_a_reviewed_transcript_stays_reviewed_through_a_rebuild(
        self, settings: Settings, sample_m4a
    ) -> None:
        """Delete the index, rebuild from data/ alone, and the review survives."""
        from veillee.ingest import ingest_recording
        from veillee.storage import audio as audio_storage
        from veillee.transcribe import Segment, Transcription, write_transcript

        staged = settings.data_dir / "staged-q012.m4a"
        shutil.copy2(sample_m4a, staged)
        with closing_connection(settings.db_path) as connection:
            recording = ingest_recording(
                settings,
                connection,
                question_id="q012",
                source_path=staged,
                original_suffix=".m4a",
            )
            connection.commit()
        paths = audio_storage.transcript_paths(settings, recording.recording_id)
        write_transcript(
            settings,
            Transcription(
                segments=(Segment(0.0, 1.0, "He walked the orchard."),),
                backend="local",
                model="small",
                language="en",
            ),
            recording_id=recording.recording_id,
            question_id="q012",
            created=recording.created,
            markdown_path=paths["markdown"],
            json_path=paths["json"],
        )

        # A person reviews it: the frontmatter is what records that.
        metadata, body = loads(paths["markdown"].read_text(encoding="utf-8"))
        metadata["reviewed"] = True
        paths["markdown"].write_text(dumps(metadata, body), encoding="utf-8")

        reindex(settings)

        assert _reviewed_in_index(settings, recording.recording_id) == 1, (
            "the rebuild lost a review that was sitting on disk in front of it"
        )

    def test_an_unreviewed_transcript_is_still_unreviewed(
        self, settings: Settings, sample_m4a
    ) -> None:
        """The fix must not mark everything reviewed."""
        from veillee.ingest import ingest_recording
        from veillee.storage import audio as audio_storage
        from veillee.transcribe import Segment, Transcription, write_transcript

        staged = settings.data_dir / "staged-q013.m4a"
        shutil.copy2(sample_m4a, staged)
        with closing_connection(settings.db_path) as connection:
            recording = ingest_recording(
                settings,
                connection,
                question_id="q013",
                source_path=staged,
                original_suffix=".m4a",
            )
            connection.commit()
        paths = audio_storage.transcript_paths(settings, recording.recording_id)
        write_transcript(
            settings,
            Transcription(
                segments=(Segment(0.0, 1.0, "Not yet checked."),),
                backend="local",
                model="small",
                language="en",
            ),
            recording_id=recording.recording_id,
            question_id="q013",
            created=recording.created,
            markdown_path=paths["markdown"],
            json_path=paths["json"],
        )

        reindex(settings)

        assert _reviewed_in_index(settings, recording.recording_id) == 0


class TestTheIndexUpdatesWithoutWaitingForARebuild:
    def test_saving_a_review_shows_up_immediately(
        self, live_server: LiveServer, settings: Settings, sample_m4a
    ) -> None:
        """He should not have to run reindex to see that he reviewed something."""
        with sample_m4a.open("rb") as handle:
            recording_id = httpx.post(
                live_server.url("/api/upload/q014"),
                files={"file": ("clip.m4a", handle, "audio/m4a")},
                timeout=60,
            ).json()["recording_id"]

        from veillee.storage import audio as audio_storage
        from veillee.transcribe import Segment, Transcription, write_transcript

        server_settings = Settings(
            **{**vars(settings), "data_dir": live_server.data_dir, "db_path": live_server.db_path}
        )
        paths = audio_storage.transcript_paths(server_settings, recording_id)
        write_transcript(
            server_settings,
            Transcription(
                segments=(Segment(0.0, 1.0, "Draft."),),
                backend="local",
                model="small",
                language="en",
            ),
            recording_id=recording_id,
            question_id="q014",
            created="2026-09-06T00:00:00Z",
            markdown_path=paths["markdown"],
            json_path=paths["json"],
        )
        with closing_connection(live_server.db_path) as connection:
            connection.execute(
                "UPDATE recordings SET transcript_path = ? WHERE recording_id = ?",
                (str(paths["markdown"]), recording_id),
            )
            connection.commit()

        response = httpx.post(
            live_server.url(f"/admin/transcript/{recording_id}"),
            data={"body": "He walked the orchard.", "reviewed": "on"},
            follow_redirects=False,
            timeout=30,
        )
        assert response.status_code in (200, 303), response.text

        assert _reviewed_in_index(server_settings, recording_id) == 1, (
            "the file says reviewed and the index still says otherwise"
        )

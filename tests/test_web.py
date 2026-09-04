"""HTTP against a real uvicorn process. No TestClient, no mocks."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import REPO_ROOT, LiveServer


class TestPages:
    def test_home_page_loads_and_never_shows_a_percentage(self, live_server: LiveServer) -> None:
        page = httpx.get(live_server.url("/"), timeout=30).text
        assert "There are 120 questions" in page
        assert "%" not in page.split("<style")[0]

    def test_every_chapter_page_loads(self, live_server: LiveServer) -> None:
        from veillee.questions import load_bank

        for chapter in load_bank(REPO_ROOT / "questions").chapters:
            response = httpx.get(live_server.url(f"/chapter/{chapter.slug}"), timeout=30)
            assert response.status_code == 200, chapter.slug
            assert chapter.title in response.text

    def test_a_question_page_offers_both_audio_paths(self, live_server: LiveServer) -> None:
        page = httpx.get(live_server.url("/question/q012"), timeout=30).text
        assert "record-button" in page
        assert "Or upload a recording from your phone" in page
        assert 'type="file"' in page

    def test_unknown_question_is_a_gentle_404(self, live_server: LiveServer) -> None:
        response = httpx.get(live_server.url("/question/q999"), timeout=30)
        assert response.status_code == 404
        assert "Nothing is lost" in response.text

    def test_random_redirects_to_an_unanswered_question(self, live_server: LiveServer) -> None:
        response = httpx.get(live_server.url("/random"), timeout=30, follow_redirects=False)
        assert response.status_code == 303
        assert "/question/" in response.headers["location"]


class TestSaving:
    def test_saving_writes_a_file_and_reports_the_word_count(self, live_server: LiveServer) -> None:
        response = httpx.post(
            live_server.url("/api/answer/q012"),
            json={"body": "Bread and turf smoke, mostly."},
            timeout=30,
        )
        assert response.status_code == 200
        assert response.json()["word_count"] == 5

        files = list(live_server.data_dir.rglob("012-*.md"))
        assert len(files) == 1
        assert "turf smoke" in files[0].read_text(encoding="utf-8")

    def test_reading_back_returns_what_was_written(self, live_server: LiveServer) -> None:
        httpx.post(live_server.url("/api/answer/q012"), json={"body": "First."}, timeout=30)
        httpx.post(live_server.url("/api/answer/q012"), json={"body": "Second."}, timeout=30)

        assert live_server.get_json("/api/answer/q012")["body"] == "Second."

    def test_every_save_leaves_a_revision(self, live_server: LiveServer) -> None:
        for index in range(4):
            httpx.post(live_server.url("/api/answer/q012"), json={"body": f"v{index}"}, timeout=30)
        revisions = list((live_server.data_dir / ".revisions" / "q012").glob("*.md"))
        assert len(revisions) == 3

    def test_a_body_that_is_not_text_is_refused(self, live_server: LiveServer) -> None:
        response = httpx.post(
            live_server.url("/api/answer/q012"), json={"body": {"not": "text"}}, timeout=30
        )
        assert response.status_code == 422

    def test_saving_an_unknown_question_is_a_404(self, live_server: LiveServer) -> None:
        response = httpx.post(live_server.url("/api/answer/q999"), json={"body": "x"}, timeout=30)
        assert response.status_code == 404

    def test_skip_moves_on_without_losing_what_was_typed(self, live_server: LiveServer) -> None:
        httpx.post(live_server.url("/api/answer/q012"), json={"body": "Half written."}, timeout=30)
        response = httpx.post(
            live_server.url("/question/q012/skip"), timeout=30, follow_redirects=False
        )
        assert response.status_code == 303
        assert live_server.get_json("/api/answer/q012")["body"] == "Half written."
        assert live_server.get_json("/api/answer/q012")["status"] == "skipped"

    def test_come_back_to_this_is_offered_first_next_time(self, live_server: LiveServer) -> None:
        httpx.post(live_server.url("/question/q030/later"), timeout=30, follow_redirects=False)
        assert "You said you would come back" in httpx.get(live_server.url("/"), timeout=30).text

    def test_he_can_add_his_own_question(self, live_server: LiveServer) -> None:
        response = httpx.post(
            live_server.url("/questions/new"),
            data={"text": "What happened to the dog?"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("/question/c001")

        page = httpx.get(live_server.url("/question/c001"), timeout=30).text
        assert "What happened to the dog?" in page
        assert (live_server.data_dir / "custom_questions.yaml").exists()

    def test_an_empty_own_question_is_refused(self, live_server: LiveServer) -> None:
        response = httpx.post(live_server.url("/questions/new"), data={"text": "   "}, timeout=30)
        assert response.status_code == 422


class TestAudioOverHttp:
    def test_uploading_a_real_file_produces_all_three_derived_files(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        with sample_m4a.open("rb") as handle:
            response = httpx.post(
                live_server.url("/api/upload/q012"),
                files={"file": ("voice-memo.m4a", handle, "audio/m4a")},
                data={"device": "iPad"},
                timeout=120,
            )
        assert response.status_code == 201
        recording_id = response.json()["recording_id"]

        audio = live_server.data_dir / "audio"
        assert list(audio.rglob(f"{recording_id}.flac"))
        assert list(audio.rglob(f"{recording_id}.opus"))
        assert list(audio.rglob(f"{recording_id}.orig.m4a"))
        assert list(audio.rglob(f"{recording_id}.json"))

    def test_uploaded_audio_plays_back(self, live_server: LiveServer, sample_m4a) -> None:
        with sample_m4a.open("rb") as handle:
            created = httpx.post(
                live_server.url("/api/upload/q012"),
                files={"file": ("clip.m4a", handle, "audio/m4a")},
                timeout=120,
            ).json()

        response = httpx.get(live_server.url(created["playback_url"]), timeout=60)
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert len(response.content) > 0

    def test_a_file_that_is_not_audio_is_refused_with_advice(self, live_server: LiveServer) -> None:
        response = httpx.post(
            live_server.url("/api/upload/q012"),
            files={"file": ("notes.m4a", b"this is not audio" * 200, "audio/m4a")},
            timeout=60,
        )
        assert response.status_code == 422
        assert "m4a" in response.json()["detail"]

    def test_chunks_assemble_into_a_playable_recording(
        self, live_server: LiveServer, sample_wav
    ) -> None:
        upload_id = httpx.post(live_server.url("/api/recording/q015/start"), timeout=30).json()[
            "upload_id"
        ]

        data = sample_wav.read_bytes()
        size = len(data) // 4 + 1
        for index, start in enumerate(range(0, len(data), size)):
            httpx.post(
                live_server.url(f"/api/recording/{upload_id}/chunk?index={index}"),
                content=data[start : start + size],
                timeout=60,
            )

        finished = httpx.post(live_server.url(f"/api/recording/{upload_id}/finish"), timeout=120)
        assert finished.status_code == 201
        assert finished.json()["duration_seconds"] > 0
        playback = httpx.get(live_server.url(finished.json()["playback_url"]), timeout=60)
        assert playback.status_code == 200

    def test_a_chunk_for_an_unknown_session_is_refused(self, live_server: LiveServer) -> None:
        response = httpx.post(
            live_server.url("/api/recording/deadbeef/chunk?index=0"), content=b"x", timeout=30
        )
        assert response.status_code == 404

    def test_a_traversal_attempt_in_a_recording_id_is_rejected(
        self, live_server: LiveServer
    ) -> None:
        response = httpx.get(live_server.url("/audio/..%2F..%2Fetc%2Fpasswd.opus"), timeout=30)
        assert response.status_code in (400, 404)

    def test_deleting_needs_the_word_and_only_moves_to_trash(
        self, live_server: LiveServer, sample_m4a
    ) -> None:
        with sample_m4a.open("rb") as handle:
            recording_id = httpx.post(
                live_server.url("/api/upload/q012"),
                files={"file": ("clip.m4a", handle, "audio/m4a")},
                timeout=120,
            ).json()["recording_id"]

        refused = httpx.post(
            live_server.url(f"/api/recording/{recording_id}/delete"),
            json={"confirm": "yes"},
            timeout=30,
        )
        assert refused.status_code == 422

        accepted = httpx.post(
            live_server.url(f"/api/recording/{recording_id}/delete"),
            json={"confirm": "delete"},
            timeout=30,
        )
        assert accepted.status_code == 200
        assert not list((live_server.data_dir / "audio").rglob(f"{recording_id}.flac"))
        assert list((live_server.data_dir / ".trash").rglob(f"{recording_id}.flac"))


class TestHealth:
    def test_healthz_reports_what_the_morning_check_needs(self, live_server: LiveServer) -> None:
        payload = live_server.get_json("/healthz")
        assert payload["status"] == "ok"
        assert payload["counts"]["questions"] == 120
        assert payload["disk"]["free_bytes"] > 0
        assert "last_backup" in payload
        assert set(payload["queue"]) == {"pending", "running", "done", "dead"}
        assert payload["ffmpeg"] is True


@pytest.mark.parametrize("path", ["/", "/chapters", "/answers", "/question/q001", "/admin"])
def test_no_page_leaks_a_stack_trace(live_server: LiveServer, path: str) -> None:
    page = httpx.get(live_server.url(path), timeout=30).text
    assert "Traceback" not in page
    assert "site-packages" not in page

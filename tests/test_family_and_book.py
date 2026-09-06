"""Family read-only access, and the printable book.

The read-only rule is enforced by the middleware, so these tests go at it
through HTTP rather than by checking which buttons are hidden. A hidden button
is a courtesy; a refused request is the guarantee.
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import LiveServer

WRITER = "seanchai"
FAMILY = "cousins"


@pytest.fixture
def family_client(live_server_with_family: LiveServer):
    with httpx.Client(base_url=live_server_with_family.base_url, timeout=30) as client:
        client.post("/enter", data={"passcode": FAMILY, "next_path": "/"}, follow_redirects=False)
        yield client


@pytest.fixture
def writer_client(live_server_with_family: LiveServer):
    with httpx.Client(base_url=live_server_with_family.base_url, timeout=30) as client:
        client.post("/enter", data={"passcode": WRITER, "next_path": "/"}, follow_redirects=False)
        yield client


class TestSigningIn:
    def test_each_word_earns_its_own_role(self, live_server_with_family: LiveServer) -> None:
        for passcode in (WRITER, FAMILY):
            with httpx.Client(base_url=live_server_with_family.base_url, timeout=30) as client:
                entry = client.post(
                    "/enter",
                    data={"passcode": passcode, "next_path": "/"},
                    follow_redirects=False,
                )
                assert entry.status_code == 303
                assert client.get("/", follow_redirects=False).status_code == 200

    def test_a_wrong_word_earns_nothing(self, live_server_with_family: LiveServer) -> None:
        response = httpx.post(
            live_server_with_family.url("/enter"),
            data={"passcode": "neither", "next_path": "/"},
            timeout=30,
            follow_redirects=False,
        )
        assert response.status_code == 401


class TestFamilyMayRead:
    @pytest.mark.parametrize(
        "path",
        ["/", "/chapters", "/chapter/childhood-and-home", "/question/q012", "/answers", "/book"],
    )
    def test_every_reading_page_is_open(self, family_client, path: str) -> None:
        assert family_client.get(path).status_code == 200

    def test_they_can_hear_his_recordings(self, family_client, writer_client, sample_m4a) -> None:
        with sample_m4a.open("rb") as handle:
            created = writer_client.post(
                "/api/upload/q012",
                files={"file": ("clip.m4a", handle, "audio/m4a")},
                timeout=120,
            ).json()
        assert family_client.get(created["playback_url"]).status_code == 200

    def test_they_can_see_his_photographs(self, family_client, writer_client, sample_photo) -> None:
        with sample_photo.open("rb") as handle:
            created = writer_client.post(
                "/api/photo/q012",
                files={"file": ("photo.jpg", handle, "image/jpeg")},
                data={"caption": "Michael and Sarah"},
                timeout=120,
            ).json()
        assert family_client.get(created["view_url"]).status_code == 200
        page = family_client.get("/question/q012").text
        assert "Michael and Sarah" in page


class TestFamilyMayNotWrite:
    def test_they_cannot_save_an_answer(self, family_client) -> None:
        response = family_client.post("/api/answer/q012", json={"body": "not his words"})
        assert response.status_code == 403

    def test_nothing_reaches_the_disk_when_they_try(
        self, family_client, live_server_with_family: LiveServer
    ) -> None:
        family_client.post("/api/answer/q012", json={"body": "not his words"})
        assert not list(live_server_with_family.data_dir.rglob("012-*.md"))

    def test_they_cannot_skip_a_question_on_his_behalf(self, family_client) -> None:
        assert family_client.post("/question/q012/skip", follow_redirects=False).status_code == 403

    def test_they_cannot_add_a_question(self, family_client) -> None:
        assert family_client.post("/questions/new", data={"text": "Mine"}).status_code == 403

    def test_they_cannot_upload_a_recording(self, family_client, sample_m4a) -> None:
        with sample_m4a.open("rb") as handle:
            response = family_client.post(
                "/api/upload/q012", files={"file": ("clip.m4a", handle, "audio/m4a")}, timeout=60
            )
        assert response.status_code == 403

    def test_they_cannot_upload_a_photograph(self, family_client, sample_photo) -> None:
        with sample_photo.open("rb") as handle:
            response = family_client.post(
                "/api/photo/q012", files={"file": ("p.jpg", handle, "image/jpeg")}, timeout=60
            )
        assert response.status_code == 403

    def test_they_cannot_delete_a_recording(self, family_client, writer_client, sample_m4a) -> None:
        with sample_m4a.open("rb") as handle:
            recording_id = writer_client.post(
                "/api/upload/q012", files={"file": ("clip.m4a", handle, "audio/m4a")}, timeout=120
            ).json()["recording_id"]
        response = family_client.post(
            f"/api/recording/{recording_id}/delete", json={"confirm": "delete"}
        )
        assert response.status_code == 403


class TestFamilyMayNotSeeTranscripts:
    def test_the_admin_view_is_closed_to_them(self, family_client) -> None:
        """Machine transcripts are drafts. They are not for the family either."""
        response = family_client.get("/admin", follow_redirects=False)
        assert response.status_code == 403
        assert "reading copy" in response.text.lower()

    def test_a_transcript_page_is_closed_to_them(self, family_client) -> None:
        assert family_client.get("/admin/transcript/anything").status_code == 403

    def test_the_writer_still_sees_admin(self, writer_client) -> None:
        assert writer_client.get("/admin").status_code == 200


class TestTheBook:
    def test_it_holds_everything_he_has_written(
        self, writer_client, live_server_with_family: LiveServer
    ) -> None:
        writer_client.post("/api/answer/q012", json={"body": "Bread and turf smoke."})
        writer_client.post("/api/answer/q030", json={"body": "The forge at the crossroads."})

        book = writer_client.get("/book").text
        assert "Bread and turf smoke." in book
        assert "The forge at the crossroads." in book

    def test_unanswered_questions_are_left_out(self, writer_client) -> None:
        """A book of blanks is not a book."""
        writer_client.post("/api/answer/q012", json={"body": "Only this one."})
        book = writer_client.get("/book").text
        assert "Only this one." in book
        assert "What did you carry your lunch in" not in book

    def test_chapters_appear_in_order(self, writer_client) -> None:
        writer_client.post("/api/answer/q001", json={"body": "First chapter."})
        writer_client.post("/api/answer/q012", json={"body": "Second chapter."})
        book = writer_client.get("/book").text
        assert book.index("Ancestors and the crossing") < book.index("Childhood and home")

    def test_photographs_are_in_it_with_their_captions(self, writer_client, sample_photo) -> None:
        writer_client.post("/api/answer/q012", json={"body": "The house."})
        with sample_photo.open("rb") as handle:
            writer_client.post(
                "/api/photo/q012",
                files={"file": ("p.jpg", handle, "image/jpeg")},
                data={"caption": "Michael and Sarah at Weller"},
                timeout=120,
            )
        book = writer_client.get("/book").text
        assert "Michael and Sarah at Weller" in book
        assert "/photo/" in book

    def test_a_recording_is_noted_for_the_printed_page(self, writer_client, sample_m4a) -> None:
        """On paper an audio player is useless, so say that it exists."""
        with sample_m4a.open("rb") as handle:
            writer_client.post(
                "/api/upload/q012", files={"file": ("clip.m4a", handle, "audio/m4a")}, timeout=120
            )
        book = writer_client.get("/book").text
        assert "He answered this aloud" in book

    def test_it_carries_print_rules(self, writer_client) -> None:
        assert "book.css" in writer_client.get("/book").text
        css = writer_client.get("/static/css/book.css").text
        assert "@media print" in css
        assert "page-break-before" in css
        assert "page-break-inside: avoid" in css

    def test_the_family_may_read_the_book(self, family_client) -> None:
        assert family_client.get("/book").status_code == 200

    def test_it_is_reachable_from_every_page(self, writer_client) -> None:
        assert "/book" in writer_client.get("/").text

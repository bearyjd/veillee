"""The open-session cap counts recorder sessions only, expires stale ones, and
staging uploads never leak or get locked out."""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from veillee import ingest
from veillee.config import Settings
from veillee.web.app import create_app

QUESTION = "q012"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _fill_recorder_sessions(client: TestClient) -> None:
    for _ in range(ingest.MAX_OPEN_SESSIONS):
        assert client.post(f"/api/recording/{QUESTION}/start").status_code == 201


def test_recorder_start_is_refused_with_429_at_the_cap(client: TestClient) -> None:
    _fill_recorder_sessions(client)
    assert client.post(f"/api/recording/{QUESTION}/start").status_code == 429


def test_staging_uploads_are_not_locked_out_by_full_recorder_sessions(
    client: TestClient, sample_photo: Path, sample_wav: Path
) -> None:
    _fill_recorder_sessions(client)
    photo = client.post(
        f"/api/photo/{QUESTION}", files={"file": ("a.jpg", sample_photo.read_bytes())}
    )
    assert photo.status_code == 201
    upload = client.post(
        f"/api/upload/{QUESTION}", files={"file": ("a.wav", sample_wav.read_bytes())}
    )
    assert upload.status_code == 201


def test_staging_dirs_do_not_count_toward_the_cap(settings: Settings) -> None:
    for index in range(ingest.MAX_OPEN_SESSIONS + 5):
        ingest.start_upload(settings, f"stage{index}", {"question_id": QUESTION})
    assert ingest.count_open_uploads(settings) == 0
    ingest.start_upload(settings, "rec", {"question_id": QUESTION, "started": True})
    assert ingest.count_open_uploads(settings) == 1


def test_stale_sessions_are_swept_and_free_their_slot(
    client: TestClient, settings: Settings
) -> None:
    _fill_recorder_sessions(client)
    old = time.time() - ingest.UPLOAD_TTL_SECONDS - 60
    for entry in settings.uploads_dir.iterdir():
        os.utime(entry, (old, old))
    assert client.post(f"/api/recording/{QUESTION}/start").status_code == 201
    assert ingest.count_open_uploads(settings) == 1


def test_fresh_sessions_survive_the_sweep(settings: Settings) -> None:
    ingest.start_upload(settings, "fresh", {"question_id": QUESTION, "started": True})
    assert ingest.sweep_stale_uploads(settings) == 0
    assert ingest.upload_dir(settings, "fresh").is_dir()


def test_oversize_photo_413_leaves_no_staging_dir(settings: Settings, sample_photo: Path) -> None:
    small = dataclasses.replace(settings, max_upload_bytes=10)
    with TestClient(create_app(small)) as small_client:
        response = small_client.post(
            f"/api/photo/{QUESTION}", files={"file": ("a.jpg", sample_photo.read_bytes())}
        )
    assert response.status_code == 413
    assert list(small.uploads_dir.iterdir()) == []

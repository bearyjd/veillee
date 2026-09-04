"""Browser tests. Everything in this directory is marked `e2e` automatically."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


E2E_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark only the tests in this directory.

    `pytest_collection_modifyitems` is a global hook: a conftest in a
    subdirectory is still handed every collected item, so it must filter by
    path or it silently marks the entire suite as e2e.
    """
    for item in items:
        if E2E_DIR in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def playwright_instance() -> Iterator[object]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        yield playwright


@pytest.fixture
def browser(playwright_instance: object) -> Iterator[object]:
    """Plain Chromium, for everything that is not about recording."""
    instance = playwright_instance.chromium.launch(headless=True)  # type: ignore[attr-defined]
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def fake_audio_browser(playwright_instance: object) -> Iterator[object]:
    """Chromium with a fake microphone that plays a real wav file into the page.

    This is what makes the MediaRecorder test a real round-trip rather than a
    mock: the browser genuinely captures audio and genuinely uploads it.
    """
    sample = FIXTURES / "sample.wav"
    if not sample.exists():
        pytest.skip("tests/fixtures/sample.wav is missing")
    instance = playwright_instance.chromium.launch(  # type: ignore[attr-defined]
        headless=True,
        args=[
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={sample}",
            "--autoplay-policy=no-user-gesture-required",
        ],
    )
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def axe_source() -> str:
    path = FIXTURES / "axe.min.js"
    if not path.exists():
        pytest.skip("tests/fixtures/axe.min.js is missing")
    return path.read_text(encoding="utf-8")

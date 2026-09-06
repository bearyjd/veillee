"""axe-core on every page template. Zero critical violations, no exceptions.

He is eighty. Contrast, target size, and honest labelling are not a compliance
exercise here; they are whether he can use the thing at all.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import FIXTURES, LiveServer

PAGE_TEMPLATES = [
    ("home.html", "/"),
    ("chapters.html", "/chapters"),
    ("chapter.html", "/chapter/childhood-and-home"),
    ("question.html", "/question/q012"),
    ("answers.html", "/answers"),
    ("admin.html", "/admin"),
    ("404.html", "/no-such-page"),
    ("book.html", "/book"),
]

RUN_AXE = """
async () => {
  const results = await axe.run(document, {
    resultTypes: ['violations'],
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
  });
  return results.violations.map(v => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.slice(0, 3).map(n => n.html.slice(0, 160)),
  }));
}
"""


def _audit(page: object, axe_source: str) -> list[dict]:
    page.add_script_tag(content=axe_source)  # type: ignore[attr-defined]
    return list(page.evaluate(RUN_AXE))  # type: ignore[attr-defined]


def _describe(violations: list[dict]) -> str:
    return json.dumps(violations, indent=2)


@pytest.mark.parametrize(("template", "path"), PAGE_TEMPLATES, ids=[t for t, _ in PAGE_TEMPLATES])
def test_no_critical_or_serious_violations(
    browser: object, live_server: LiveServer, axe_source: str, template: str, path: str
) -> None:
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url(path), wait_until="load")
    page.wait_for_timeout(700)
    violations = _audit(page, axe_source)
    context.close()

    blocking = [v for v in violations if v["impact"] in ("critical", "serious")]
    assert not blocking, f"{template} has accessibility violations:\n{_describe(blocking)}"


def test_the_passcode_page_is_accessible(
    browser: object, live_server_with_passcode: LiveServer, axe_source: str
) -> None:
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server_with_passcode.url("/enter"), wait_until="load")
    violations = _audit(page, axe_source)
    context.close()

    blocking = [v for v in violations if v["impact"] in ("critical", "serious")]
    assert not blocking, f"enter.html has violations:\n{_describe(blocking)}"


def test_the_transcript_page_is_accessible(
    browser: object, live_server: LiveServer, axe_source: str, sample_m4a
) -> None:
    """Reached only after a recording exists, so it needs its own setup."""
    import httpx

    with sample_m4a.open("rb") as handle:
        recording_id = httpx.post(
            live_server.url("/api/upload/q012"),
            files={"file": ("clip.m4a", handle, "audio/m4a")},
            timeout=120,
        ).json()["recording_id"]

    transcript = live_server.data_dir / "transcripts" / "2026" / "09" / f"{recording_id}.md"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        f"---\nrecording_id: {recording_id}\nquestion_id: q012\n"
        "created: '2026-09-04T00:00:00Z'\n"
        "backend: local\nmodel: small\nreviewed: false\n---\n\n"
        "[00:00:00] A machine draft with mistakes in it.\n",
        encoding="utf-8",
    )

    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url(f"/admin/transcript/{recording_id}"), wait_until="load")
    violations = _audit(page, axe_source)
    context.close()

    blocking = [v for v in violations if v["impact"] in ("critical", "serious")]
    assert not blocking, f"admin_transcript.html has violations:\n{_describe(blocking)}"


def test_every_page_has_a_skip_link_and_a_main_landmark(
    browser: object, live_server: LiveServer
) -> None:
    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    for _, path in PAGE_TEMPLATES:
        page.goto(live_server.url(path), wait_until="load")
        assert page.locator("a.skip-link").count() == 1, path
        assert page.locator("main#main").count() == 1, path
        assert page.locator("html[lang]").count() == 1, path
    context.close()


def test_the_axe_bundle_is_vendored_not_fetched() -> None:
    """The suite must run with the host offline, like the app itself."""
    assert (FIXTURES / "axe.min.js").exists()


def test_the_book_is_accessible_with_content_in_it(
    browser: object, live_server: LiveServer, axe_source: str, sample_photo
) -> None:
    """An empty book exercises none of the markup that matters."""
    import httpx

    httpx.post(
        live_server.url("/api/answer/q012"),
        json={"body": "Bread, mostly. And the turf smoke."},
        timeout=30,
    ).raise_for_status()
    with sample_photo.open("rb") as handle:
        httpx.post(
            live_server.url("/api/photo/q012"),
            files={"file": ("p.jpg", handle, "image/jpeg")},
            data={"caption": "Michael and Sarah at Weller"},
            timeout=120,
        ).raise_for_status()

    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url("/book"), wait_until="load")
    page.wait_for_timeout(800)
    violations = _audit(page, axe_source)
    context.close()

    blocking = [v for v in violations if v["impact"] in ("critical", "serious")]
    assert not blocking, f"the book has violations:\n{_describe(blocking)}"


def test_a_photograph_carries_alternative_text(
    browser: object, live_server: LiveServer, sample_photo
) -> None:
    """A caption is also the alt text. A picture with neither is a dead end."""
    import httpx

    with sample_photo.open("rb") as handle:
        httpx.post(
            live_server.url("/api/photo/q012"),
            files={"file": ("p.jpg", handle, "image/jpeg")},
            data={"caption": "Michael and Sarah at Weller, about 1905"},
            timeout=120,
        ).raise_for_status()

    context = browser.new_context()  # type: ignore[attr-defined]
    page = context.new_page()
    page.goto(live_server.url("/question/q012"), wait_until="load")
    page.wait_for_timeout(600)
    alt = page.get_attribute(".photo img", "alt")
    context.close()

    assert alt == "Michael and Sarah at Weller, about 1905"

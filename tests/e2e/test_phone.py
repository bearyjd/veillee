"""The phone in his pocket is the machine that is actually to hand.

A story comes back to him in the car or in the garden, and the thing he has on
him is an Android phone, not the laptop on the desk upstairs. So the phone is
not a lesser way in — it is the likeliest one, and it is where a layout that
looks fine on a laptop quietly fails: a button pushed half an inch off the side
of the screen, a scrub bar too thin for a thumb, a question scrolled away before
he has read it.

Everything here runs in real Chromium mobile emulation at the sizes Android
phones genuinely report, with touch events rather than a mouse. iPhones are not
tested because he does not have one.
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import FIXTURES, LiveServer
from tests.e2e.helpers import editor_locator

# A Pixel-ish phone, used for everything that does not need the whole matrix.
PHONE = {"width": 393, "height": 851}

# Portrait sizes covering the narrow end (a small Samsung), the middle (a
# Pixel), and the wide end (a Pixel Pro) of Android in his hands.
PORTRAIT = [(360, 740), (393, 851), (412, 915)]
LANDSCAPE = (851, 393)

# The floor Android and WCAG both settle on for a fingertip.
MIN_TAP = 44
# The promise the stylesheet's own header comment makes.
TOUCH_PROMISE = 56

CONTROLS = "button, a.button, input[type=file], .record-button, summary"


def phone_context(browser: object, width: int, height: int) -> object:
    """A real mobile browser, not a laptop with a narrow window.

    `is_mobile` changes the viewport meta handling and `has_touch` changes which
    events fire, and both of those are where phone-only bugs live.
    """
    return browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": width, "height": height},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2.625,
    )


@pytest.fixture
def page(browser: object, live_server: LiveServer):
    context = phone_context(browser, PHONE["width"], PHONE["height"])
    page = context.new_page()
    yield page
    context.close()


# Every control that fails the thumb test is collected, not just the first one,
# so one run says everything that is wrong instead of one thing at a time.
MEASURE_CONTROLS = """(selector) => {
    const name = (el) => el.tagName.toLowerCase()
        + (el.id ? '#' + el.id : '')
        + (typeof el.className === 'string' && el.className.trim()
            ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
    const tooSmall = [];
    let visible = 0;
    document.querySelectorAll(selector).forEach((el) => {
        const box = el.getBoundingClientRect();
        if (box.width === 0 || box.height === 0) return;
        if (getComputedStyle(el).visibility === 'hidden') return;
        visible += 1;
        if (box.height < 44 || box.width < 44) {
            tooSmall.push({
                where: name(el),
                width: Math.round(box.width),
                height: Math.round(box.height),
            });
        }
    });
    return { visible: visible, tooSmall: tooSmall };
}"""


@pytest.mark.parametrize(("width", "height"), PORTRAIT, ids=[f"{w}x{h}" for w, h in PORTRAIT])
def test_the_page_is_workable_on_a_phone_held_upright(
    browser: object, live_server: LiveServer, width: int, height: int
) -> None:
    context = phone_context(browser, width, height)
    page = context.new_page()
    page.goto(live_server.url("/question/q040"), wait_until="load")
    page.wait_for_selector("#record-button", timeout=20_000)
    page.wait_for_timeout(900)

    assert not page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    ), "the page scrolls sideways"
    assert page.evaluate("() => parseFloat(getComputedStyle(document.body).fontSize)") >= 18, (
        "the text is below the 18px floor this whole design is built on"
    )

    measured = page.evaluate(MEASURE_CONTROLS, CONTROLS)
    # A sweep that found nothing to measure would pass while proving nothing.
    assert measured["visible"] >= 6, (
        f"only {measured['visible']} controls were measured; the sweep is not seeing the page"
    )
    assert not measured["tooSmall"], "too small for a thumb: " + ", ".join(
        f"{item['where']} is {item['width']}x{item['height']}px, needs {MIN_TAP}"
        for item in measured["tooSmall"]
    )
    context.close()


class TestTheTouchPromise:
    def test_the_main_buttons_keep_their_full_height(
        self, page: object, live_server: LiveServer
    ) -> None:
        """56px is the stylesheet's own stated promise, not a nice-to-have."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        page.wait_for_timeout(900)

        short = page.evaluate(f"""() => {{
            const out = [];
            document.querySelectorAll('.button:not(.quiet)').forEach((el) => {{
                const box = el.getBoundingClientRect();
                if (box.height === 0) return;
                if (box.height < {TOUCH_PROMISE}) {{
                    out.push(el.textContent.trim().slice(0, 24)
                        + ' (' + Math.round(box.height) + 'px)');
                }}
            }});
            return out;
        }}""")
        assert not short, "buttons shorter than the 56px promised: " + ", ".join(short)

    def test_the_formatting_buttons_are_no_smaller_than_the_rest(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Bold and Italic are pressed with the same thumb as everything else.

        They are laid out in a row of five, so they are the easiest place on the
        page to hit the wrong one.
        """
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        page.wait_for_timeout(1200)

        short = page.evaluate(f"""() => {{
            const out = [];
            document.querySelectorAll('.editor-toolbar button').forEach((el) => {{
                const box = el.getBoundingClientRect();
                if (box.height === 0) return;
                if (box.height < {TOUCH_PROMISE}) {{
                    out.push((el.getAttribute('aria-label') || '?')
                        + ' (' + Math.round(box.height) + 'px)');
                }}
            }});
            return out;
        }}""")
        assert not short, "toolbar buttons shorter than the 56px promised: " + ", ".join(short)

    def test_the_quiet_remove_button_is_still_a_full_sized_target(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Quiet must mean quiet-looking, never smaller.

        A photograph is put there first because "Remove this picture" only
        exists once there is something to remove.
        """
        with (FIXTURES / "sample-photo.jpg").open("rb") as handle:
            response = httpx.post(
                live_server.url("/api/photo/q040"),
                files={"file": ("sample-photo.jpg", handle, "image/jpeg")},
                data={"caption": "A photograph, so the remove button exists."},
                timeout=60,
            )
        assert response.status_code == 201, f"the photograph would not upload: {response.text}"

        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        page.wait_for_selector(".button.quiet", timeout=20_000)  # type: ignore
        page.wait_for_timeout(400)

        box = page.locator(".button.quiet").first.bounding_box()
        assert box["height"] >= TOUCH_PROMISE, (
            f"the quiet button is only {box['height']}px tall; quiet must not mean small"
        )

    def test_the_record_button_is_whole_and_on_the_screen(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Talking instead of typing is the easiest way in. It must not be clipped."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        page.wait_for_selector("#record-button", timeout=20_000)  # type: ignore

        assert page.locator("#record-button").is_visible()
        box = page.locator("#record-button").bounding_box()
        assert box["height"] >= TOUCH_PROMISE, f"the record button is only {box['height']}px tall"
        assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"] + 1, (
            f"the record button runs off the side: {box['x']} to {box['x'] + box['width']}"
        )
        assert not page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        ), "reaching the record button means scrolling sideways"

    def test_neighbouring_buttons_do_not_sit_on_top_of_each_other(
        self, page: object, live_server: LiveServer
    ) -> None:
        """Overlapping buttons mean he presses Skip when he meant Next."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        page.wait_for_timeout(900)

        overlaps = page.evaluate("""() => {
            const label = (el) => el.textContent.trim().slice(0, 20);
            const clashes = [];
            document.querySelectorAll('.button-row').forEach((row) => {
                const kids = Array.from(row.querySelectorAll('.button'))
                    .filter((el) => el.getBoundingClientRect().width > 0);
                for (let i = 0; i < kids.length; i++) {
                    for (let j = i + 1; j < kids.length; j++) {
                        const a = kids[i].getBoundingClientRect();
                        const b = kids[j].getBoundingClientRect();
                        if (a.left < b.right - 1 && b.left < a.right - 1
                            && a.top < b.bottom - 1 && b.top < a.bottom - 1) {
                            clashes.push(label(kids[i]) + ' / ' + label(kids[j]));
                        }
                    }
                }
            });
            return clashes;
        }""")
        assert not overlaps, "these buttons overlap on the screen: " + ", ".join(overlaps)


@pytest.mark.parametrize(("width", "height"), PORTRAIT, ids=[f"{w}x{h}" for w, h in PORTRAIT])
def test_he_has_a_real_column_to_type_in(
    browser: object, live_server: LiveServer, width: int, height: int
) -> None:
    """Milkdown's own stylesheet sets `padding: 60px 120px` on the editable
    area - a desktop editor's generous margins, hardcoded in pixels. Our rule
    asks for 1.5rem and has the same specificity, so it lost purely because the
    vendor sheet is loaded second.

    On a 393px phone that left 119px to type in: a column about four words
    wide, adrift in margin. He would have watched his own sentence wrap every
    few words. The padding has to give way on a small screen.
    """
    context = phone_context(browser, width, height)
    page = context.new_page()
    page.goto(live_server.url("/question/q040"), wait_until="load")
    editor_locator(page)
    page.wait_for_timeout(900)

    usable = page.evaluate("""() => {
        const ed = document.querySelector('.ProseMirror')
            || document.querySelector('#editor-fallback');
        if (!ed) return null;
        const cs = getComputedStyle(ed);
        return ed.getBoundingClientRect().width
            - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    }""")
    assert usable is not None, "no editor on the page at all"
    share = usable / width
    assert share >= 0.70, (
        f"only {usable:.0f}px of {width}px is his to type in ({share:.0%}) - the rest is padding"
    )
    context.close()


class TestWhatHeSeesFirst:
    def test_the_question_is_the_first_thing_on_the_screen(
        self, page: object, live_server: LiveServer
    ) -> None:
        """He must read the question before anything asks him for anything."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        editor_locator(page)
        page.wait_for_timeout(900)

        assert page.evaluate("() => window.scrollY") == 0, (
            "the page had already scrolled away from the question before he touched it"
        )
        assert page.locator("h1.question-text").is_visible(), "the question is not on the screen"


class TestWritingWithAThumb:
    def test_tapping_into_the_box_and_typing_reaches_the_disk(
        self, page: object, live_server: LiveServer
    ) -> None:
        """A tap is not a click. The whole autosave path must survive one."""
        page.goto(live_server.url("/question/q040"), wait_until="load")  # type: ignore
        editor = editor_locator(page)
        page.wait_for_timeout(900)

        editor.tap()
        page.keyboard.type("Typed with a thumb, standing up.", delay=6)
        page.evaluate("() => window.veilleeSaveNow && window.veilleeSaveNow()")
        page.wait_for_timeout(1500)

        files = list(live_server.data_dir.rglob("040-*.md"))
        assert files, "nothing he typed on the phone ever reached the disk"
        assert "with a thumb" in files[0].read_text(encoding="utf-8"), (
            "the file exists but the words he tapped in are not in it"
        )


def test_the_phone_turned_sideways_still_works(browser: object, live_server: LiveServer) -> None:
    """He puts the phone down flat on the table and it lands in landscape."""
    width, height = LANDSCAPE
    context = phone_context(browser, width, height)
    page = context.new_page()
    page.goto(live_server.url("/question/q040"), wait_until="load")
    page.wait_for_selector("#record-button", timeout=20_000)
    page.wait_for_timeout(900)

    assert not page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    ), "the page scrolls sideways when the phone is turned"

    page.locator("#record-button").scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = page.locator("#record-button").bounding_box()
    assert box["height"] >= TOUCH_PROMISE, f"the record button is only {box['height']}px tall"
    assert box["y"] >= 0 and box["y"] + box["height"] <= height + 1, (
        "the record button cannot be brought fully onto a sideways screen"
    )

    # Turning the phone must not shrink anything. A landscape phone is 851px
    # wide, so every rule hung on a narrow-screen breakpoint stops matching
    # here while his thumb stays exactly the size it was. This is the assertion
    # that catches that: it failed before the touch rules were moved onto
    # `pointer: coarse`, reporting the toolbar buttons back at 48px.
    shrunk = page.evaluate(f"""() => {{
        const out = [];
        document.querySelectorAll(
            '.button:not(.quiet), .editor-toolbar button, input[type=file]'
        ).forEach((el) => {{
            const box = el.getBoundingClientRect();
            if (box.height === 0) return;
            if (box.height < {TOUCH_PROMISE}) {{
                out.push((el.getAttribute('aria-label') || el.textContent.trim() || el.type)
                    .slice(0, 24) + ' (' + Math.round(box.height) + 'px)');
            }}
        }});
        return out;
    }}""")
    assert not shrunk, "turning the phone sideways shrank his targets below 56px: " + ", ".join(
        shrunk
    )
    context.close()

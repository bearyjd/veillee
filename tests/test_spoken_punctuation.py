"""He dictates like a man writing a letter, and says the punctuation out loud.

Whisper hears "period" and writes the word "period", so his seven-minute
recording about the orchard reads "...essential for a 40-acre homesteading
farm, period." fourteen times over. That is not a transcription error - the
machine heard him correctly - but nobody wants to read it, and the draft is
what his son corrects from.

The conversion has to be timid, because "period" is also an ordinary word: a
period of history, the postwar period, her period of mourning. Turning one of
those into a full stop would put words in his mouth, which is worse than
leaving the artifact in. So only the dictation shape is touched: a comma, the
word, then a sentence ending. The raw machine output is kept in the .json
sidecar either way, so nothing he said is ever only in the cleaned copy.
"""

from __future__ import annotations

import pytest

from veillee.transcribe import Segment, Transcription, apply_spoken_punctuation, render_markdown


class TestTheDictationShapeIsConverted:
    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            (
                "a picture dated around 1905, period. Daniel was one of",
                "a picture dated around 1905. Daniel was one of",
            ),
            (
                "which was her maiden, her married name, period. Daniel Beary,",
                "which was her maiden, her married name. Daniel Beary,",
            ),
            (
                "who later became president of the USA, period. Daniel went west",
                "who later became president of the USA. Daniel went west",
            ),
        ],
    )
    def test_comma_period_full_stop_becomes_a_full_stop(self, spoken: str, expected: str) -> None:
        assert apply_spoken_punctuation(spoken) == expected

    def test_paragraph_becomes_a_paragraph_break(self) -> None:
        got = apply_spoken_punctuation(
            "Naval War College in Newport, Rhode Island, period. Paragraph back to the orchard"
        )
        assert got == ("Naval War College in Newport, Rhode Island.\n\nback to the orchard")

    def test_the_closing_formula_he_uses(self) -> None:
        got = apply_spoken_punctuation("is now known only to God, period, end of recording.")
        assert got == "is now known only to God. End of recording."


class TestOrdinaryEnglishIsLeftAlone:
    @pytest.mark.parametrize(
        "sentence",
        [
            "they farmed there for a long period of time",
            "the postwar period was hard on the family",
            "that period of his life he never spoke about",
            "a period drama, she called it",
            "during this period the orchard was still standing",
            "he wrote a paragraph about it in the family book",
        ],
    )
    def test_the_word_survives_when_it_is_a_word(self, sentence: str) -> None:
        assert apply_spoken_punctuation(sentence) == sentence


class TestTheRawOutputIsNeverTheCleanedOne:
    def test_the_markdown_draft_is_cleaned(self) -> None:
        t = Transcription(
            segments=(Segment(0.0, 4.0, "He fought at Vicksburg, period. Then he went west."),),
            backend="local",
            model="small",
            language="en",
        )
        md = render_markdown(t, recording_id="r1", question_id="q1", created="2026-09-06T00:00:00Z")
        assert "He fought at Vicksburg. Then he went west." in md
        assert ", period." not in md

    def test_the_segments_themselves_are_untouched(self) -> None:
        """What the machine actually heard has to survive somewhere verbatim."""
        original = "He fought at Vicksburg, period. Then he went west."
        t = Transcription(
            segments=(Segment(0.0, 4.0, original),),
            backend="local",
            model="small",
            language="en",
        )
        render_markdown(t, recording_id="r1", question_id="q1", created="2026-09-06T00:00:00Z")
        assert t.segments[0].text == original, "rendering mutated the machine's own record"

"""The chart note: one line under the header rule of chart 1, saying that the ancestry
continues on the chart numbered in the last column. It is drawn on chart 1 only, and
only when chart 1 has a continuation chart number. It sits where a continuation chart's
line sits (top left, under the rule, same font, size and baseline) and is fitted to the
same width. Its text is the chart_note string (English and German); an empty string
turns it off. It overlaps no box, in normal and large print, on Letter and A4, with and
without --shadow.

Synthetic fixtures only."""

import pytest
from reportlab.pdfbase import pdfmetrics

import kincade.charts
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.pdf import Options, render_pdf

from conftest import PAPERS, TODAY, approx, render, render_chart
from pdfread import drawn, rectangles, runs

ENGLISH = "Ancestry continues on the chart numbered in the last column."
GERMAN = "Fortsetzung auf der Tafel mit der Nummer in der letzten Spalte."
# on chart 2, which continues from chart 1
CONTINUATION = "Number 1 on this chart is the same as number 8 on chart 1."
# the continuation line's baseline, measured down from the top of the page
BASELINE = 46


def note_run(pdf):
    """The note's drawn Run, English or German, or None."""
    return next((r for r in runs(pdf) if r.text in (ENGLISH, GERMAN)), None)


# ---------------------------------------------------------------- where it is drawn


def test_the_note_is_drawn_on_chart_1_when_chart_1_has_continuations(pedigree):
    # chart 1 has continuation chart numbers
    assert plan_charts(pedigree, "I1", 5)[0].continuations
    assert ENGLISH in drawn(render_chart(pedigree))
    assert drawn(render(pedigree, generations=5)).count(ENGLISH) == 1


def test_the_note_is_on_no_chart_after_the_first(pedigree):
    charts = plan_charts(pedigree, "I1")
    # chart 2 has a continuation chart of its own, and gets no note all the same
    assert charts[1].continuations
    for chart in charts[1:]:
        one = render_pdf(
            [chart],
            pedigree,
            Options(fonts="base14", compress=False, today=TODAY, index=False),
        )
        assert ENGLISH not in drawn(one), f"chart {chart.number}"
    # the whole document: chart 1 only
    assert drawn(render(pedigree)).count(ENGLISH) == 1


def test_no_note_when_chart_1_has_no_continuation_charts(pedigree):
    # precondition: the note appears where continuations do
    assert ENGLISH in drawn(render(pedigree, generations=5))
    # the parents of boxes 8-15 are generation 5
    assert plan_charts(pedigree, "I1", 4)[0].continuations == {}
    text = drawn(render(pedigree, generations=4))
    assert ENGLISH not in text and CONTINUATION not in text


def test_no_note_in_large_print_when_chart_1_has_no_continuation_charts(pedigree):
    large = {
        "large_print": True,
        "fonts": "base14",
        "compress": False,
        "today": TODAY,
        "index": False,
    }
    with_some = plan_charts(pedigree, "I1", None, "birth", True)[0]
    # precondition: chart 1 has some
    assert ENGLISH in drawn(render_pdf([with_some], pedigree, Options(**large)))
    # large print: boxes 4-7 continue at generation 4
    chart = plan_charts(pedigree, "I1", 3, "birth", True)[0]
    assert chart.continuations == {}
    assert ENGLISH not in drawn(render_pdf([chart], pedigree, Options(**large)))


@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_the_note_sits_under_the_rule_where_the_continuation_line_does(
    pedigree, paper, large_print
):
    one = render_chart(pedigree, large_print=large_print, paper=paper)
    note = note_run(one)
    assert note is not None
    # the left margin, as the continuation line
    assert note.x == approx(kincade.pdf.LEFT_MARGIN)
    # under the header rule, on the continuation line's baseline
    assert note.y == approx(BASELINE)
    assert note.size == 8


def test_the_note_has_the_continuation_lines_font_and_baseline(pedigree):
    # chart 1 has the note, chart 2 a continuation line
    drawn_runs = runs(render(pedigree))
    note = next(r for r in drawn_runs if r.text == ENGLISH)
    line = next(r for r in drawn_runs if r.text == CONTINUATION)
    assert note.y == approx(line.y)  # the same baseline
    assert note.font == line.font  # the same font (Helvetica)
    assert note.size == line.size == 8  # the same size


def test_a_long_note_is_fitted_to_the_continuation_width_with_the_ellipsis(pedigree):
    shown = next(
        t
        for t in drawn(
            render(pedigree, generations=5, lang={"chart_note": "word " * 200})
        )
        if t.startswith("word")
    )
    # the room from the left margin to 12 pt short of box 8's left edge (358 pt on
    # Letter, normal print)
    width = kincade.pdf.page_geom("letter").box_x0[8] - 12 - kincade.pdf.LEFT_MARGIN
    # fitted as every top-left line is
    assert shown == kincade.pdf.fit("word " * 200, "Helvetica", 8, width)
    assert (
        shown.endswith("…") and kincade.pdf.text_width(shown, "Helvetica", 8) <= width
    )


@pytest.mark.parametrize("shadow", [False, True], ids=["plain", "shadow"])
@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_a_very_long_note_and_continuation_line_end_12_points_short_of_the_right_column(
    pedigree, paper, large_print, shadow
):
    """Both top-left lines are fitted to the room left of the right column (x0 of its
    boxes less 12 pt), so a very long one is cut with the ellipsis there and never runs
    under the right column. Normal and large print, Letter and A4, with and without
    --shadow.
    """
    geom = kincade.pdf.page_geom(paper, large_print, shadow)
    right_x0 = geom.box_x0[geom.first_right]
    limit = right_x0 - 12
    long_words = "word " * 200
    chart_1 = render_chart(
        pedigree,
        1,
        large_print,
        paper=paper,
        shadow=shadow,
        lang={"chart_note": long_words},
    )
    chart_2 = render_chart(
        pedigree,
        2,
        large_print,
        paper=paper,
        shadow=shadow,
        lang={
            "continuation": "Number 1 on this chart is the same as number {pos} on chart {chart}. "
            + long_words
        },
    )
    for pdf, prefix in ((chart_1, "word"), (chart_2, "Number 1 on this chart")):
        run = next(r for r in runs(pdf) if r.text.startswith(prefix))
        assert run.text.endswith("…")
        assert (run.x, run.y, run.size) == (
            approx(kincade.pdf.LEFT_MARGIN),
            approx(BASELINE),
            8,
        )
        extent = run.x + kincade.pdf.text_width(run.text, "Helvetica", 8)
        # ends 12 pt short of the right column
        assert extent <= limit + 1e-6, (prefix, extent, limit)
        # and uses the room, rather than being cut well short of it
        assert extent > limit - 10


# ---------------------------------------------------------------- the text


def test_the_note_is_a_language_string_with_no_placeholders():
    assert kincade.lang.DEFAULT_STRINGS["chart_note"] == ENGLISH
    assert kincade.lang.PLACEHOLDERS["chart_note"] == ()
    assert kincade.lang.load_strings("de")["chart_note"] == GERMAN


def test_the_english_file_comments_the_note_above_its_key():
    lines = (kincade.lang.LANG_DIR / "en.toml").read_text(encoding="utf-8").splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith("chart_note = "))
    # a comment line above the key, as the other keys have
    assert lines[i - 1].startswith("#")


def test_the_german_note_is_drawn_on_chart_1_in_german(pedigree):
    text = drawn(render(pedigree, generations=5, lang="de"))
    assert text.count(GERMAN) == 1
    assert ENGLISH not in text


def test_an_empty_note_turns_it_off_and_chart_1_is_otherwise_the_same(pedigree):
    plain = runs(render(pedigree, generations=5))
    # precondition: the note is drawn by default
    assert any(r.text == ENGLISH for r in plain)
    off = runs(render(pedigree, generations=5, lang={"chart_note": ""}))
    assert not any(r.text == ENGLISH for r in off)
    # every other run is drawn in the same place
    assert off == [r for r in plain if r.text != ENGLISH]


# ---------------------------------------------------------------- it overlaps no box


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("shadow", [False, True], ids=["plain", "shadow"])
@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_the_note_overlaps_no_box_or_shadow(pedigree, paper, large_print, shadow, lang):
    """The note's box runs from the font's ascent above its baseline to its descent
    below, and from the left margin across its width. In normal print the highest box
    (box 8, top 42 pt) is above the baseline at 46 pt, so there the note clears box 8
    only sideways: it ends far short of the right column. In large print box 4 also
    starts at 42 pt, so it is cleared sideways in the same way. Every box outline and
    every shadow layer is checked, so an overlap of any kind fails.
    """
    pdf = render_chart(
        pedigree, large_print=large_print, paper=paper, shadow=shadow, lang=lang
    )
    note = note_run(pdf)
    assert note is not None, "the note is not drawn"
    # descent < 0
    ascent, descent = (
        pdfmetrics.getAscent("Helvetica", 8),
        pdfmetrics.getDescent("Helvetica", 8),
    )
    left, right = note.x, note.x + kincade.pdf.text_width(note.text, "Helvetica", 8)
    top, bottom = note.y - ascent, note.y - descent
    obstacles = rectangles(pdf, "B*") + rectangles(pdf, "f*")
    # every box of chart 1 is checked
    assert len(rectangles(pdf, "B*")) == (7 if large_print else 15)
    if shadow:
        assert obstacles and len(
            rectangles(pdf, "f*")
        ) == kincade.pdf.SHADOW_LAYERS * len(rectangles(pdf, "B*"))
    for bx, btop, bw, bh in obstacles:
        overlaps = left < bx + bw and bx < right and top < btop + bh and btop < bottom
        assert not overlaps, (
            f"note {left:.1f}-{right:.1f} x {top:.1f}-{bottom:.1f} hits {(bx, btop, bw, bh)}"
        )

"""Fitting text: truncation, squeezing, kerned drawing and continuation numbers."""

import io

import pytest

import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import FIX, TODAY, ged
from pdfread import drawn, runs


def test_truncation_adds_an_ellipsis():
    out = kincade.pdf.fit("x" * 200, "Times-Roman", 9, 100)
    assert out.endswith("…") and kincade.pdf.stringWidth(out, "Times-Roman", 9) <= 100
    assert kincade.pdf.fit("short", "Times-Roman", 9, 100) == "short"


@pytest.mark.parametrize("ellipsis", ["…", "...", "…..."])
@pytest.mark.parametrize(
    "text", ["x" * 200, "ab cd ef gh ij kl mn", "W" * 30 + "     ", "hello"]
)
def test_fit_is_never_wider_than_the_width_even_with_the_ellipsis(text, ellipsis):
    for width in [0, 0.5, 1, 2, 3, 5, 8, 12, 20, 50, 100]:
        out = kincade.pdf.fit(text, "Times-Roman", 9, width, ellipsis)
        assert kincade.pdf.stringWidth(out, "Times-Roman", 9) <= width, (width, out)


def test_fit_gives_nothing_when_not_even_the_ellipsis_fits():
    assert kincade.pdf.fit("x" * 200, "Times-Roman", 9, 0.01) == ""
    ell = kincade.pdf.stringWidth("...", "Times-Roman", 9)
    # exactly the ellipsis fits
    assert kincade.pdf.fit("x" * 200, "Times-Roman", 9, ell, ellipsis="...") == "..."


def test_overlong_lines_are_squeezed_before_they_are_truncated():
    font, width = "Times-Roman", 209
    # a little over 209 pt
    text = "mp. Oakvale County, Oakshire  by Service Rev. Jonathan Do"
    assert kincade.pdf.stringWidth(text, font, 9) > width
    kept, scale = kincade.pdf.fit_squeezed(text, font, 9, width)
    assert kept == text and kincade.pdf.SQUEEZE <= scale < 1
    kept, scale = kincade.pdf.fit_squeezed(text * 2, font, 9, width)
    assert kept.endswith("…") and scale >= kincade.pdf.SQUEEZE
    assert kincade.pdf.fit_squeezed("short", font, 9, width) == ("short", 1.0)
    assert kincade.pdf.fit_squeezed("", font, 9, width) == ("", 1.0)


def test_clean_degrades_to_cp1252():
    assert kincade.pdf.clean("Zoë “quoted” …") == "Zoë “quoted” …"  # all in cp1252
    # Ł has no cp1252 form even after NFKD; ź loses its accent
    assert kincade.pdf.clean("Łódź") == "?ódz"
    assert kincade.pdf.clean("ǅ") == "Dz"  # NFKD expansion, combining mark dropped


@pytest.mark.parametrize("control", ["\x00", "\x05", "\x7f", "\x81", "\x9f"])
def test_library_text_drops_non_whitespace_controls(control):
    tree = kincade.Tree({"I1": kincade.Person("I1", f"Ja{control}ne", "Doe")})
    pdf = kincade.render(tree, "I1", Options(fonts="base14", compress=False))
    assert "Jane DOE" in drawn(pdf)
    assert kincade.pdf.clean(f"Ja{control}ne") == "Jane"


@pytest.mark.parametrize(
    "space", ["\t", "\n", "\r", "\v", "\f", "\u0085", "\u00a0", "\u2003", "\u2028"]
)
def test_drawable_whitespace_uses_a_standard_space(space):
    assert kincade.pdf.clean(f"Jane{space}Ann") == "Jane Ann"


def test_kerning_narrows_text_width_and_draws_in_runs(monkeypatch):
    plain = kincade.pdf.stringWidth("Virginia", "Times-Roman", 10)
    # no kerning registered: the plain width
    assert kincade.pdf.text_width("Virginia", "Times-Roman", 10) == plain
    monkeypatch.setitem(
        kincade.pdf._KERNING,
        "Times-Roman",
        lambda a, b: -0.1 if (a, b) == ("V", "i") else 0,
    )
    assert kincade.pdf.text_width("Virginia", "Times-Roman", 10) == pytest.approx(
        plain - 1.0
    )
    # kerned width fits
    assert kincade.pdf.fit("Virginia", "Times-Roman", 10, plain - 0.5) == "Virginia"
    tree = read_gedcom(b"0 @I1@ INDI\n1 NAME Virginia /ROOT/\n0 TRLR\n")
    monkeypatch.setitem(
        kincade.pdf._KERNING,
        "Helvetica",
        lambda a, b: -0.1 if (a, b) == ("V", "i") else 0,
    )
    drawn_runs = runs(
        render_pdf(
            plan_charts(tree, "I1", 4),
            tree,
            Options(fonts="base14", compress=False, index=False, footer=""),
        )
    )
    pieces = [(r.x, r.text) for r in drawn_runs if r.text in ("V", "irginia ROOT")]
    assert [t for _, t in pieces] == ["V", "irginia ROOT"]  # split at the kerned pair
    gap = pieces[1][0] - pieces[0][0]
    assert gap == pytest.approx(kincade.pdf.stringWidth("V", "Helvetica", 9) - 0.9)


def test_draw_text_falls_back_to_unkerned_drawing_when_measure_and_draw_disagree(
    monkeypatch,
):
    calls = []

    # a different answer on every call: measurement and drawing cannot agree
    def lying(a, b):
        calls.append(1)
        return -0.002 * len(calls)

    monkeypatch.setitem(kincade.pdf._KERNING, "Helvetica", lying)
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Wvwv /Wvw/"))
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(fonts="base14", compress=False, index=False, footer="", today=TODAY),
    )
    text_x = kincade.pdf.BOX_X0[1] + kincade.pdf.TEXT_INSET_LEFT
    names = [
        (r.x, r.text) for r in runs(pdf) if r.x == text_x and r.text.startswith("W")
    ]
    # one run, at the box's text edge: the unkerned layout
    assert names == [(35.0, "Wvwv WVW")]


def test_draw_text_never_starts_a_run_outside_the_measured_width(monkeypatch):
    # absurd but bounded
    monkeypatch.setitem(
        kincade.pdf._KERNING, "Helvetica", lambda a, b: -0.5 if a == "V" else 0.5
    )
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME VAVAVA /VAVAVA/"))
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(fonts="base14", compress=False, index=False, footer="", today=TODAY),
    )
    pieces = [
        r.x
        for r in runs(pdf)
        if r.y
        == pytest.approx(kincade.pdf.LETTER.box_top[1] - 10 + kincade.pdf.NAME_BASE)
        and r.x >= kincade.pdf.BOX_X0[1]  # not the number
    ]
    assert len(pieces) > 3  # kerned: drawn in several runs
    start = kincade.pdf.BOX_X0[1] + kincade.pdf.TEXT_INSET_LEFT
    end = start + kincade.pdf.text_width("VAVAVA VAVAVA", "Helvetica", 9)
    assert all(start - 0.5 <= x <= end + 0.5 for x in pieces)


def draw_line(text, font, size=9, scale=1.0):
    """PDF bytes of one line drawn by draw_text at (100, 100) on a bare page."""
    buf = io.BytesIO()
    c = kincade.pdf.canvas.Canvas(buf, pagesize=(612, 792), pageCompression=0)
    kincade.pdf.draw_text(c, 100, 100, text, font, size, scale)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_a_run_of_i_with_a_huge_pair_is_measured_and_drawn_unkerned_and_never_mirrored(
    monkeypatch,
):
    monkeypatch.setitem(
        kincade.pdf._KERNING,
        "Helvetica",
        lambda a, b: -0.5 if (a, b) == ("i", "i") else 0,
    )
    word = "i" * 100
    plain = kincade.pdf.stringWidth(word, "Helvetica", 9)
    # kerned total would be negative
    assert kincade.pdf.text_width(word, "Helvetica", 9) == pytest.approx(plain)
    tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME {word} /ROOT/"))
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(fonts="base14", compress=False, index=False, footer="", today=TODAY),
    )
    scales = [r.scale for r in runs(pdf)]
    assert scales and all(0.5 <= s <= 1 for s in scales)


def test_kerning_that_would_leave_under_half_the_width_is_ignored(monkeypatch):
    monkeypatch.setitem(
        kincade.pdf._KERNING,
        "Helvetica",
        lambda a, b: -0.25 if (a, b) == ("i", "i") else 0,
    )
    plain = kincade.pdf.stringWidth("iiii", "Helvetica", 9)
    # kerned 1.2 pt, under half of 8.0
    assert kincade.pdf.text_width("iiii", "Helvetica", 9) == pytest.approx(plain)
    assert drawn(draw_line("iiii", "Helvetica")) == ["iiii"]  # drawn unkerned, one run
    monkeypatch.setitem(
        kincade.pdf._KERNING,
        "Helvetica",
        lambda a, b: -0.05 if (a, b) == ("i", "i") else 0,
    )
    # over half: kerned
    assert kincade.pdf.text_width("iiii", "Helvetica", 9) == pytest.approx(
        plain - 9 * 0.05 * 3
    )


@pytest.mark.parametrize("scale", [-0.5, 0.0, 0.2, 0.49, 1.7])
def test_the_horizontal_squeeze_is_clamped_to_fifty_and_a_hundred_percent(scale):
    scales = [r.scale for r in runs(draw_line("Virginia", "Times-Roman", 9, scale))]
    assert scales and all(0.5 <= s <= 1 for s in scales)


def test_fit_squeezed_never_returns_a_scale_below_half():
    # not even the ellipsis fits
    text, scale = kincade.pdf.fit_squeezed("x" * 40, "Times-Roman", 9, 0.01)
    assert text == "" and scale == 0.5


@pytest.mark.parametrize("paper", ["letter", "a4"])
@pytest.mark.parametrize("number", ["7", "1000", "99999", "1234567890"])
def test_a_continuation_number_stays_inside_the_right_margin_and_keeps_every_digit(
    paper, number
):
    tree = read_gedcom(FIX / "pedigree.ged")
    charts = plan_charts(tree, "I1", 4)
    # a continuation chart with this number (1000+ needs a huge tree)
    charts[0].continuations[8] = int(number)
    pdf = render_pdf(
        charts,
        tree,
        Options(
            today=TODAY,
            fonts="base14",
            compress=False,
            index=False,
            paper=paper,
            footer="",
        ),
    )
    geom = kincade.pdf.page_geom(paper)
    # where box 8's continuation number is drawn
    baseline = geom.box_top[8] + kincade.pdf.box_height(8) / 2 + 3
    labels = [
        r for r in runs(pdf) if r.text == number and r.y == pytest.approx(baseline)
    ]
    assert len(labels) == 1
    (label,) = labels
    # every digit, squeezed at most to half width
    assert label.text == number and 0.5 <= label.scale <= 1.0
    assert (
        label.x + kincade.pdf.text_width(number, "Times-Italic", 9) * label.scale
        <= geom.width - 6 + 1e-6
    )

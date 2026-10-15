"""Page numbers: "Page n of N" (German "Seite n von N") at the bottom left of every
page, charts and index alike, on the footer's baseline and at the left margin.
Options.page_numbers (--no-page-numbers) hides them; --no-footer hides only the footer.
The footer stays right-aligned and is fitted, with ellipsis, if it would come within 12
pt of the page number. Page numbers count PDF pages from 1.

Synthetic fixtures only.
"""

import io
import re

import pytest
from reportlab.pdfgen import canvas

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.model
import kincade.pdf
from kincade.charts import plan_charts
from kincade.pdf import Options

from conftest import FIX, render
from pdfread import count_pages, drawn, runs


def page_numbers(pdf, word="Page"):
    return [t for t in drawn(pdf) if re.fullmatch(rf"{word} \d+ (of|von) \d+", t)]


# ---------------------------------------------------------------- the numbers


def test_every_page_is_numbered_in_order_with_the_page_count(pedigree):
    pdf = render(pedigree)  # six charts and one index page
    pages = count_pages(pdf)
    assert pages == 7
    assert page_numbers(pdf) == [f"Page {n} of {pages}" for n in range(1, pages + 1)]


def test_the_index_pages_are_numbered_too_and_the_count_includes_them(long_index_tree):
    pdf = render(long_index_tree)
    pages = count_pages(pdf)
    assert pages > len(plan_charts(long_index_tree, "I1")) + 1
    assert page_numbers(pdf) == [f"Page {n} of {pages}" for n in range(1, pages + 1)]


def test_page_numbers_sit_bottom_left_on_the_footer_baseline_at_the_left_margin(
    pedigree,
):
    pdf = render(pedigree, footer="Footer here")
    drawn_runs = runs(pdf)
    footer_y = next(r.y for r in drawn_runs if r.text == "Footer here")
    x, y, text = next(
        (r.x, r.y, r.text) for r in drawn_runs if r.text.startswith("Page ")
    )
    assert text == "Page 1 of 7"
    # 18 pt, the left margin of the header rule
    assert x == pytest.approx(kincade.pdf.LEFT_MARGIN)
    assert y == pytest.approx(footer_y)  # the same baseline as the footer
    assert footer_y == pytest.approx(792 - kincade.pdf.FOOTER_INSET)


def test_the_footer_stays_right_aligned_when_page_numbers_are_drawn(pedigree):
    pdf = render(pedigree, footer="Created here")
    assert "Page 1 of 7" in drawn(pdf)
    x = next(r for r in runs(pdf) if r.text == "Created here").x
    assert x + kincade.pdf.text_width("Created here", "Helvetica", 8) == pytest.approx(
        kincade.pdf.LETTER.footer_right
    )


@pytest.mark.parametrize(
    "paper,height", [("letter", 792), ("a4", kincade.pdf.PAPER_SIZES["a4"][1])]
)
def test_the_baseline_follows_the_footer_on_both_papers(pedigree, paper, height):
    drawn_runs = runs(render(pedigree, paper=paper, generations=1, index=False))
    assert next(r.y for r in drawn_runs if r.text == "Page 1 of 1") == pytest.approx(
        height - kincade.pdf.FOOTER_INSET
    )


def test_german_page_numbers(pedigree):
    pdf = render(pedigree, lang="de")
    assert page_numbers(pdf, "Seite")[:2] == ["Seite 1 von 7", "Seite 2 von 7"]
    assert page_numbers(pdf, "Seite")[-1] == "Seite 7 von 7"
    assert "Page 1 of 7" not in drawn(pdf)


def test_the_page_number_template_is_a_language_key():
    assert kincade.lang.DEFAULT_STRINGS["page_number"] == "Page {page} of {pages}"
    assert kincade.lang.load_strings("de")["page_number"] == "Seite {page} von {pages}"
    assert kincade.lang.PLACEHOLDERS["page_number"] == ("page", "pages")


# ---------------------------------------------------------------- switches


def test_no_page_numbers_hides_them_and_nothing_else(pedigree):
    shown = drawn(render(pedigree))
    hidden = drawn(render(pedigree, page_numbers=False))
    assert page_numbers(render(pedigree, page_numbers=False)) == []
    assert [t for t in shown if t not in hidden] == [
        t for t in shown if t.startswith(("Page ", "Seite "))
    ]
    assert "Created " in " ".join(hidden)  # the footer stays


def test_no_footer_keeps_the_page_numbers(pedigree):
    pdf = render(pedigree, footer=False)
    assert page_numbers(pdf) == [f"Page {n} of 7" for n in range(1, 8)]
    assert not any(t.startswith("Created") for t in drawn(pdf))


def test_no_footer_and_no_page_numbers_leave_no_bottom_text(pedigree):
    pdf = render(pedigree, footer=False, page_numbers=False)
    assert not any(t.startswith(("Created", "Page ")) for t in drawn(pdf))


def test_cli_flags_set_the_options(tmp_path, rendered_options):
    base = [
        str(FIX / "pedigree.ged"),
        "--root",
        "@I1@",
        "--generations",
        "2",
        "-o",
        str(tmp_path / "x.pdf"),
    ]
    assert kincade.cli.main(base) == 0
    assert kincade.cli.main(base + ["--no-page-numbers"]) == 0
    assert kincade.cli.main(base + ["--no-footer"]) == 0
    assert [(o.page_numbers, o.footer) for o in rendered_options] == [
        (True, None),
        (False, None),
        (True, False),
    ]


# ---------------------------------------------------------------- collisions


def test_a_long_footer_is_fitted_to_the_room_right_of_the_page_number(pedigree):
    footer = "F" * 600
    pdf = render(pedigree, footer=footer, index=False)
    x, shown = next(
        (r.x, r.text)
        for r in runs(pdf)
        if r.text.startswith("F") and r.text.endswith("…")
    )
    page_w = kincade.pdf.text_width("Page 1 of 1", "Helvetica", 8)
    assert shown.endswith("…")
    # at least 12 pt clear of the page number
    assert x >= kincade.pdf.LEFT_MARGIN + page_w + 12 - 1e-6
    assert x + kincade.pdf.text_width(shown, "Helvetica", 8) == pytest.approx(
        kincade.pdf.LETTER.footer_right
    )


def test_a_normal_footer_is_not_touched_by_the_page_number(pedigree):
    pdf = render(pedigree, footer="Created 10 Oct 2026 using Kincade")
    assert "Created 10 Oct 2026 using Kincade" in drawn(pdf)


# ----------------------------------------------------------------
# a page number is fitted to half the usable width


def bottom_left_run(pdf, geom):
    """(x, text) of the run at the left margin on the footer's baseline."""
    baseline = geom.height - kincade.pdf.FOOTER_INSET
    return next(
        (r.x, r.text)
        for r in runs(pdf)
        if r.x == pytest.approx(kincade.pdf.LEFT_MARGIN)
        and r.y == pytest.approx(baseline)
    )


def measured(text):
    """The width of a run in the font and size of the footer line."""
    return kincade.pdf.text_width(text, "Helvetica", 8)


@pytest.mark.parametrize("paper", ["letter", "a4"])
def test_a_long_page_number_is_fitted_to_half_the_usable_width(pedigree, paper):
    geom = kincade.pdf.page_geom(paper)
    pdf = render(
        pedigree,
        paper=paper,
        generations=1,
        index=False,
        lang={"page_number": "P" * 300 + " {page} of {pages}"},
    )
    _, text = bottom_left_run(pdf, geom)
    # from the left margin to 6 pt short of the center
    usable = geom.width / 2 - kincade.pdf.PAGE_NUMBER_EDGE - kincade.pdf.LEFT_MARGIN
    assert text.endswith("…")
    assert measured(text) <= usable / 2 + 1e-6


def test_the_footer_keeps_12_pt_clear_of_a_fitted_page_number(pedigree):
    pdf = render(
        pedigree,
        generations=1,
        index=False,
        footer="F" * 600,
        lang={"page_number": "P" * 300 + " {page} of {pages}"},
    )
    x, number = bottom_left_run(pdf, kincade.pdf.LETTER)
    footer_x, footer = next((r.x, r.text) for r in runs(pdf) if r.text.startswith("F"))
    assert footer.endswith("…")
    assert footer_x >= x + measured(number) + 12 - 1e-6
    assert footer_x + measured(footer) == pytest.approx(kincade.pdf.LETTER.footer_right)


def test_no_footer_is_drawn_when_no_room_is_left_for_it():
    # so narrow that the footer has no room
    narrow = kincade.pdf.PageGeom("letter", 30, 792, kincade.pdf.LETTER.y_bottom, {})
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(30, 792), pageCompression=0)
    doc = kincade.pdf._Doc(
        kincade.model.Tree(),
        Options(),
        kincade.pdf.choose_fonts("base14"),
        kincade.lang.DEFAULT_STRINGS,
        kincade.charts.nobody_living,
        narrow,
        footer="Created here",
    )
    kincade.pdf._frame(c, doc, "Title", "", "", "Page 1 of 1")
    c.save()
    # no room for the title either: no footer, no number, not even an ellipsis
    assert drawn(buf.getvalue()) == []

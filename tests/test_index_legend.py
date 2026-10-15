"""The index legend: one line under the "Index" title on the FIRST index page only, in
the small subtitle style (the same font, size and baseline as the continuation line
under the header rule). Its text is the index.legend string (English and German); an
empty string turns it off. The index body starts below it.

Synthetic fixtures only.
"""

import pytest

import kincade.charts
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts

from conftest import render
from pdfread import count_pages, drawn, runs

ENGLISH = "The numbers after each name indicate the chart number and box number. 6-1 is box 1 on chart 6."
GERMAN = "Die Zahlen nach jedem Namen bedeuten Tafel-Nr.: 6-1 ist Nr. 1 auf Tafel 6."
CONTINUATION = "Number 1 on this chart is the same as number 8 on chart 1."


# ---------------------------------------------------------------- where it is drawn


def test_the_legend_is_drawn_right_after_the_index_title_on_the_first_index_page(
    pedigree,
):
    text = drawn(render(pedigree))
    # the title, then the legend, before the page number
    assert text[text.index("Index") + 1] == ENGLISH
    assert text.count(ENGLISH) == 1


def test_only_the_first_index_page_has_the_legend(long_index_tree):
    pdf = render(long_index_tree)
    # more than one index page
    assert count_pages(pdf) > len(plan_charts(long_index_tree, "I1")) + 1
    text = drawn(pdf)
    titles = [i for i, t in enumerate(text) if t == "Index"]
    assert len(titles) >= 2
    assert text[titles[0] + 1] == ENGLISH
    assert all(
        not text[i + 1].startswith(("The numbers after", "Die Zahlen"))
        for i in titles[1:]
    )
    assert text.count(ENGLISH) == 1


def test_the_legend_is_on_no_chart_page(pedigree):
    text = drawn(render(pedigree, index=False))
    assert ENGLISH not in text  # no index, so no legend


def test_the_legend_sits_in_the_subtitle_position_under_the_rule(pedigree):
    drawn_runs = runs(render(pedigree))
    legend = next(r for r in drawn_runs if r.text == ENGLISH)
    continuation = next(r for r in drawn_runs if r.text == CONTINUATION)
    # the left margin, like the continuation subtitle
    assert legend.x == pytest.approx(kincade.pdf.LEFT_MARGIN)
    # the same baseline, 46 pt from the top
    assert legend.y == pytest.approx(continuation.y)
    assert legend.y == pytest.approx(46)


def test_the_index_body_starts_below_the_legend(pedigree):
    drawn_runs = runs(render(pedigree))
    legend_at = next(i for i, r in enumerate(drawn_runs) if r.text == ENGLISH)
    legend = drawn_runs[legend_at]
    # the first entry: entries are in the serif, after the page number and footer
    first_entry = next(
        r for r in drawn_runs[legend_at + 1 :] if r.font == "Times-Roman"
    )
    assert first_entry.text.startswith("ASHFORD, Abel")
    assert first_entry.y == pytest.approx(kincade.pdf.INDEX_TOP)
    # one 8 pt line of room between them, no overlap
    assert legend.y + kincade.pdf.INDEX_SIZE <= first_entry.y


def test_a_long_legend_is_fitted_to_the_line_with_the_ellipsis(pedigree):
    shown = next(
        t
        for t in drawn(render(pedigree, lang={"index": {"legend": "word " * 200}}))
        if t.startswith("word")
    )
    # cut short with the language's ellipsis, as the continuation line is
    assert shown.endswith("…")
    assert (
        kincade.pdf.text_width(shown, "Helvetica", 8)
        <= kincade.pdf.LETTER.right - kincade.pdf.LEFT_MARGIN
    )


# ---------------------------------------------------------------- the text


def test_the_legend_is_an_index_string_in_the_language_files():
    assert kincade.lang.DEFAULT_STRINGS["index"]["legend"] == ENGLISH
    assert kincade.lang.load_strings("de")["index"]["legend"] == GERMAN
    assert kincade.lang.PLACEHOLDERS["index.legend"] == ()


def test_the_german_legend_is_drawn_under_the_german_title(pedigree):
    text = drawn(render(pedigree, lang="de"))
    assert text[text.index("Namensregister") + 1] == GERMAN
    assert GERMAN in text and ENGLISH not in text


def test_an_empty_legend_turns_it_off_and_the_body_is_unchanged(pedigree):
    plain = render(pedigree)
    off = render(pedigree, lang={"index": {"legend": ""}})
    text = drawn(off)
    assert ENGLISH not in text and not any(
        t.startswith("The numbers after") for t in text
    )
    # the page number follows the title directly
    assert text[text.index("Index") + 1].startswith("Page ")
    # the entries are drawn at the same places as with the legend
    body = lambda pdf: [
        r for r in runs(pdf) if r.y >= kincade.pdf.INDEX_TOP - 0.5 and r.text != ENGLISH
    ]
    assert body(off) == body(plain)


def test_the_legend_is_a_language_string_for_the_library_too(pedigree):
    text = drawn(
        render(
            pedigree,
            lang=kincade.lang.load_strings(
                "de", {"index": {"legend": "Eigener Hinweis."}}
            ),
        )
    )
    assert "Eigener Hinweis." in text and GERMAN not in text


@pytest.mark.parametrize("paper", ["letter", "a4"])
@pytest.mark.parametrize("large_print", [False, True])
def test_the_english_legend_fits_whole_on_its_line(pedigree, paper, large_print):
    legend = next(
        r
        for r in runs(render(pedigree, paper=paper, large_print=large_print))
        if r.text == ENGLISH
    )
    geom = kincade.pdf.page_geom(paper, large_print)
    assert legend.size == 8 and legend.scale == 1
    assert legend.right() <= geom.right

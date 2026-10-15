"""The name index: who is listed, the sort order and the page layout."""

import pytest

import kincade.charts
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import FIX, TODAY, ged
from pdfread import count_pages, runs


def test_index_lists_only_the_people_drawn(pedigree):
    charts = plan_charts(pedigree, "I1", generations=3)
    lines = kincade.pdf.build_index(pedigree, charts, lambda pid: False, False)
    assert len(lines) == 7  # boxes 1 to 7 only
    # boxes 8 and 14 are beyond
    assert not any("Thomas" in line or "Isaac" in line for line in lines)


def test_index_is_skipped_when_there_is_nobody_to_list():
    assert kincade.pdf._index_pages([], "Times-Roman", kincade.pdf.LETTER) == []


def test_index_layout_is_three_columns_with_a_hanging_indent():
    # the numbers docs/design.md gives
    assert (
        kincade.pdf.INDEX_COLS == 3
        and kincade.pdf.INDEX_GUTTER == 10
        and kincade.pdf.INDEX_HANGING == 10
    )
    assert round(kincade.pdf.LETTER.index_col_w) == 185
    long_entry = (
        "WILKS, " + "Very Long Given Name " * 6 + "(b. 1800 – d. 1870), 1-1, 2-3, 3-4"
    )
    (page,) = kincade.pdf._index_pages([long_entry], "Times-Roman", kincade.pdf.LETTER)
    (entry,) = page[0]
    assert len(entry) > 1 and entry[0][1] == 0
    assert all(indent == kincade.pdf.INDEX_HANGING for _, indent in entry[1:])
    assert all(
        kincade.pdf.stringWidth(text, "Times-Roman", 8) + indent
        <= kincade.pdf.LETTER.index_col_w
        for text, indent in entry
    )


# ----------------------------------------------------------------
# sort order and locations


def test_index_sorting_and_locations():
    tree = read_gedcom(FIX / "collapse.ged")
    charts = plan_charts(tree, "I1")
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    assert "DALE, Old (b. 1900 – d. 1970), 1-8, 1-12, 2-1" in entries
    names = [e.split(",")[0] for e in entries]
    assert names == sorted(names)  # surname order
    assert any(e.startswith("DALE, Cora") for e in entries)


def test_index_puts_surnameless_people_last():
    ged = b"0 @I1@ INDI\n1 NAME Zed /ZULU/\n0 @I2@ INDI\n1 NAME Anna\n0 @I3@ INDI\n1 NAME Bob /ALPHA/\n0 TRLR\n"
    tree = read_gedcom(ged)
    charts = [
        kincade.charts.Chart(
            1, {**dict.fromkeys(range(1, 16)), 1: "I1", 2: "I2", 3: "I3"}
        )
    ]
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    assert [e.split(" ")[0] for e in entries] == ["ALPHA,", "ZULU,", "Anna,"]


# ----------------------------------------------------------------
# long entries and the sort key


def test_index_entry_taller_than_a_column_stays_on_the_page():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI", "1 NAME Many /LOCATIONS/", "0 @I2@ INDI", "1 NAME Zed /ZULU/"
        )
    )
    # one person in every box of 140 charts: 2100 locations
    everywhere = dict.fromkeys(range(1, 16), "I1")
    charts = [kincade.charts.Chart(n, dict(everywhere)) for n in range(1, 141)]
    charts.append(kincade.charts.Chart(141, {**dict.fromkeys(range(1, 16)), 1: "I2"}))
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    per_col = (
        int(
            (kincade.pdf.LETTER.y_bottom - kincade.pdf.INDEX_TOP)
            // kincade.pdf.INDEX_LEADING
        )
        + 1
    )
    pages = kincade.pdf._index_pages(entries, "Times-Roman", kincade.pdf.LETTER)
    assert len(pages) > 1  # the long entry continues in the next column and page
    for page in pages:
        assert len(page) <= kincade.pdf.INDEX_COLS
        # lines per column
        assert all(sum(len(lines) for lines in column) <= per_col for column in page)
    pdf = render_pdf(charts, tree, Options(fonts="base14", compress=False, today=TODAY))
    drawn_runs = runs(pdf)
    assert all(0 <= r.y <= 792 for r in drawn_runs)  # nothing drawn off the page
    assert all(
        r.y <= kincade.pdf.LETTER.y_bottom or r.y == 750
        for r in drawn_runs
        if r.x >= kincade.pdf.INDEX_LEFT and r.y > 700
    )
    body = " ".join(r.text for r in drawn_runs)
    assert "140-15" in body and "ZULU" in body  # nothing is dropped
    assert count_pages(pdf) == 141 + len(pages)


def test_index_sorts_by_surname_then_given_name_without_the_title_then_birth_year():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Timothy /BLAKE/",
            "2 NPFX Captain",
            "1 BIRT",
            "2 DATE 1745",
            "0 @I2@ INDI",
            "1 NAME Timothy /BLAKE/",
            "2 NPFX Major",
            "1 BIRT",
            "2 DATE 1776",
            "0 @I3@ INDI",
            "1 NAME Sarah /BLAKE/",
            "1 BIRT",
            "2 DATE 1815",
            "0 @I4@ INDI",
            "1 NAME Timothy /BLAKE/",
            "2 NSFX Jr.",
            "1 BIRT",
            "2 DATE 1745",
            "0 @I5@ INDI",
            "1 NAME Ann /blake/",
        )
    )
    chart = dict.fromkeys(range(1, 16))
    charts = [
        kincade.charts.Chart(1, {**chart, 1: "I1", 2: "I2", 3: "I3", 4: "I4", 5: "I5"})
    ]
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    # 1745 ties go to the person without a suffix;
    # the title never takes part in the sort
    assert [e.split(" (")[0].split(", 1-")[0] for e in entries] == [
        "BLAKE, Ann",
        "BLAKE, Sarah",
        "BLAKE, Captain Timothy",
        "BLAKE, Timothy Jr.",
        "BLAKE, Major Timothy",
    ]


# ----------------------------------------------------------------
# wrapped entries and the bottom margin


def test_index_continuation_lines_fit_inside_the_column_including_their_indent(
    monkeypatch,
):
    entry = "ROOT, " + "x" * 300 + ", 1-1"  # an unbreakable run on a continuation line
    (page,) = kincade.pdf._index_pages([entry], "Times-Roman", kincade.pdf.LETTER)
    for text, indent in page[0][0]:
        assert (
            kincade.pdf.text_width(text, "Times-Roman", 8) + indent
            <= kincade.pdf.LETTER.index_col_w + 1e-6
        )
    # kerning widens: wrapping must notice
    monkeypatch.setitem(kincade.pdf._KERNING, "Times-Roman", lambda a, b: 0.04)
    entry = (
        "WILKS, "
        + " ".join(["Jordan Morgan Blake"] * 12)
        + " (b. 1900 – d. 1970), 1-1, 2-3"
    )
    (page,) = kincade.pdf._index_pages([entry], "Times-Roman", kincade.pdf.LETTER)
    lines = page[0][0]
    assert len(lines) > 2
    for text, indent in lines:
        assert (
            kincade.pdf.text_width(text, "Times-Roman", 8) + indent
            <= kincade.pdf.LETTER.index_col_w + 1e-6
        )


def test_placeholder_surnames_sort_with_the_no_surname_group_but_display_as_written():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Mary /(UNKNOWN)/",
            "0 @I2@ INDI",
            "1 NAME Zed /ZULU/",
            "0 @I3@ INDI",
            "1 NAME Anna /ABEL/",
            "0 @I4@ INDI",
            "1 NAME Bob /?/",
            "0 @I5@ INDI",
            "1 NAME Cy //",
            "0 @I6@ INDI",
            "1 NAME Di /Unknown/",
            "0 @I7@ INDI",
            "1 NAME Eve /N.N./",
        )
    )
    chart = dict.fromkeys(range(1, 16))
    charts = [kincade.charts.Chart(1, {**chart, **{n: f"I{n}" for n in range(1, 8)}})]
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    heads = [e.split(", 1-")[0] for e in entries]
    assert heads == [
        "ABEL, Anna",
        "ZULU, Zed",
        "?, Bob",
        "Cy",
        "UNKNOWN, Di",
        "N.N., Eve",
        "(UNKNOWN), Mary",
    ]


def test_index_body_stays_above_the_charts_bottom_margin():
    per_col_lines = lambda page: max(
        sum(len(lines) for lines in column) for column in page
    )
    pages = kincade.pdf._index_pages(
        [f"SURNAME, Person{i}, 1-1" for i in range(400)],
        "Times-Roman",
        kincade.pdf.LETTER,
    )
    longest = max(per_col_lines(page) for page in pages)
    assert longest > 60  # columns are really filled
    assert (
        kincade.pdf.INDEX_TOP + (longest - 1) * kincade.pdf.INDEX_LEADING
        <= kincade.pdf.LETTER.y_bottom
    )


def test_a4_index_body_stays_above_the_bottom_margin():
    g = kincade.pdf.page_geom("a4")
    pages = kincade.pdf._index_pages(
        [f"SURNAME, Person{i}, 1-1" for i in range(400)], "Times-Roman", g
    )
    longest = max(
        sum(len(lines) for lines in column) for page in pages for column in page
    )
    assert longest > 60
    assert (
        kincade.pdf.INDEX_TOP + (longest - 1) * kincade.pdf.INDEX_LEADING <= g.y_bottom
    )


@pytest.mark.parametrize("show_ids", [False, True])
@pytest.mark.parametrize("years", [False, True])
def test_index_separates_the_name_and_years_from_chart_boxes(show_ids, years):
    lines = ["0 @I12@ INDI", "1 NAME Jane /Doe/"]
    if years:
        lines += ["1 BIRT", "2 DATE 1900", "1 DEAT", "2 DATE 1980"]
    tree = read_gedcom(ged(*lines))
    charts = [
        kincade.charts.Chart(1, {11: "I12"}, drawn=frozenset({11})),
        kincade.charts.Chart(6, {1: "I12"}, drawn=frozenset({1})),
    ]
    record = " [I12]" if show_ids else ""
    dates = " (b. 1900 – d. 1980)" if years else ""
    assert kincade.pdf.build_index(
        tree, charts, lambda pid: False, False, show_ids=show_ids
    ) == [f"DOE, Jane{record}{dates}, 1-11, 6-1"]

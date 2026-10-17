"""Page layout: page counts, box geometry, connectors, header, footer and paper."""

import itertools
import re

import pytest

import kincade.cli
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import (
    FIX,
    PAPERS,
    PRINTS,
    TODAY,
    approx,
    full_chart,
    ged,
    render,
)
from pdfread import count_pages, ink_box, lines, overlaps, pages, rectangles, runs

# ---------------------------------------------------------------- rendering


def test_render_smoke_and_page_counts(pedigree):
    charts = plan_charts(pedigree, "I1")
    pdf = render_pdf(charts, pedigree, Options(today=TODAY, fonts="base14"))
    assert pdf.startswith(b"%PDF")
    assert count_pages(pdf) == len(charts) + 1  # six charts, one index page
    no_index = render_pdf(
        charts, pedigree, Options(today=TODAY, index=False, fonts="base14")
    )
    assert count_pages(no_index) == len(charts)


def test_index_flows_over_many_pages(long_index_tree):
    charts = plan_charts(long_index_tree, "I1")
    pdf = render_pdf(charts, long_index_tree, Options(today=TODAY, fonts="base14"))
    assert count_pages(pdf) > len(charts) + 1


def test_render_is_raw_text_searchable_without_compression(pedigree):
    pdf = render(pedigree, compress=False, title="Test Chart", footer="Footer here")
    # parentheses are escaped in PDF strings
    for text in (
        b"(Jane ASHFORD)",
        b"(b. 14 Feb 1980)",
        b"(bp. Springfield, Illinois)",
        b"(m. 12 Jun 1975)",
        b"(Chart 1)",
        b"(Test Chart)",
        b"(Footer here)",
        b"(Number 1 on this chart is the same as number 8 on chart 1.)",
        b"(Index)",
        b"(ASHFORD, Jane \\(b. 1980\\), 1-1)",
    ):
        assert text in pdf, text


def test_empty_slots_drawn_by_default_and_skipped_with_no_empty():
    tree = read_gedcom(FIX / "cycle.ged")
    full = render(tree, generations=4, index=False)
    lean = render(tree, generations=4, index=False, empty_boxes=False)
    # every box drawn on the chart: a research worksheet
    assert full.count(b"(dp.)") == 15
    # only the four people who exist: positions 1, 2, 4 and 8
    assert lean.count(b"(dp.)") == 4


@pytest.mark.parametrize(
    "generations,boxes", [(1, 1), (3, 7), (4, 15), (5, 27), (7, 75), (None, 90)]
)
def test_generations_set_how_many_boxes_are_drawn(pedigree, generations, boxes):
    pdf = render(pedigree, generations=generations, index=False)
    # one rectangle per drawn box
    assert (
        sum(1 for *_, w, _h in rectangles(pdf, page=None) if w == kincade.pdf.BOX_W)
        == boxes
    )


def test_generations_five_gives_boxes_one_to_three_on_continuation_charts(pedigree):
    pdf = render(pedigree, generations=5, index=False)
    assert (
        pdf.count(b"(Number 1 on this chart is the same as number 8 on chart 1.)") == 1
    )
    assert count_pages(pdf) == 5


class _Lines:
    """Stands in for a canvas and records the x coordinates of every straight line."""

    def __init__(self):
        self.xs = []

    def setStrokeColorRGB(self, *_):
        pass

    def setLineWidth(self, *_):
        pass

    def line(self, x1, y1, x2, y2):
        self.xs += [x1, x2]


@pytest.mark.parametrize(
    "generations,rightmost", [(3, kincade.pdf.BOX_X0[7]), (4, kincade.pdf.BOX_X0[8])]
)
def test_connectors_stop_at_the_last_drawn_generation(pedigree, generations, rightmost):
    chart = plan_charts(pedigree, "I1", generations)[0]
    canvas_ = _Lines()
    kincade.pdf._connectors(
        canvas_,
        lambda pos: kincade.pdf._shown(chart, pos, empty_boxes=True),
        kincade.pdf.LETTER,
    )
    # no stub reaches a box beyond the limit
    assert canvas_.xs and max(canvas_.xs) == rightmost
    right_trunk_x = (
        kincade.pdf.BOX_X0[4] + kincade.pdf.BOX_W + kincade.pdf.RIGHT_TRUNK_DX
    )
    assert (right_trunk_x in canvas_.xs) == (generations == 4)


# ---------------------------------------------------------------- page layout


def test_box_metrics_give_78_and_58_point_boxes():
    # the numbers docs/design.md gives
    assert (
        kincade.pdf.box_height(1) == 78
        and kincade.pdf.box_height(2) == 78
        and kincade.pdf.box_height(14) == 78
    )
    assert kincade.pdf.box_height(3) == 58 and kincade.pdf.box_height(15) == 58
    pdf = kincade.pdf
    assert (pdf.NAME_BASE, pdf.DETAIL_GAP, pdf.LEADING, pdf.BOTTOM_PAD) == (
        11,
        12,
        10,
        5,
    )


def test_right_column_fills_the_page_with_uniform_gaps():
    top, height = kincade.pdf.LETTER.box_top, kincade.pdf.box_height
    assert top[8] == kincade.pdf.Y_TOP
    assert top[15] + height(15) == pytest.approx(kincade.pdf.LETTER.y_bottom)
    gaps = [top[p + 1] - (top[p] + height(p)) for p in range(8, 15)]
    assert gaps == pytest.approx([gaps[0]] * 7) and gaps[0] == pytest.approx(21.5)


def test_cached_page_geometry_has_read_only_box_positions():
    geom = kincade.pdf.page_geom("a4", large_print=True, shadow=True)
    for positions in (geom.box_top, geom.box_x0):
        with pytest.raises(TypeError):
            positions[1] = 0


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", PRINTS)
@pytest.mark.parametrize("shadow", [False, True])
def test_rendered_boxes_have_equal_gaps_to_the_edges_above_and_below(
    pedigree, paper, large_print, shadow
):
    pdf = render(
        pedigree, paper=paper, large_print=large_print, shadow=shadow, index=False
    )
    first_right = 4 if large_print else 8
    # Both the enlarged initial root and an ordinary continuation root fit evenly.
    for page in (0, 1):
        boxes = dict(enumerate(rectangles(pdf, "B*", page), 1))
        for pos in range(1, first_right):
            above, below = (
                (5, 6) if pos == 1 and not large_print else (2 * pos, 2 * pos + 1)
            )
            _, top, _, height = boxes[pos]
            gap_above = top - (boxes[above][1] + boxes[above][3])
            gap_below = boxes[below][1] - (top + height)
            assert gap_above == pytest.approx(gap_below, abs=0.001), (page, pos)
        gaps = [
            boxes[p + 1][1] - (boxes[p][1] + boxes[p][3])
            for p in range(first_right, 2 * first_right - 1)
        ]
        assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=0.001)


def test_connectors_meet_each_box_at_its_vertical_center():
    geom = kincade.pdf.LETTER
    for pos in geom.box_top:
        assert kincade.pdf.stub_y(pos, geom) == pytest.approx(
            geom.box_top[pos] + geom.h(pos) / 2
        )


def test_left_zone_boxes_do_not_touch_and_everything_is_on_the_page():
    order = [4, 2, 5, 1, 6, 3, 7]  # top to bottom
    for above, below in itertools.pairwise(order):
        gap = kincade.pdf.LETTER.box_top[below] - (
            kincade.pdf.LETTER.box_top[above] + kincade.pdf.box_height(above)
        )
        assert gap >= 8, (above, below, gap)
    for p in range(1, 16):
        assert kincade.pdf.LETTER.box_top[p] >= kincade.pdf.Y_TOP
        assert (
            kincade.pdf.LETTER.box_top[p] + kincade.pdf.box_height(p)
            <= kincade.pdf.LETTER.y_bottom + 1e-9
        )
    assert kincade.pdf.LETTER.y_bottom < 750 - 8  # clear of the footer baseline


def test_text_baselines_leave_room_above_and_below(pedigree):
    pdf = render(pedigree, generations=4, index=False)
    top, h = kincade.pdf.LETTER.box_top[1] - 5, 88
    box1 = [
        (r.y, r.text)
        for r in runs(pdf)
        if r.x == kincade.pdf.BOX_X0[1] + kincade.pdf.TEXT_INSET_LEFT
    ]
    # name, +12, then +10 each
    assert [round(y - top, 2) for y, _ in box1] == [11, 23, 33, 43, 53, 63, 73, 83]
    # last baseline 5 pt above the bottom edge
    assert box1[-1][0] == pytest.approx(top + h - 5)
    assert box1[0][1] == "Jane ASHFORD" and box1[-1][1].startswith("dp.")


def test_box_numbers_and_continuation_numbers_sit_at_the_box_metrics(pedigree):
    # all charts: chart 1 has continuations
    drawn_runs = runs(render(pedigree, index=False))
    x1 = kincade.pdf.BOX_X0[8] + kincade.pdf.BOX_W
    cont = [(r.y, r.text) for r in drawn_runs if r.x == x1 + 5]
    top8, h8 = kincade.pdf.LETTER.box_top[8], kincade.pdf.box_height(8)
    # center + 3
    assert any(t == "2" and y == pytest.approx(top8 + h8 / 2 + 3) for y, t in cont)
    # right column
    numbers = {
        r.text: r.y
        for r in drawn_runs
        if r.text.isdigit() and r.x < kincade.pdf.BOX_X0[8] - 2 and r.x > 300
    }
    # even: level with the name
    assert numbers["8"] == pytest.approx(kincade.pdf.LETTER.box_top[8] + 11)
    # odd: last
    assert numbers["9"] == pytest.approx(
        kincade.pdf.LETTER.box_top[9] + kincade.pdf.box_height(9) - 5
    )


# ----
# header and footer fitting ---------------------------------------------------------


def test_title_footer_and_subtitle_are_fitted(pedigree):
    pdf = render(
        pedigree,
        index=False,
        title="T" * 400,
        footer="F" * 600,
        lang={"chart_note": "N" * 400},
    )
    drawn_runs = runs(pdf)
    x, title = next((r.x, r.text) for r in drawn_runs if r.y == pytest.approx(32))
    label = kincade.pdf.text_width("Chart 1", "Helvetica", 9)
    assert title.endswith("…")
    width = kincade.pdf.text_width(title, "Helvetica-Bold", 16)
    # at least 10 pt clear of the chart label
    assert x + width <= 593.5 - label - 10 + 1e-6
    # not the page number
    x, footer = next(
        (r.x, r.text)
        for r in drawn_runs
        if r.y == pytest.approx(750) and r.text.startswith("F")
    )
    assert footer.endswith("…") and x >= 18 - 1e-6
    assert x + kincade.pdf.text_width(footer, "Helvetica", 8) == pytest.approx(592.5)
    note = next(r for r in drawn_runs if r.text.startswith("N"))  # chart 1's subtitle
    assert note.text.endswith("…")
    # 12 pt short of the right column
    assert note.right() <= kincade.pdf.BOX_X0[8] - 12 + 1e-6
    idx = render(pedigree, lang={"index": {"title": "T" * 400}})
    # the index title; the charts' is "Cascading Pedigree"
    title = next(
        r for r in runs(idx) if r.y == pytest.approx(32) and r.text.startswith("T")
    )
    assert title.text.endswith("…")
    # index pages have no chart label: the title may run to the rule's end
    assert 593 - 16 < title.right() <= 593 + 1e-6


@pytest.mark.parametrize("paper", ["letter", "a4"])
@pytest.mark.parametrize(
    "template,count",
    [
        ("Long translated label " * 80 + "{n}", 1),
        ("{n} " + "Long translated label " * 80, 1),
        ("Long prefix " * 40 + "{n}" + " long suffix" * 40, 1),
        ("Chart {n} " + "long label " * 80 + " sheet {n}", 2),
        ("Literal {{n}} " + "long label " * 80 + "{n}", 1),
    ],
    ids=["number_last", "number_first", "number_middle", "repeated", "escaped"],
)
def test_long_chart_labels_keep_the_number_and_clear_the_title(
    pedigree, paper, template, count
):
    pdf = render(
        pedigree,
        index=False,
        paper=paper,
        title="Pedigree",
        lang={"chart_label": template},
    )
    header = [r for r in runs(pdf) if r.y == pytest.approx(35)]
    label = header[0]
    assert label.x >= 18
    assert label.right() <= kincade.pdf.PAPER_SIZES[paper][0] - 18.5 + 0.01
    assert label.text.count("1") == count
    assert "…" in label.text
    title = next(r for r in runs(pdf) if r.text == "Pedigree")
    assert title.right() + 10 <= label.x + 0.01


def test_a_short_title_is_not_touched(pedigree):
    drawn_runs = runs(render(pedigree, index=False))
    assert (
        next(r.text for r in drawn_runs if r.y == pytest.approx(32))
        == "Cascading Pedigree — Jane ASHFORD"
    )


# ----------------------------------------------------------------
# paper sizes, footers and box text insets

A4_W, A4_H = 595.28, 841.89


LETTER_CHART1_BOXES = [  # chart 1 boxes 1-15 on Letter: (x, y, w, h) in PDF points
    (30.0, 353.75, 215.0, 88.0),
    (73.0, 527.75, 215.0, 78.0),
    (73.0, 179.75, 215.0, 58.0),
    (116.0, 622.25, 215.0, 78.0),
    (116.0, 453.25, 215.0, 58.0),
    (116.0, 264.25, 215.0, 78.0),
    (116.0, 95.25, 215.0, 58.0),
    (358.0, 672.0, 215.0, 78.0),
    (358.0, 592.5, 215.0, 58.0),
    (358.0, 493.0, 215.0, 78.0),
    (358.0, 413.5, 215.0, 58.0),
    (358.0, 314.0, 215.0, 78.0),
    (358.0, 234.5, 215.0, 58.0),
    (358.0, 135.0, 215.0, 78.0),
    (358.0, 55.5, 215.0, 58.0),
]


def test_letter_chart_one_box_geometry(pedigree):
    pdf = render(pedigree, generations=4, index=False, paper="letter")
    assert b"/MediaBox [ 0 0 612 792 ]" in pdf
    assert [
        (x, 792 - top - h, w, h) for x, top, w, h in rectangles(pdf)
    ] == LETTER_CHART1_BOXES


def test_a4_pages_are_595_by_842_points(pedigree):
    pdf = render(pedigree, paper="a4")
    assert set(re.findall(rb"/MediaBox \[[^\]]*\]", pdf)) == {
        b"/MediaBox [ 0 0 595.28 841.89 ]"
    }


def test_every_a4_box_lies_inside_the_layout_and_the_left_zone_does_not_overlap(
    pedigree,
):
    # (left, top, right, bottom)
    boxes = [
        (x, top, x + w, top + h)
        for x, top, w, h in rectangles(
            render(pedigree, generations=4, index=False, paper="a4")
        )
    ]
    assert len(boxes) == 15
    # Letter's bottom edge 736.5 is 55.5 pt above the foot of the page
    y_bottom = A4_H - 55.5
    for pos, (_left, top, right, bottom) in enumerate(boxes, start=1):
        assert top >= kincade.pdf.Y_TOP - 1e-6 and bottom <= y_bottom + 1e-6, pos
        # the right column stops at the right margin
        assert right <= A4_W - 19 + 1e-6, pos
    assert boxes[7][1] == pytest.approx(kincade.pdf.Y_TOP) and boxes[14][
        3
    ] == pytest.approx(y_bottom)
    # right column: uniform gaps, recomputed
    gaps = [boxes[i + 1][1] - boxes[i][3] for i in range(7, 14)]
    # PDF coordinates carry four decimals
    assert gaps == pytest.approx([gaps[0]] * 7, abs=1e-3)
    assert gaps[0] == pytest.approx(
        (y_bottom - kincade.pdf.Y_TOP - 4 * 78 - 4 * 58) / 7, abs=1e-3
    )
    for a, b in itertools.combinations(range(7), 2):  # boxes 1-7 share the left zone
        (la, ta, ra, ba), (lb, tb, rb, bb) = boxes[a], boxes[b]
        if la < rb and lb < ra:  # overlapping in x, so they must be apart in y
            assert ba <= tb + 1e-6 or bb <= ta + 1e-6, (a + 1, b + 1)


def test_footer_is_on_every_page_by_default(pedigree):
    pdf = render(pedigree, footer="Custom footer")
    # charts and index pages alike
    assert pdf.count(b"(Custom footer)") == count_pages(pdf)


def test_no_footer_leaves_it_off_every_page(pedigree):
    pdf = render(pedigree, footer=False)
    assert b"(Created" not in pdf
    # the rest of every page is drawn
    assert pdf.count(b"(Chart ") == 6 and b"(Index)" in pdf


def test_box_text_has_a_5_point_left_inset_and_a_3_point_right_clearance():
    # the numbers docs/design.md gives
    assert (kincade.pdf.TEXT_INSET_LEFT, kincade.pdf.TEXT_INSET_RIGHT) == (5, 3)
    assert kincade.pdf.TEXT_WIDTH == kincade.pdf.BOX_W - 8 == 207


def test_box_text_is_fitted_into_the_text_width(pedigree, monkeypatch):
    widths = []
    real = kincade.pdf.fit_squeezed

    def spy(text, font, size, width, **kwargs):  # kwargs: the language's ellipsis
        widths.append(width)
        return real(text, font, size, width, **kwargs)

    monkeypatch.setattr(kincade.pdf, "fit_squeezed", spy)
    render(pedigree, generations=1, index=False)
    assert widths and max(widths) == kincade.pdf.TEXT_WIDTH
    assert min(widths) >= 0


def test_long_box_text_starts_5_points_in_and_ends_3_points_short_of_the_edge():
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME " + "1234 " * 12 + "/Smith/"))
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, index=False, footer=""),
    )
    name_y = kincade.pdf.LETTER.box_top[1] - 5 + kincade.pdf.NAME_BASE
    (run,) = [
        r
        for r in runs(pdf)
        if r.y == pytest.approx(name_y) and r.x >= kincade.pdf.BOX_X0[1]
    ]
    assert run.text.endswith("…") and 0.5 <= run.scale <= 1.0
    assert run.x == pytest.approx(kincade.pdf.BOX_X0[1] + 5)
    assert run.right() <= (kincade.pdf.BOX_X0[1] + kincade.pdf.BOX_W - 3 + 1e-6)


@pytest.mark.parametrize(
    "paper,width,height", [("letter", 612, 792), ("a4", A4_W, A4_H)]
)
def test_header_and_footer_keep_their_margins_on_both_papers(
    pedigree, paper, width, height
):
    drawn_runs = runs(render(pedigree, generations=4, index=False, paper=paper))
    label = next(r for r in drawn_runs if r.text == "Chart 1")
    footer = next(r for r in drawn_runs if r.text.startswith("Created"))
    # right-aligned items sit at the same offsets from the right edge as on Letter
    # (593.5 and 592.5 there)
    assert label.x + kincade.pdf.stringWidth(
        "Chart 1", "Helvetica", 9
    ) == pytest.approx(width - 18.5)
    assert footer.x + kincade.pdf.stringWidth(
        footer.text, "Helvetica", 8
    ) == pytest.approx(width - 19.5)
    # footer baseline 42 pt above the bottom edge
    assert footer.y == pytest.approx(height - 42)


@pytest.mark.parametrize(
    "paper,width,height", [("letter", 612, 792), ("a4", A4_W, A4_H)]
)
def test_page_geometry_per_paper(paper, width, height):
    g = kincade.pdf.page_geom(paper)
    assert (g.width, g.height) == (width, height)
    # the header rule and the index end 19 pt from the right edge
    assert g.right == pytest.approx(width - 19)
    assert g.y_bottom == pytest.approx(height - 55.5)  # 736.5 on Letter
    assert (
        kincade.pdf.INDEX_LEFT + 3 * g.index_col_w + 2 * kincade.pdf.INDEX_GUTTER
        == pytest.approx(g.right)
    )


def test_the_paper_flag_takes_letter_or_a4_and_defaults_to_letter(tmp_path, capsys):
    assert kincade.cli._parser().parse_args(["x.ged", "--root", "I1"]).paper == "letter"
    assert (
        kincade.cli._parser()
        .parse_args(["x.ged", "--root", "I1", "--paper", "a4"])
        .paper
        == "a4"
    )
    out = tmp_path / "a4.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--paper",
                "a4",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    assert b"/MediaBox [ 0 0 595.28 841.89 ]" in out.read_bytes()
    with pytest.raises(SystemExit) as e:
        kincade.cli._parser().parse_args(["x.ged", "--root", "I1", "--paper", "legal"])
    assert e.value.code == 2 and "legal" in capsys.readouterr().err


def test_render_refuses_a_paper_it_does_not_know(pedigree):
    with pytest.raises(ValueError, match="paper"):
        render(pedigree, paper="legal")


SHADOWS = [False, True]


CONNECTOR_HALF_WIDTH = 0.125  # connectors are drawn 0.25 pt wide


def connector_rectangles(pdf):
    """Each connector segment as the thin rectangle it covers: its line width either
    side of it.
    """
    out = []
    for a, b, c, d in lines(pdf):
        x0, x1 = sorted((a, c))
        y0, y1 = sorted((b, d))
        h = CONNECTOR_HALF_WIDTH
        out.append((x0 - h, y0 - h, x1 - x0 + 2 * h, y1 - y0 + 2 * h))
    return out


def box_numbers(pdf, geom):
    """The box number runs on the first page, by position."""
    runs = [
        r
        for r in pages(pdf)[0]
        if r.font == "Helvetica-Bold" and r.size == geom.size and r.text.isdigit()
    ]
    return {int(r.text): r for r in runs}


# ---- box numbers: 4 pt (scaled) left of the box, clear of connectors and boxes


@pytest.mark.parametrize("shadow", SHADOWS, ids=["plain", "shadow"])
@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_each_box_number_ends_4_points_left_of_its_box(paper, large_print, shadow):
    geom = kincade.pdf.page_geom(paper, large_print, shadow)
    numbers = box_numbers(full_chart(large_print, paper=paper, shadow=shadow), geom)
    assert sorted(numbers) == list(range(1, 2**geom.gens))  # every box is numbered
    for pos, run in numbers.items():
        assert run.right() == approx(geom.box_x0[pos] - 4 * geom.scale)


@pytest.mark.parametrize("shadow", SHADOWS, ids=["plain", "shadow"])
@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_no_box_number_overlaps_a_connector_or_another_box(paper, large_print, shadow):
    geom = kincade.pdf.page_geom(paper, large_print, shadow)
    pdf = full_chart(large_print, paper=paper, shadow=shadow)
    obstacles = (
        rectangles(pdf, "B*") + rectangles(pdf, "f*") + connector_rectangles(pdf)
    )
    assert obstacles
    for pos, run in box_numbers(pdf, geom).items():
        number = ink_box(run)
        hit = [o for o in obstacles if overlaps(number, o)]
        assert not hit, f"box number {pos} at {number} overlaps {hit}"

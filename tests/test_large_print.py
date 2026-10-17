"""Large print (--large-print, config large_print, Options.large_print): 14 pt box text
instead of 9 pt, and three generations on a page instead of four. The fonts, leading,
paddings and insets of a box scale by 14/9. Box 1 is at x = 30, boxes 2 and 3 at x = 73,
and boxes 4 to 7 form the right column; every box is as wide as the page allows (236.5
pt on Letter). The right column (boxes 4 to 7) is stacked from Y_TOP to the bottom edge
with one uniform gap that fills the space exactly, as the normal right column does;
boxes 2 and 3 and continuation roots are centered on their parents. The initial root,
including its spouse row, is centered between boxes 2 and 3.
Continuation charts start from boxes 4 to 7; --generations counts the root as 1 and each
continuation level adds two generations (three without large print). Headers, footers,
page numbers and the index are as in normal print.

Synthetic fixtures only.
"""

import itertools

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import BOX_X0, Options, render_pdf

from conftest import FIX, PAPERS, approx, ged, render_charts
from pdfread import count_pages, lines, pages, rectangles

SCALE = 14 / 9
MIN_GAP = 8  # the least vertical gap between two boxes that overlap horizontally
ELLIPSIS = "…"


def large(paper="letter", shadow=False):
    return kincade.pdf.page_geom(paper, True, shadow)


def render_large(tree, root="I1", generations=None, **opts):
    """The chart pages alone, in large print unless large_print=False."""
    return render_charts(tree, root, generations, **{"large_print": True, **opts})


def chain(length):
    """A single line of ancestors: P0 (the root) <- P1 <- P2 ... , each the father of
    the one before.
    """
    out = []
    for i in range(length):
        out += [f"0 @P{i}@ INDI", f"1 NAME Person{i} /CHAIN/"]
        if i + 1 < length:
            out.append(f"1 FAMC @F{i}@")
    for i in range(length - 1):
        out += [f"0 @F{i}@ FAM", f"1 HUSB @P{i + 1}@", f"1 CHIL @P{i}@"]
    return read_gedcom(ged(*out))


# ---------------------------------------------------------------- geometry


@pytest.mark.parametrize("paper", PAPERS)
def test_normal_print_geometry(paper):
    geom = kincade.pdf.page_geom(paper)
    assert (geom.large_print, geom.gens, geom.size) == (False, 4, 9)
    assert geom.box_w == kincade.pdf.BOX_W and geom.box_x0 == BOX_X0
    assert geom == kincade.pdf.page_geom(paper, False)
    assert (geom.name_base, geom.detail_gap, geom.leading, geom.bottom_pad) == (
        kincade.pdf.NAME_BASE,
        kincade.pdf.DETAIL_GAP,
        kincade.pdf.LEADING,
        kincade.pdf.BOTTOM_PAD,
    )
    assert (geom.inset_left, geom.inset_right, geom.text_w) == (
        kincade.pdf.TEXT_INSET_LEFT,
        kincade.pdf.TEXT_INSET_RIGHT,
        kincade.pdf.TEXT_WIDTH,
    )


def test_the_column_formula_reproduces_the_normal_columns():
    width, x0 = kincade.pdf.column_layout(4, 573)
    assert width == kincade.pdf.BOX_W and x0 == BOX_X0


def test_the_large_print_columns_on_letter():
    g = large()
    assert (g.large_print, g.gens, g.size) == (True, 3, 14)
    assert g.box_x0 == {
        1: 30,
        2: 73,
        3: 73,
        4: g.box_x0[4],
        5: g.box_x0[4],
        6: g.box_x0[4],
        7: g.box_x0[4],
    }
    assert g.box_w == pytest.approx(236.5)  # (573 - 27 - 73) / 2
    # 27 pt clear of the left zone, as in normal print
    assert g.box_x0[4] == pytest.approx(73 + 236.5 + 27)
    # the same right edge as normal print on Letter
    assert g.box_x0[4] + g.box_w == pytest.approx(573)


def test_the_large_print_columns_on_a4_are_recomputed():
    g = large("a4")
    # the same right margin as Letter, so the continuation numbers have the room
    right_edge = 595.28 - (612 - 573)
    assert g.box_x0[4] + g.box_w == pytest.approx(right_edge)
    assert g.box_w == pytest.approx((right_edge - 27 - 73) / 2)
    assert g.box_x0[1] == 30 and g.box_x0[2] == g.box_x0[3] == 73
    assert g.box_x0[4] == pytest.approx(73 + g.box_w + 27)
    assert g.box_w < large("letter").box_w  # narrower page, narrower boxes


@pytest.mark.parametrize("paper", PAPERS)
def test_every_text_measure_scales_by_14_over_9(paper):
    g = large(paper)
    assert g.name_base == pytest.approx(kincade.pdf.NAME_BASE * SCALE)
    assert g.detail_gap == pytest.approx(kincade.pdf.DETAIL_GAP * SCALE)
    assert g.leading == pytest.approx(kincade.pdf.LEADING * SCALE)
    assert g.bottom_pad == pytest.approx(kincade.pdf.BOTTOM_PAD * SCALE)
    assert g.inset_left == pytest.approx(kincade.pdf.TEXT_INSET_LEFT * SCALE)
    assert g.inset_right == pytest.approx(kincade.pdf.TEXT_INSET_RIGHT * SCALE)
    assert g.id_size == pytest.approx(kincade.pdf.RECORD_ID_SIZE * SCALE)
    assert g.id_gap == pytest.approx(kincade.pdf.RECORD_ID_GAP * SCALE)
    assert g.text_w == pytest.approx(g.box_w - g.inset_left - g.inset_right)
    # the root and the fathers
    assert g.h(1) == g.h(2) == g.h(4) == g.h(6) == pytest.approx(78 * SCALE)
    assert g.h(3) == g.h(5) == g.h(7) == pytest.approx(58 * SCALE)  # the mothers


SHADOWS = pytest.mark.parametrize("shadow", [False, True], ids=["plain", "shadow"])


@SHADOWS
@pytest.mark.parametrize("paper", PAPERS)
def test_all_boxes_lie_between_the_top_and_the_bottom_edge(paper, shadow):
    g = large(paper, shadow)
    assert set(g.box_top) == set(range(1, 8))
    for pos in range(1, 8):
        # box 4 starts on Y_TOP, to float rounding
        assert g.box_top[pos] >= kincade.pdf.Y_TOP - 1e-9
        assert g.box_top[pos] + g.h(pos) <= g.y_bottom + 1e-9


@SHADOWS
@pytest.mark.parametrize("paper", PAPERS)
def test_no_boxes_overlap_and_boxes_that_share_columns_keep_8_points(paper, shadow):
    g = large(paper, shadow)
    for a, b in itertools.combinations(range(1, 8), 2):
        across = min(g.box_x0[a] + g.box_w, g.box_x0[b] + g.box_w) - max(
            g.box_x0[a], g.box_x0[b]
        )
        if across <= 0:
            continue  # side by side
        gap = max(
            g.box_top[b] - (g.box_top[a] + g.h(a)),
            g.box_top[a] - (g.box_top[b] + g.h(b)),
        )
        assert gap >= MIN_GAP, (a, b, gap)


@SHADOWS
@pytest.mark.parametrize("paper", PAPERS)
def test_the_left_zone_is_clear_of_the_right_column(paper, shadow):
    g = large(paper, shadow)
    left_edge = max(g.box_x0[p] + g.box_w for p in (1, 2, 3))
    assert g.box_x0[4] - left_edge >= 27 - 1e-9
    order = sorted((1, 2, 3), key=lambda p: g.box_top[p])
    assert order == [2, 1, 3]  # top to bottom, as in normal print
    for above, below in itertools.pairwise(order):
        assert g.box_top[below] - (g.box_top[above] + g.h(above)) >= MIN_GAP


@SHADOWS
@pytest.mark.parametrize("paper", PAPERS)
def test_the_right_column_fills_the_usable_area_with_one_gap_as_in_normal_print(
    paper, shadow
):
    g = large(paper, shadow)
    # the stack starts at the top of the usable area
    assert g.box_top[4] == pytest.approx(kincade.pdf.Y_TOP)
    # and ends on the bottom edge, nothing left over
    assert g.box_top[7] + g.h(7) == pytest.approx(g.y_bottom)
    gaps = [
        g.box_top[below] - (g.box_top[above] + g.h(above))
        for above, below in itertools.pairwise(range(4, 8))
    ]
    assert gaps == pytest.approx([gaps[0]] * 3)  # one uniform gap
    assert gaps[0] == pytest.approx(
        (g.y_bottom - kincade.pdf.Y_TOP - sum(g.h(p) for p in range(4, 8))) / 3
    )
    assert gaps[0] > 2 * g.leading  # the gap fills the column: no limit of two leadings
    # the normal right column is laid out the same way
    n = kincade.pdf.page_geom(paper, False, shadow)
    assert n.box_top[8] == pytest.approx(kincade.pdf.Y_TOP)
    assert n.box_top[15] + n.h(15) == pytest.approx(n.y_bottom)


@pytest.mark.parametrize("paper", PAPERS)
def test_each_left_box_is_centered_between_its_parents_edges(paper):
    g = large(paper)
    center = {p: g.box_top[p] + g.h(p) / 2 for p in range(1, 8)}
    for p in (1, 2, 3):
        assert center[p] == pytest.approx(
            (g.box_top[2 * p] + g.h(2 * p) + g.box_top[2 * p + 1]) / 2
        )
        assert kincade.pdf.stub_y(p, g) == pytest.approx(center[p])


# ---------------------------------------------------------------- drawing


@pytest.mark.parametrize("paper", PAPERS)
def test_a_chart_draws_seven_boxes_at_the_large_print_geometry(pedigree, paper):
    g = large(paper)
    boxes = rectangles(render_large(pedigree, paper=paper))
    assert len(boxes) == 7
    for pos in range(1, 8):
        _x, _top, w, h = next(
            b
            for b in boxes
            if b[0] == approx(g.box_x0[pos])
            and b[1] == approx(g.box_top[pos] - (g.leading / 2 if pos == 1 else 0))
        )
        assert (w, h) == (
            approx(g.box_w),
            approx(g.h(pos) + (10 * SCALE if pos == 1 else 0)),
        )


@SHADOWS
@pytest.mark.parametrize("paper", PAPERS)
def test_the_drawn_right_column_runs_from_the_top_to_the_bottom_edge(
    pedigree, paper, shadow
):
    """The box outlines as drawn (paint 'B*'; the shadow layers are 'f*' and are not
    counted). Boxes 4 to 7 are the only ones whose left edge is the right column's, so
    their top and bottom are the column's.
    """
    g = large(paper, shadow)
    pdf = render_large(pedigree, paper=paper, shadow=shadow)
    outlines = [(x, top, h) for x, top, _w, h in rectangles(pdf, "B*")]
    column = [b for b in outlines if b[0] == pytest.approx(g.box_x0[4], abs=0.02)]
    assert len(outlines) == 7 and len(column) == 4
    assert min(top for _, top, _ in column) == pytest.approx(
        kincade.pdf.Y_TOP, abs=0.02
    )
    assert max(top + h for _, top, h in column) == pytest.approx(g.y_bottom, abs=0.02)


def test_only_the_numbers_1_to_7_are_drawn(pedigree):
    page = pages(render_large(pedigree))[0]
    numbers = sorted(
        r.text for r in page if r.font == "Helvetica-Bold" and r.text.isdigit()
    )
    assert numbers == ["1", "2", "3", "4", "5", "6", "7"]


def test_box_text_is_14_point_and_the_header_and_footer_are_not(pedigree):
    page = pages(render_large(pedigree))[0]
    name = next(r for r in page if r.text == "Jane ASHFORD")
    detail = next(r for r in page if r.text.startswith("b. 14 Feb 1980"))
    assert (name.font, name.size) == ("Helvetica", 14) and (
        detail.font,
        detail.size,
    ) == ("Times-Roman", 14)
    title = next(r for r in page if r.text == "Cascading Pedigree — Jane ASHFORD")
    label = next(r for r in page if r.text == "Chart 1")
    footer = next(r for r in page if r.text.startswith("Created"))
    number = next(r for r in page if r.text.startswith("Page 1 of"))
    assert (title.size, label.size, footer.size, number.size) == (16, 9, 8, 8)
    # the box numbers
    assert all(
        r.size == 14 for r in page if r.font == "Helvetica-Bold" and r.text.isdigit()
    )


def test_baselines_and_the_left_inset_scale(pedigree):
    g = large()
    page = pages(render_large(pedigree))[0]
    box1 = sorted(
        (r for r in page if r.x == approx(g.box_x0[1] + g.inset_left)),
        key=lambda r: r.y,
    )
    assert [r.text for r in box1][:3] == [
        "Jane ASHFORD",
        "b. 14 Feb 1980",
        "bp. Springfield, Illinois",
    ]
    top = g.box_top[1] - g.leading / 2
    assert box1[0].y == approx(top + g.name_base)
    assert box1[1].y == approx(top + g.name_base + g.detail_gap)
    assert box1[2].y == approx(top + g.name_base + g.detail_gap + g.leading)
    # the last line, 5 pt x 14/9 up
    assert len(box1) == 8 and box1[-1].y == approx(top + 88 * SCALE - g.bottom_pad)


def test_text_is_fitted_into_the_scaled_width():
    long_place = "Q" * 90 + " County, Kentucky"
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Root /ROOT/",
            "1 DEAT",
            "2 DATE 1 JAN 1950",
            f"2 PLAC {long_place}",
        )
    )
    g = large()
    page = pages(render_large(tree, generations=1))[0]
    run = next(r for r in page if r.text.startswith("dp."))
    assert run.text.endswith(ELLIPSIS) and 0.5 <= run.scale <= 1.0
    assert run.right() <= g.box_x0[1] + g.inset_left + g.text_w + 0.01
    assert run.right() > g.box_x0[1] + g.inset_left + g.text_w - 60


def test_box_numbers_sit_left_of_the_box_level_with_the_name_or_the_last_line(pedigree):
    g = large()
    page = pages(render_large(pedigree))[0]
    numbers = {
        r.text: r for r in page if r.font == "Helvetica-Bold" and r.text.isdigit()
    }
    for pos in range(1, 8):
        assert numbers[str(pos)].right() == approx(g.box_x0[pos] - 4 * SCALE)
    # the left zone and the right column's fathers: level with the name
    for pos in (1, 2, 3, 4, 6):
        assert numbers[str(pos)].y == approx(
            g.box_top[pos] - (g.leading / 2 if pos == 1 else 0) + g.name_base
        )
    for pos in (5, 7):  # the right column's mothers: level with the last line
        assert numbers[str(pos)].y == approx(g.box_top[pos] + g.h(pos) - g.bottom_pad)


def test_continuation_numbers_are_beside_boxes_4_to_7_in_italic_14_point(pedigree):
    g = large()
    charts = plan_charts(pedigree, "I1", None, "birth", True)
    assert charts[0].continuations
    page = pages(render_large(pedigree))[0]
    italics = [r for r in page if r.font == "Times-Italic"]
    assert sorted(int(r.text) for r in italics) == sorted(
        charts[0].continuations.values()
    )
    for pos, number in charts[0].continuations.items():
        run = next(r for r in italics if r.text == str(number))
        assert run.size == 14
        assert run.x == approx(g.box_x0[pos] + g.box_w + 5 * SCALE)
        assert run.y == approx(g.box_top[pos] + g.h(pos) / 2 + 3 * SCALE)


def test_the_continuation_subtitle_names_a_box_from_4_to_7(pedigree):
    charts = plan_charts(pedigree, "I1", None, "birth", True)
    out = pages(render_large(pedigree))
    for chart, page in zip(charts, out, strict=True):
        if chart.origin:
            pos = chart.origin[1]
            assert 4 <= pos <= 7
            sub = next(r for r in page if r.text.startswith("Number 1 on this chart"))
            assert (
                sub.text
                == f"Number 1 on this chart is the same as number {pos} on chart {chart.origin[0]}."
            )
            assert sub.y == approx(46) and sub.size == 8


def test_the_record_id_is_scaled_and_aligned_with_the_name_cap_top(pedigree):
    g = large()
    page = pages(render_large(pedigree, show_ids=True))[0]
    record = next(r for r in page if r.text == "[I1]")
    assert record.font == "Helvetica" and record.size == approx(7 * SCALE)
    assert record.right() == approx(g.box_x0[1] + g.box_w - g.inset_right, abs=0.01)
    assert record.y == approx(
        g.box_top[1] - g.leading / 2 + g.name_base - (g.size - g.id_size) * 0.718
    )
    name = next(r for r in page if r.text == "Jane ASHFORD")
    assert name.y - name.size * 0.718 == approx(record.y - record.size * 0.718)


def test_a_long_name_leaves_the_scaled_record_id_its_room():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Alexandrina Wilhelmina Fredericka Charlotte Josephine /VANDERBILT/",
        )
    )
    g = large()
    page = pages(render_large(tree, generations=1, show_ids=True))[0]
    record = next(r for r in page if r.text == "[I1]")
    name = next(r for r in page if r.text.startswith("Alexandrina"))
    assert name.right() <= record.x - g.id_gap + 0.01


def test_connectors_run_to_the_large_print_columns(pedigree):
    g = large()
    ls = lines(render_large(pedigree))
    vertical = {
        round(x1, 3) for x1, y1, x2, y2 in ls if x1 == x2 and y1 != y2 and 40 < y1 < 780
    }
    assert vertical == {30 + 18, round(73 + g.box_w + 13, 3)}  # one trunk per zone
    # where the stubs end
    children = {round(x2, 3) for x1, y1, x2, y2 in ls if y1 == y2 and x2 > x1}
    assert {73, round(g.box_x0[4], 3)} <= children


def test_nothing_is_drawn_beyond_the_page_width(pedigree):
    for paper in PAPERS:
        page = pages(render_large(pedigree, paper=paper))[0]
        width = kincade.pdf.page_geom(paper).width
        assert all(r.right() <= width for r in page)


def test_the_index_is_as_in_normal_print(pedigree):
    normal = pages(render_large(pedigree, large_print=False, index=True))
    big = pages(render_large(pedigree, large_print=True, index=True))
    first_index = next(
        i for i, page in enumerate(big) if any(r.text == "Index" for r in page)
    )
    index_page = big[first_index]
    entries = [r for r in index_page if r.font == "Times-Roman"]
    assert entries and all(r.size == kincade.pdf.INDEX_SIZE for r in entries)
    assert min(r.y for r in entries) == approx(kincade.pdf.INDEX_TOP)
    normal_index = next(page for page in normal if any(r.text == "Index" for r in page))
    placed = lambda page: [(r.font, r.size, r.x, r.y, r.scale) for r in page]
    # every run in the same place, font and size; the chart-box numbers differ
    assert placed(index_page) == placed(normal_index)


def test_page_numbers_and_the_footer_are_as_in_normal_print(pedigree):
    normal = pages(render_large(pedigree, large_print=False, generations=3))[0]
    big = pages(render_large(pedigree, generations=3))[0]
    pick = lambda page, start: next(
        (r.x, r.y, r.size) for r in page if r.text.startswith(start)
    )
    for start in ("Page 1 of", "Created", "Cascading", "Chart "):
        assert pick(normal, start)[1:] == pick(big, start)[1:]


def test_large_print_makes_more_pages(pedigree):
    normal = count_pages(render_large(pedigree, large_print=False))
    big = count_pages(render_large(pedigree))
    assert big > normal


# ---------------------------------------------------------------- planning


def test_charts_are_three_generations_deep(pedigree):
    charts = plan_charts(pedigree, "I1", None, "birth", True)
    assert all(c.depth == 3 and c.drawn == frozenset(range(1, 8)) for c in charts)
    assert all(c.slots[p] is None for c in charts for p in range(8, 16))
    # normal print: four generations
    assert all(c.depth == 4 for c in plan_charts(pedigree, "I1"))


def independent_plan(tree, root, depth, generations=None):
    """A second, naive breadth-first numbering: [(origin position, person)] per chart
    after the first.
    """

    def parents(pid):
        return tuple(x for x in tree.parent_ids(pid))

    def slots(pid):
        out = {1: pid}
        for p in range(1, 2 ** (depth - 1)):
            if out.get(p):
                out[2 * p], out[2 * p + 1] = parents(out[p])
        return out

    roots, queue, result = {root: 1}, [(root, 0)], []
    for pid, offset in queue:
        s = slots(pid)
        for pos in range(2 ** (depth - 1), 2**depth):
            person = s.get(pos)
            if not person or not any(parents(person)) or person in roots:
                continue
            gen = offset + pos.bit_length()
            if generations is not None and gen + 1 > generations:
                continue
            roots[person] = len(roots) + 1
            queue.append((person, gen - 1))
            result.append((roots[person], pos, person))
    return result


@pytest.mark.parametrize(
    "fixture", ["pedigree.ged", "collapse.ged", "deep_collapse.ged", "cycle.ged"]
)
@pytest.mark.parametrize("generations", [None, 3, 4, 5, 6])
def test_continuation_charts_start_from_boxes_4_to_7(fixture, generations):
    tree = read_gedcom(FIX / fixture)
    root = "I1"
    charts = plan_charts(tree, root, generations, "birth", True)
    assert [
        (c.number, c.origin[1], c.slots[1]) for c in charts[1:]
    ] == independent_plan(tree, root, 3, generations)
    for chart in charts:
        assert all(4 <= pos <= 7 for pos in chart.continuations)
        assert all(
            1 <= number <= len(charts) for number in chart.continuations.values()
        )
        assert all(
            charts[number - 1].slots[1] == chart.slots[pos]
            for pos, number in chart.continuations.items()
        )
    assert [c.number for c in charts] == list(range(1, len(charts) + 1))
    # a person roots at most one chart
    assert len({c.slots[1] for c in charts}) == len(charts)


def test_the_pedigree_fixture_has_continuations_from_the_right_boxes(pedigree):
    charts = plan_charts(pedigree, "I1", None, "birth", True)
    assert len(charts) > 1
    assert all(c.origin and 4 <= c.origin[1] <= 7 for c in charts[1:])
    assert {p for c in charts for p in c.continuations} <= {4, 5, 6, 7}
    # chart 1's own grandparents (boxes 4 to 7) continue
    assert charts[0].continuations


@pytest.mark.parametrize("generations", range(1, 13))
def test_generations_count_the_root_as_one_and_a_level_adds_two(generations):
    tree = chain(13)
    big = plan_charts(tree, "P0", generations, "birth", True)
    normal = plan_charts(tree, "P0", generations)
    assert len(big) == 1 + max(0, (generations - 2) // 2)
    assert len(normal) == 1 + max(0, (generations - 2) // 3)
    assert [c.offset for c in big] == [2 * k for k in range(len(big))]
    assert [c.offset for c in normal] == [3 * k for k in range(len(normal))]
    shown_big = {c.slots[p] for c in big for p in c.drawn if c.slots[p]}
    # every generation up to N, none beyond
    assert len(shown_big) == min(generations, 13)


def test_generations_limit_the_boxes_drawn_on_each_chart():
    tree = chain(13)
    chart1, chart2, chart3 = plan_charts(tree, "P0", 6, "birth", True)
    assert chart1.offset == 0 and chart1.drawn == frozenset(range(1, 8))
    # generations 3 to 5
    assert chart2.offset == 2 and chart2.drawn == frozenset(range(1, 8))
    # generations 5 and 6 only
    assert chart3.offset == 4 and chart3.drawn == frozenset({1, 2, 3})


def test_boxes_beyond_the_limit_are_not_drawn_and_their_numbers_not_set():
    tree = chain(13)
    two = plan_charts(tree, "P0", 2, "birth", True)
    assert len(two) == 1 and two[0].drawn == frozenset({1, 2, 3})
    assert two[0].slots[4] is None and not two[0].continuations
    three = plan_charts(tree, "P0", 3, "birth", True)
    assert (
        len(three) == 1
        and three[0].drawn == frozenset(range(1, 8))
        and not three[0].continuations
    )
    four = plan_charts(tree, "P0", 4, "birth", True)
    assert len(four) == 2 and four[0].continuations == {4: 2}
    assert four[1].drawn == frozenset({1, 2, 3}) and four[1].origin == (1, 4)


def test_the_cli_generations_option_works_with_large_print(tmp_path, capsys):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--large-print",
                "--generations",
                "4",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    # chart 1 and the continuations of boxes 4 to 7; normal print draws chart 1 alone
    assert "(5 charts," in capsys.readouterr().err


@pytest.mark.parametrize("generations", [2, 3, 4, 5, 6, 7, None])
def test_a_drawn_persons_privacy_does_not_depend_on_generations_in_large_print(
    generations,
):
    """The same file and rule as in normal print: the living estimate is taken from the
    unlimited plan.
    """
    tree = read_gedcom(FIX / "deep_collapse.ged")
    pdf = render_large(tree, generations=generations, exclude_private=True)
    assert b"Father DEEP" not in pdf
    assert b"(Living)" in pdf
    assert b"Akron, Ohio" not in pdf


def test_the_index_lists_the_people_in_boxes_1_to_7_only(pedigree):
    charts = plan_charts(pedigree, "I1", 3, "birth", True)
    entries = kincade.pdf.build_index(
        pedigree, charts, lambda pid: False, exclude_private=False
    )
    assert len(entries) == 7
    assert all(
        int(loc.split("-")[1]) <= 7
        for line in entries
        for loc in line.rsplit(" ", 1)[1].split(", ")
    )


def test_charts_and_options_must_agree_on_large_print(pedigree):
    normal_charts = plan_charts(pedigree, "I1")
    with pytest.raises(ValueError, match="large"):
        render_pdf(normal_charts, pedigree, Options(large_print=True))
    big_charts = plan_charts(pedigree, "I1", None, "birth", True)
    with pytest.raises(ValueError, match="large"):
        render_pdf(big_charts, pedigree, Options())


# ----------------------------------------------------------------
# the switch and the config


def test_the_cli_plans_and_renders_in_large_print(tmp_path, drawn_charts):
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--large-print",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    charts, opts = drawn_charts[-1]
    assert opts.large_print is True and all(c.depth == 3 for c in charts)
    assert (
        kincade.cli.main([str(FIX / "pedigree.ged"), "--root", "@I1@", "-o", str(out)])
        == 0
    )
    charts, opts = drawn_charts[-1]
    assert opts.large_print is False and all(c.depth == 4 for c in charts)

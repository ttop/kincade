"""The drop shadow (--shadow): three translucent layers, each 0.8 pt larger than the one
inside it, all offset 2.5 pt right and down (large print scales both by 14/9). No layer
is clipped. With shadows on the chart area makes room for them, so every shadow is drawn
in full, ends 6 pt above the footer text, and stays inside the right margin. Nothing is
drawn without --shadow, and the layout is the plain one.

Synthetic fixtures only.
"""

import pytest
from reportlab.pdfbase import pdfmetrics

import kincade.charts
import kincade.gedcom
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import FIX, PAPERS, PRINTS, TODAY, approx, full_chart
from pdfread import ink_box, overlaps, pages, rectangles

SCALE = 14 / 9
FOOTER_GAP = 6  # a shadow ends at least this far above the footer text


def footer_baseline(pdf):
    """The footer's baseline, y from the page top: the 'Created' line (the page number
    shares it).
    """
    return next(r.y for r in pages(pdf)[0] if r.text.startswith("Created"))


def assert_layers(layers, expected):
    assert len(layers) == len(expected)
    for got, want in zip(layers, expected, strict=True):
        assert len(got) == 4
        for a, b in zip(got, want, strict=True):
            assert a == approx(b)


def layers_by_box(pdf):
    """The shadow layers of each box, in the order the boxes are drawn: [(box, [layer,
    ...]), ...], innermost layer first. Each box's layers are drawn just before its
    outline, so they pair up by position.
    """
    boxes = rectangles(pdf, "B*")
    layers = rectangles(pdf, "f*")
    assert len(layers) == kincade.pdf.SHADOW_LAYERS * len(boxes)
    per = kincade.pdf.SHADOW_LAYERS
    return [(box, layers[i * per : (i + 1) * per]) for i, box in enumerate(boxes)]


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
def test_every_shadow_is_drawn_in_full(paper, large_print):
    """Each layer is the box moved 2.5 pt right and down (scaled for large print), grown
    0.8 pt per layer on every side. A clipped layer would be smaller, so this checks
    that none is.
    """
    pdf = full_chart(large_print, paper=paper, shadow=True)
    s = SCALE if large_print else 1.0
    drawn = layers_by_box(pdf)
    assert len(drawn) == (7 if large_print else 15)
    for (bx, btop, bw, bh), layers in drawn:
        for i, (x, top, w, h) in enumerate(layers):
            grow = i * 0.8 * s
            assert x == approx(bx + 2.5 * s - grow)
            assert top == approx(btop + 2.5 * s - grow)
            # same size relative to its box, layer by layer
            assert w == approx(bw + 2 * grow)
            assert h == approx(bh + 2 * grow)


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
def test_every_shadow_clears_the_footer_and_the_right_margin(paper, large_print):
    pdf = full_chart(large_print, paper=paper, shadow=True)
    geom = kincade.pdf.page_geom(paper, large_print, shadow=True)
    footer_top = footer_baseline(pdf) - pdfmetrics.getAscent(
        "Helvetica", kincade.pdf.FOOTER_SIZE
    )
    for _, layers in layers_by_box(pdf):
        for x, top, w, h in layers:
            # 6 pt above the footer text's top
            assert top + h <= footer_top - FOOTER_GAP + 0.02
            assert x + w <= geom.right + 0.02  # inside the right margin
            assert x >= 0


@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
def test_no_shadow_layers_without_the_flag_and_the_plain_layout(large_print):
    pdf = full_chart(large_print, shadow=False)
    assert rectangles(pdf, "f*") == []
    geom = kincade.pdf.page_geom("letter", large_print)
    expected = [
        (
            geom.box_x0[p],
            geom.box_top[p] - (10 if p == 1 and not large_print else 0),
            geom.box_w,
            geom.h(p) + (10 * geom.scale if p == 1 else 0),
        )
        for p in range(1, 2**geom.gens)
    ]
    assert rectangles(pdf, "B*") == [tuple(approx(v) for v in box) for box in expected]


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("large_print", [False, True], ids=["normal", "large"])
def test_the_chart_area_makes_room_for_the_shadow_reach(paper, large_print):
    plain = kincade.pdf.page_geom(paper, large_print)
    shadowed = kincade.pdf.page_geom(paper, large_print, shadow=True)
    reach = kincade.pdf.shadow_reach(large_print)
    assert shadowed.y_bottom == approx(plain.y_bottom - reach)
    boxes = range(1, 2**shadowed.gens)
    assert (
        max(shadowed.box_top[p] + shadowed.h(p) for p in boxes)
        <= shadowed.y_bottom + 1e-9
    )
    right = max(shadowed.box_x0[p] + shadowed.box_w for p in boxes)
    plain_right = max(plain.box_x0[p] + plain.box_w for p in boxes)
    assert right + reach <= shadowed.right + 1e-9  # every shadow clears the margin
    # narrower only where the margin needs it
    assert right == approx(min(plain_right, plain.right - reach))


def test_a4_normal_print_narrows_the_columns_only_as_far_as_the_margin_needs():
    geom = kincade.pdf.page_geom("a4", False, shadow=True)
    # 0.41 pt less than Letter's 215: A4's margin is only 3.28 pt past the column, so
    # the right edge moves in 0.82 pt to clear the 4.1 pt shadow, and a box loses half
    assert geom.box_w == approx(214.59)
    assert geom.box_x0[8] + geom.box_w == approx(
        595.28 - 19 - kincade.pdf.shadow_reach()
    )
    letter = kincade.pdf.page_geom("letter", False, shadow=True)
    # the margin has room on Letter
    assert letter.box_w == kincade.pdf.BOX_W and letter.box_x0 == kincade.pdf.BOX_X0


def test_shadow_reach_is_offset_plus_outer_growth_scaled_for_large_print():
    assert kincade.pdf.shadow_reach() == approx(2.5 + 2 * 0.8)
    assert kincade.pdf.shadow_reach(True) == approx((2.5 + 2 * 0.8) * SCALE)


def test_normal_print_layers_are_offset_and_grow_0_8_points_each():
    geom = kincade.pdf.page_geom("letter")
    # a box at (116, 100), 58 pt tall, 215 wide
    layers = kincade.pdf.shadow_layers(116, 100, 58, geom)
    assert_layers(
        layers,
        [
            (118.5, 102.5, 215, 58),
            (117.7, 101.7, 216.6, 59.6),
            (116.9, 100.9, 218.2, 61.2),
        ],
    )


def test_large_print_layers_scale_offset_and_growth_by_14_over_9():
    geom = kincade.pdf.page_geom("letter", True)
    layers = kincade.pdf.shadow_layers(116, 100, 90, geom)
    s, w = SCALE, geom.box_w
    expected = [
        (116 + 2.5 * s - g, 100 + 2.5 * s - g, w + 2 * g, 90 + 2 * g)
        for g in (0, 0.8 * s, 1.6 * s)
    ]
    assert_layers(layers, expected)


# ---- continuation numbers beyond the drop shadow


def continuation_runs(pdf, geom, charts):
    """Each continuation number of chart 1 as (box, number, run), located at its box's
    center line + 3 (scaled).
    """
    found = []
    for pos, number in charts[0].continuations.items():
        y = geom.box_top[pos] + geom.h(pos) / 2 + 3 * geom.scale
        run = [
            r
            for r in pages(pdf)[0]
            if r.font == "Times-Italic" and r.text == str(number) and r.y == approx(y)
        ]
        assert len(run) == 1, f"no continuation number {number} beside box {pos}"
        found.append((pos, number, run[0]))
    return found


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_with_shadow_each_continuation_number_starts_beyond_the_shadow(
    paper, large_print, pedigree
):
    charts = plan_charts(pedigree, "I1", None, "birth", large_print)
    # precondition: chart 1 has continuation numbers beside the right-column boxes
    assert charts[0].continuations
    pdf = render_pdf(
        charts,
        pedigree,
        Options(
            large_print=large_print,
            paper=paper,
            shadow=True,
            fonts="base14",
            compress=False,
            index=False,
            today=TODAY,
        ),
    )
    geom = kincade.pdf.page_geom(paper, large_print, shadow=True)
    reach = kincade.pdf.shadow_reach(large_print)
    for pos, _, run in continuation_runs(pdf, geom, charts):
        x1 = geom.box_x0[pos] + geom.box_w
        # starts beyond the shadow, with the gap
        assert run.x >= x1 + reach + 5 * geom.scale - 0.02
        assert run.x == approx(x1 + reach + 5 * geom.scale)
        assert run.right() <= geom.width - 6 + 0.02  # and ends inside the page edge


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_with_shadow_no_continuation_number_overlaps_a_shadow(
    paper, large_print, pedigree
):
    charts = plan_charts(pedigree, "I1", None, "birth", large_print)
    pdf = render_pdf(
        charts,
        pedigree,
        Options(
            large_print=large_print,
            paper=paper,
            shadow=True,
            fonts="base14",
            compress=False,
            index=False,
            today=TODAY,
        ),
    )
    geom = kincade.pdf.page_geom(paper, large_print, shadow=True)
    layers = rectangles(pdf, "f*")
    assert layers
    for _, number, run in continuation_runs(pdf, geom, charts):
        assert not [layer for layer in layers if overlaps(ink_box(run), layer)], (
            f"{number} is on a shadow"
        )


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
def test_without_shadow_the_continuation_number_keeps_the_plain_gap(
    paper, large_print, pedigree
):
    charts = plan_charts(pedigree, "I1", None, "birth", large_print)
    pdf = render_pdf(
        charts,
        pedigree,
        Options(
            large_print=large_print,
            paper=paper,
            fonts="base14",
            compress=False,
            index=False,
            today=TODAY,
        ),
    )
    geom = kincade.pdf.page_geom(paper, large_print)
    for pos, _, run in continuation_runs(pdf, geom, charts):
        x1 = geom.box_x0[pos] + geom.box_w
        # 5 pt, or 5 x 14/9 in large print; no shadow reach
        assert run.x == approx(x1 + 5 * geom.scale)


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("number", ["2", "10"])
def test_with_shadow_a_short_continuation_number_starts_at_the_gap_and_ends_inside_the_edge(
    paper, number
):
    """A one- or two-digit number starts at the box's right edge + shadow reach + 5 pt,
    whatever the paper.
    """
    tree = read_gedcom(FIX / "pedigree.ged")
    charts = plan_charts(tree, "I1", 4)
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
            shadow=True,
        ),
    )
    geom = kincade.pdf.page_geom(paper, False, shadow=True)
    run = [
        r
        for r in pages(pdf)[0]
        if r.font == "Times-Italic"
        and r.text == number
        and r.y == approx(geom.box_top[8] + geom.h(8) / 2 + 3)
    ]
    assert len(run) == 1
    assert run[0].x == approx(
        geom.box_x0[8] + geom.box_w + kincade.pdf.shadow_reach() + 5
    )
    # any squeeze keeps it inside the edge
    assert run[0].right() <= geom.width - 6 + 0.02


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("number", ["7", "1000", "99999"])
def test_with_shadow_a_long_continuation_number_keeps_every_digit_inside_the_edge(
    paper, large_print, number, pedigree
):
    """A number too wide for the room is condensed (to half width at least), then moved
    left to end 6 pt inside the page edge. Every digit is drawn."""
    charts = plan_charts(pedigree, "I1", None, "birth", large_print)
    for pos in charts[0].continuations:
        charts[0].continuations[pos] = int(number)
    pdf = render_pdf(
        charts,
        pedigree,
        Options(
            large_print=large_print,
            paper=paper,
            shadow=True,
            fonts="base14",
            compress=False,
            index=False,
            today=TODAY,
        ),
    )
    geom = kincade.pdf.page_geom(paper, large_print, shadow=True)
    for _, _, run in continuation_runs(pdf, geom, charts):
        assert run.text == number and 0.5 <= run.scale <= 1.0
        assert run.right() <= geom.width - 6 + 0.02

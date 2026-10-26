"""The pedigree PDF, read with pdfread: layout, continuations, parent choice, the root
box, record IDs, places, the index, text fitting, event stand-ins and names.
"""

import itertools
import random
import re

import pytest
from reportlab.pdfbase import pdfmetrics

import kincade
import kincade.charts
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.model import Date, Day, Event, Family, ParentLink, Person, Tree
from kincade.pdf import Options, render_pdf

from conftest import (
    FIX,
    KID,
    PAPERS,
    PRINTS,
    TODAY,
    approx,
    full_pedigree,
    ged,
    indi,
    kid_tree,
    render,
    render_charts,
)
from pdfread import (
    count_pages,
    drawn,
    ink_box,
    overlaps,
    pages,
    rectangles,
    runs,
    streams,
)
from pdfread import lines as pdf_lines

# ---------------------------------------------------------------- helpers


def line_of(n, through_mothers=False):
    """P0, then one known parent per generation, n people in all: a single line that
    runs out at the end.
    """
    lines = ["0 HEAD"]
    for i in range(n):
        lines += [f"0 @P{i}@ INDI", f"1 NAME P{i} /LINE/"] + (
            [f"1 FAMC @F{i}@"] if i + 1 < n else []
        )
    for i in range(n - 1):
        lines += [
            f"0 @F{i}@ FAM",
            f"1 {'WIFE' if through_mothers else 'HUSB'} @P{i + 1}@",
            f"1 CHIL @P{i}@",
        ]
    return read_gedcom(ged(*lines))


def full_tree(generations):
    """Every ancestor known to the given generation: person k has parents 2k and 2k+1
    (Ahnentafel numbers).
    """
    last = 2**generations
    lines = ["0 HEAD"]
    for k in range(1, last):
        lines += [f"0 @A{k}@ INDI", f"1 NAME A{k} /FULL/"] + (
            [f"1 FAMC @G{k}@"] if 2 * k + 1 < last else []
        )
    for k in range(1, last // 2):
        lines += [
            f"0 @G{k}@ FAM",
            f"1 HUSB @A{2 * k}@",
            f"1 WIFE @A{2 * k + 1}@",
            f"1 CHIL @A{k}@",
        ]
    return read_gedcom(ged(*lines))


def nearby(rng, i, people):
    """A person among the next dozen after person i: the parent of i."""
    return f"@R{rng.randrange(i + 1, min(people, i + 13))}@"


def random_tree(seed, people=90):
    """Parents are drawn from the next dozen people, so lines run out at different
    depths, ancestors are shared (the pedigree collapses), one parent is often missing,
    and some people also have an adopted family listed first.
    """
    rng = random.Random(seed)
    lines = ["0 HEAD"]
    fams = []
    for i in range(people):
        lines += [f"0 @R{i}@ INDI", f"1 NAME R{i} /RANDOM/"]
        for kind in ("adopted", "birth") if rng.random() < 0.15 else ("birth",):
            if i + 1 >= people or rng.random() < 0.15:
                continue
            fid = f"@F{len(fams)}@"
            father, mother = (
                nearby(rng, i, people) if rng.random() < 0.8 else None for _ in range(2)
            )
            if father == mother:
                mother = None
            fams.append((fid, father, mother, i))
            lines += [f"1 FAMC {fid}"] + (
                [f"2 PEDI {kind}"] if kind == "adopted" else []
            )
    for fid, father, mother, child in fams:
        lines += (
            [f"0 {fid} FAM"]
            + ([f"1 HUSB {father}"] if father else [])
            + ([f"1 WIFE {mother}"] if mother else [])
        )
        lines += [f"1 CHIL @R{child}@"]
    return read_gedcom(ged(*lines))


TREES = {
    name: read_gedcom(FIX / f"{name}.ged")
    for name in ("pedigree", "collapse", "cycle", "deep_collapse", "quirks")
}
TREES |= {
    "line of fathers": line_of(14),
    "line of mothers": line_of(14, True),
    "full tree": full_tree(7),
    **{f"random {seed}": random_tree(seed) for seed in (1, 2, 3)},
}


def guarantee(tree, root, generations, large_print, parents):
    """Every violation of the --generations guarantee in the charts planned for this
    root, as texts (none: it holds).
    """
    problems = []
    charts = plan_charts(tree, root, generations, parents, large_print)
    depth = kincade.charts.page_depth(large_print)
    by_number = {chart.number: chart for chart in charts}
    assert [chart.number for chart in charts] == list(range(1, len(charts) + 1))
    for chart in charts:
        where = (
            f"{root} N={generations} large={large_print} {parents} chart {chart.number}"
        )
        shown = {
            pos
            for pos in range(1, 2**depth)
            if kincade.pdf._shown(chart, pos, empty_boxes=True)
        }
        every = set(range(1, 2**depth))
        if shown != every & chart.drawn:
            problems.append(
                f"{where}: drawn {sorted(chart.drawn)} but shows {sorted(shown)}"
            )
        for pos in sorted(shown):  # no box beyond generation N
            if (
                generations is not None
                and chart.offset + kincade.charts.box_generation(pos) > generations
            ):
                problems.append(
                    f"{where}: box {pos} is generation "
                    f"{chart.offset + kincade.charts.box_generation(pos)}"
                )
        for pos, person in chart.slots.items():
            if person is not None and pos not in shown:
                problems.append(f"{where}: box {pos} holds {person} but is not drawn")
        if chart.number != 1:
            if not any(chart.slots[pos] for pos in (2, 3)):
                problems.append(f"{where}: boxes 2 and 3 are both empty")
            if not {2, 3} & shown:
                problems.append(f"{where}: boxes 2 and 3 are not drawn")
        for pos, number in chart.continuations.items():
            target = by_number.get(number)
            if (
                pos not in shown
                or pos < 2 ** (depth - 1)
                or not target
                or target.slots[1] != chart.slots[pos]
            ):
                problems.append(
                    f"{where}: continuation {pos} -> {number} is not the person's own "
                    "chart"
                )
    return problems


# a place with a home country (USA) and enough parts to need shortening
LONG = "Springfield, Greene County, Northern Missouri, Western Region, USA"
HOME_GED = ged(
    "0 @I1@ INDI",
    "1 NAME Root /ROOT/",
    "1 BIRT",
    f"2 PLAC {LONG}",
    "1 FAMC @F1@",
    "0 @I2@ INDI",
    "1 NAME Dad /ROOT/",
    "1 BIRT",
    "2 PLAC Ohio, USA",
    "0 @I3@ INDI",
    "1 NAME Mum /ROOT/",
    "1 BIRT",
    "2 PLAC Kent, USA",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 WIFE @I3@",
)


# ---------------------------------------------------------------- the fixture itself


def test_the_pedigree_fixture_document(pedigree):
    pdf = render(pedigree)
    assert count_pages(pdf) == 7
    for text in (
        b"(Jane ASHFORD)",
        b"(b. 14 Feb 1980)",
        b"(bp. Springfield, Illinois)",
        b"(m. 12 Jun 1975)",
        b"(Cascading Pedigree \\227 Jane ASHFORD)",
        b"(Chart 1)",
        b"(Created 10 Oct 2026 using Kincade)",
        b"(Page 1 of 7)",
        b"(Index)",
        b"(ASHFORD, Jane \\(b. 1980\\), 1-1)",
    ):
        assert text in pdf, text
    assert b"(m. 12 Jun 1975)" in pdf and b"(mp. Akron, Ohio)" in pdf
    first_page_runs = pages(pdf)[0]
    numbers = {int(r.text) for r in first_page_runs if r.text.isdigit()}
    # continuation numbers sit beside the last-column boxes
    assert numbers >= {8, 9, 10, 11, 12, 13, 14, 15}


# ---------------------------------------------------------------- layout invariants

LAYOUT_CASES = [
    ("letter", False, False),
    ("a4", False, True),
    ("letter", True, True),
    ("a4", True, False),
]


def _box_number_runs(page_runs, geom):
    return {
        int(r.text): r
        for r in page_runs
        if r.font == "Helvetica-Bold" and r.size == geom.size and r.text.isdigit()
    }


def _continuation_runs(page_runs, geom, continuations):
    found = {}
    for pos, number in continuations.items():
        y = approx(geom.box_top[pos] + geom.h(pos) / 2 + 3 * geom.scale)
        match = [
            r
            for r in page_runs
            if r.font == "Times-Italic" and r.text == str(number) and r.y == y
        ]
        assert len(match) == 1, (pos, number)
        found[pos] = match[0]
    return found


@pytest.mark.parametrize(
    "paper,large_print,shadow",
    LAYOUT_CASES,
    ids=[
        "letter-normal-plain",
        "a4-normal-shadow",
        "letter-large-shadow",
        "a4-large-plain",
    ],
)
def test_layout_invariants(paper, large_print, shadow):
    """Every chart page of a tree with no gaps, deep enough that every last-column box
    continues, keeps the same invariants of position, text and margins.
    """
    depth = kincade.charts.page_depth(large_print)
    tree = full_pedigree(depth + 1)
    charts = plan_charts(tree, "I1", None, "birth", large_print)
    last_column = range(2 ** (depth - 1), 2**depth)
    assert len(charts) == 1 + len(last_column)  # every last-column box continues
    pdf = render_charts(
        tree, "I1", None, paper=paper, large_print=large_print, shadow=shadow
    )
    geom = kincade.pdf.page_geom(paper, large_print, shadow)
    per_page = pages(pdf)
    assert count_pages(pdf) == len(charts)

    positions = list(range(1, 2**geom.gens))

    def box_rect(pos, root_chart):
        # chart 1's box 1 reserves an extra spouse row; every other box is plain
        top, height = geom.box_top[pos], geom.h(pos)
        if pos == 1 and root_chart:
            top, height = top - geom.leading / 2, height + geom.leading
        return (geom.box_x0[pos], top, geom.box_w, height)

    for pos in positions:
        assert kincade.pdf.stub_y(pos, geom) == approx(
            geom.box_top[pos] + geom.h(pos) / 2
        ), pos  # connectors meet every box at its vertical centre

    for page_index, chart in enumerate(charts):
        boxes = rectangles(pdf, "B*", page_index)
        expected_boxes = [box_rect(p, page_index == 0) for p in positions]
        assert boxes == [tuple(approx(v) for v in box) for box in expected_boxes], (
            page_index
        )
        for a, b in itertools.combinations(boxes, 2):
            assert not overlaps(a, b), (page_index, a, b)
            # inside the page and the margins
        for x, top, w, h in boxes:
            assert x >= 0 and top >= 0
            assert x + w <= geom.width + 0.02 and top + h <= geom.height + 0.02

        page_runs = per_page[page_index]
        # box text starts 5 pt in and ends 3 pt short of the edge (scaled)
        found_text_in_a_box = False
        for x, top, w, h in boxes:
            for r in page_runs:
                if top - 1 <= r.y <= top + h + 1 and x - 1 <= r.x <= x + w + 1:
                    found_text_in_a_box = True
                    assert r.x >= x + geom.inset_left - 0.02, (page_index, r)
                    assert r.right() <= x + w - geom.inset_right + 0.02, (page_index, r)
        assert found_text_in_a_box, page_index

        if shadow:
            shadow_layers = rectangles(pdf, "f*", page_index)
            assert len(shadow_layers) == kincade.pdf.SHADOW_LAYERS * len(boxes)
            footer_top = next(
                r.y for r in page_runs if r.text.startswith("Created")
            ) - pdfmetrics.getAscent("Helvetica", kincade.pdf.FOOTER_SIZE)
            for x, top, w, h in shadow_layers:
                # shadows are drawn in full and clear the footer and the right margin
                assert top + h <= footer_top - 6 + 0.02, page_index
                assert x + w <= geom.right + 0.02, page_index
                assert x >= -1e-6, page_index
        else:
            assert rectangles(pdf, "f*", page_index) == []

        # box numbers end 4 pt left of their box, and touch no box or connector
        numbers = _box_number_runs(page_runs, geom)
        assert sorted(numbers) == positions, page_index
        obstacles = boxes + (shadow_layers if shadow else [])
        for pos, run in numbers.items():
            assert run.right() == approx(geom.box_x0[pos] - 4 * geom.scale), (
                page_index,
                pos,
            )
            box = ink_box(run)
            hit = [o for o in obstacles if overlaps(box, o)]
            assert not hit, (page_index, pos, hit)

        # continuation numbers: every digit inside the right edge, past any shadow
        reach = kincade.pdf.shadow_reach(large_print) if shadow else 0.0
        for pos, run in _continuation_runs(
            page_runs, geom, chart.continuations
        ).items():
            x1 = geom.box_x0[pos] + geom.box_w
            assert run.x == approx(x1 + reach + 5 * geom.scale), (page_index, pos)
            assert run.right() <= geom.width - 6 + 0.02, (page_index, pos)
            if shadow:
                assert not [s for s in shadow_layers if overlaps(ink_box(run), s)], (
                    page_index,
                    pos,
                )

        # header and footer keep their margins and overlap no box
        label = next(r for r in page_runs if r.text.startswith("Chart"))
        footer = next(r for r in page_runs if r.text.startswith("Created"))
        assert label.right() <= geom.width - 18.5 + 0.02, page_index
        assert footer.x + kincade.pdf.text_width(
            footer.text, "Helvetica", kincade.pdf.FOOTER_SIZE
        ) == approx(geom.width - 19.5), page_index
        for box in boxes:
            assert not overlaps(ink_box(label), box), page_index
            assert not overlaps(ink_box(footer), box), page_index

    if large_print:
        scale = 14 / 9
        assert geom.size == 14
        assert geom.name_base == approx(kincade.pdf.NAME_BASE * scale)
        assert geom.leading == approx(kincade.pdf.LEADING * scale)
        assert geom.inset_left == approx(kincade.pdf.TEXT_INSET_LEFT * scale)
        assert geom.inset_right == approx(kincade.pdf.TEXT_INSET_RIGHT * scale)
    else:
        assert geom.size == 9


# ---------------------------------------------------------------- generations and pages


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
def test_generations_limit_the_plan_and_the_pages(large_print):
    """Every root of every synthetic tree, for every generations limit and both parent
    modes, obeys the --generations guarantee, and the PDF's box outlines match the
    plan's shown boxes.
    """
    limits = [None, *range(1, 10)]
    modes = ["birth", "adoptive"]
    problems = [
        problem
        for name, tree in TREES.items()
        for root, generations, parents in itertools.product(tree.people, limits, modes)
        for problem in guarantee(tree, root, generations, large_print, parents)
    ]
    assert problems == []

    # the generated trees are varied enough to mean something (not vacuous)
    most = max(
        len(plan_charts(tree, root, None))
        for name, tree in TREES.items()
        if name.startswith("random")
        for root in tree.people
    )
    assert most >= 5  # long, branching pedigrees
    shared = max(
        len(chart.continuations) - len(set(chart.continuations.values()))
        for tree in TREES.values()
        for root in tree.people
        for chart in plan_charts(tree, root, None)
    )
    assert shared >= 1  # pedigree collapse: two boxes continue on the same chart
    adopted = TREES["random 1"]
    assert any(
        plan_charts(adopted, root, None, "birth")[0].slots
        != plan_charts(adopted, root, None, "adoptive")[0].slots
        for root in adopted.people
    )

    # the PDF shows exactly the boxes the plan shows, with and without --no-empty
    pedigree = TREES["pedigree"]
    for generations in limits:
        for no_empty in (False, True):
            charts = plan_charts(pedigree, "I1", generations, "birth", large_print)
            pdf = render_pdf(
                charts,
                pedigree,
                Options(
                    large_print=large_print,
                    empty_boxes=not no_empty,
                    index=False,
                    fonts="base14",
                    compress=False,
                    today=TODAY,
                ),
            )
            assert len(streams(pdf)) == len(charts)
            for page, chart in enumerate(charts):
                outlines = len(rectangles(pdf, "B*", page))
                assert outlines == sum(
                    1
                    for pos in range(1, 2**chart.depth)
                    if kincade.pdf._shown(chart, pos, empty_boxes=not no_empty)
                ), (generations, no_empty, page)

    # the 14-person line: continuation offsets match the chart's known generations
    step = 2 if large_print else 3
    line = TREES["line of fathers"]
    for generations in [None, *range(1, 16)]:
        limit = generations if generations is not None else 99
        charts = plan_charts(line, "P0", generations, "birth", large_print)
        wanted = [
            k for k in range(1, 14) if step * k + 2 <= limit and step * k + 1 <= 13
        ]
        assert [chart.offset for chart in charts] == [0] + [step * k for k in wanted], (
            generations
        )


# ---------------------------------------------------------------- continuation charts


def chain_tree(depth, line="father", step=False, union_first=True):
    """A chain p0 -> p1 -> ... -> x -> d, each the father of the one before
    (`line="father"`) or the mother. x roots a continuation chart via two unions: F
    (married 1930 in Xville, the parents of the person just below x) and Z (married
    1950 in Zville), listed first unless `union_first` is false. With `step` the F
    partner is a step-parent."""
    people, families = {}, {}
    names = [f"p{i}" for i in range(depth - 1)] + ["x"]
    for i, child in enumerate(names[:-1]):
        last = i == depth - 2
        mine, other = ("father", "mother") if line == "father" else ("mother", "father")
        link = ParentLink(f"f{i}", **{other: "step"} if last and step else {})
        people[child] = Person(
            child,
            given=child,
            surname="Pell",
            parents=[link],
            families=[f"f{i - 1}"] if i else [],
        )
        families[f"f{i}"] = Family(
            f"f{i}",
            **{mine: names[i + 1], other: f"other{i}"},
            children=[child],
            marriage=Event(Date("exact", Day(1930)), "Xville") if last else None,
        )
        people[f"other{i}"] = Person(f"other{i}", given=f"other{i}", surname="Pell")
    last_union = f"f{depth - 2}"
    people["x"] = Person(
        "x",
        given="x",
        surname="Pell",
        parents=[ParentLink("fx")],
        families=[last_union, "fz"] if union_first else ["fz", last_union],
    )
    people["d"] = Person("d", given="d", surname="Pell")
    people["z"] = Person("z", given="z", surname="Pell")
    families["fx"] = Family("fx", father="d", children=["x"])
    families["fz"] = Family(
        "fz", father="x", mother="z", marriage=Event(Date("exact", Day(1950)), "Zville")
    )
    return Tree(people, families)


def marriages(pdf):
    return [t for t in drawn(pdf) if t.startswith(("m. ", "mp. "))]


def test_continuation_charts_and_their_notes(pedigree):
    """collapse.ged: a person reached twice in the last column has one continuation
    chart, from the first box. A built tree shows that chart 2's box 1 shows the
    marriage box 1 showed for those parents, a step marriage left out of chart 1 is left
    out of chart 2 too, and adoptive mode chooses the family the continuation came from.
    The pedigree fixture carries the continuation note.
    """
    collapse = read_gedcom(FIX / "collapse.ged")
    charts = plan_charts(collapse, "I1")
    # I8 (Old) sits at positions 8 and 12: one continuation chart, from the first box
    assert charts[0].slots[8] == charts[0].slots[12] == "I8"
    assert charts[0].continuations[8] == charts[0].continuations[12]
    (chart2_number,) = {charts[0].continuations[8]}
    chart2 = next(c for c in charts if c.number == chart2_number)
    assert chart2.slots[1] == "I8"

    # chart 2 shows the marriage chart 1 showed for the parents it came from, and a
    # step marriage left out of chart 1 is left out of chart 2 too
    tree = chain_tree(4, "father", step=False, union_first=True)
    assert [c.slots[1] for c in plan_charts(tree, "p0")] == ["p0", "x"]
    assert marriages(render_charts(tree, "p0")) == [
        "m. 1930",
        "mp. Xville",
        "m. 1930",
        "mp. Xville",
    ]
    stepped = chain_tree(4, "father", step=True, union_first=True)
    assert marriages(render_charts(stepped, "p0")) == []

    # adoptive mode chooses the family the continuation came from
    adoptive_tree = chain_tree(4, "father", step=False, union_first=True)
    adoptive_tree.people["p2"].parents = [
        ParentLink("f2"),
        ParentLink("fa", "adopted", "adopted"),
    ]
    adoptive_tree.families["fa"] = Family(
        "fa",
        father="x",
        mother="amy",
        children=["p2"],
        marriage=Event(Date("exact", Day(1940))),
    )
    adoptive_tree.people["amy"] = Person(
        "amy", given="Amy", surname="Pell", families=["fa"]
    )
    adoptive_tree.people["x"].families = ["fz", "f2", "fa"]
    assert marriages(render_charts(adoptive_tree, "p0")) == [
        "m. 1930",
        "mp. Xville",
        "m. 1930",
        "mp. Xville",
    ]
    assert marriages(render_charts(adoptive_tree, "p0", adoptive_parents=True)) == [
        "m. 1940",
        "m. 1940",
    ]

    # the pedigree fixture at generations=5 shows the continuation note
    note = "Number 1 on this chart is the same as number 8 on chart 1."
    text = drawn(render(pedigree, generations=5))
    assert text.count(note) == 1
    english = "Ancestry continues on the chart numbered in the last column."
    assert drawn(render(pedigree, generations=5)).count(english) == 1
    assert english not in drawn(render(pedigree, generations=4))  # no continuations
    # the note is on chart 1 only, and overlaps no box
    chart1 = render_charts(pedigree, "I1", 5)
    note_run = next(r for r in runs(chart1) if r.text == english)
    boxes = rectangles(chart1, "B*")
    assert not [b for b in boxes if overlaps(ink_box(note_run), b)]
    # a chart_note too long for the subtitle's room is fitted with the ellipsis, and
    # stays left of the boxes just as the normal-length note does
    long_note_pdf = render_charts(pedigree, "I1", 5, lang={"chart_note": "XY " * 200})
    long_note_run = next(r for r in runs(long_note_pdf) if r.text.startswith("XY"))
    assert long_note_run.text.endswith("…")
    long_note_boxes = rectangles(long_note_pdf, "B*")
    assert not [b for b in long_note_boxes if overlaps(ink_box(long_note_run), b)]
    # likewise a continuation chart's own subtitle (the "Number N on this chart..."
    # note, via a language override)
    long_cont_pdf = render_charts(
        pedigree, "I1", 5, lang={"continuation": "QR {pos} {chart} " + "ZZ " * 200}
    )
    long_cont_runs = [r for r in runs(long_cont_pdf) if r.text.startswith("QR")]
    assert long_cont_runs
    long_cont_boxes = rectangles(long_cont_pdf, "B*")
    for run in long_cont_runs:
        assert run.text.endswith("…")
        assert not [b for b in long_cont_boxes if overlaps(ink_box(run), b)]
    # an empty note turns it off, and everything else draws the same
    plain = runs(render(pedigree, generations=5))
    off = runs(render(pedigree, generations=5, lang={"chart_note": ""}))
    assert not any(r.text == english for r in off)
    assert off == [r for r in plain if r.text != english]


# ---------------------------------------------------------------- large print continuations


def test_large_print_continues_from_boxes_4_to_7(pedigree):
    large = {"large_print": True}
    charts = plan_charts(pedigree, "I1", None, "birth", True)
    assert charts[0].depth == 3
    known = {pos for pos, pid in charts[0].slots.items() if pid}
    assert known and known <= set(range(1, 8))  # only boxes 1-7 are known
    # continuation charts start from boxes 4 to 7, and the subtitle names such a box
    assert set(charts[0].continuations) <= {4, 5, 6, 7}
    assert charts[0].continuations  # some exist on the fixture
    # the index lists boxes 1-7 only
    lines = kincade.pdf.build_index(
        pedigree, [charts[0]], lambda pid: False, exclude_private=False
    )
    chart_numbers = {
        int(loc.split("-")[1]) for line in lines for loc in [line.split(", ")[-1]]
    }
    assert chart_numbers <= set(range(1, 8))
    # large print makes more pages than normal print at the same generations
    normal_pages = count_pages(render(pedigree, generations=4))
    large_pages = count_pages(render(pedigree, generations=4, **large))
    assert large_pages > normal_pages


# ---------------------------------------------------------------- parent choice


@pytest.mark.parametrize("prefer", ["birth", "adoptive"])
def test_the_parents_drawn(prefer):
    """Birth mode takes the first birth family, else the first; adoptive mode takes
    adopted, then foster, then birth. The relationship note follows the chosen family.
    A step-parent's box is empty, with no marriage, and no birth-father-plus-stepmother
    marriage in the father's box. The index and a continuation chart use the mode too.
    """
    F1, F2 = "F1", "F2"
    # birth beats an adopted family listed first; adoptive prefers adopted whatever
    # the order
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    chosen = tree.parent_family(KID, prefer).id
    assert chosen == (F2 if prefer == "birth" else F1)
    # adoptive mode prefers a foster family over a birth family, with no adopted family
    foster_tree = kid_tree([(F1, "foster"), (F2, "")])
    foster_chosen = foster_tree.parent_family(KID, prefer).id
    assert foster_chosen == (F2 if prefer == "birth" else F1)
    # the note follows the chosen family
    text = drawn(render_charts(tree, parents=prefer))
    assert ("Kid KID (adopted)" in text) == (prefer == "adoptive")
    # the marriage line is the chosen family's
    text2 = drawn(render_charts(tree, generations=2, parents=prefer))
    assert ("m. 1960" in text2) == (prefer == "birth")
    assert ("m. 1950" in text2) == (prefer == "adoptive")
    # the index lists the chosen parents
    lines = kincade.pdf.build_index(
        tree,
        plan_charts(tree, KID, 2, prefer),
        lambda pid: False,
        exclude_private=False,
    )
    heads = [line.split(",")[0] for line in lines]
    assert heads == (
        ["KID", "TWO", "TWO"] if prefer == "birth" else ["KID", "ONE", "ONE"]
    )

    # a step-parent is never placed in a box: it is numbered with empty_boxes and left
    # out without them; no step marriage and no birth-father-plus-stepmother marriage
    step_ged = ged(
        "0 @I1@ INDI",
        "1 NAME Tom /PELL/",
        "1 FAMC @F1@",
        "0 @I2@ INDI",
        "1 NAME John /PELL/",  # the stepfather
        "0 @I3@ INDI",
        "1 NAME Mary /PELL/",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
        "1 WIFE @I3@",
        "1 CHIL @I1@",
        "1 MARR",
        "2 DATE 1950",
        "2 PLAC Reno",
    )
    step_tree = read_gedcom(step_ged)
    step_tree.people["I1"].parents = [ParentLink("F1", "step", "birth")]
    with_empty = drawn(render_charts(step_tree, "I1", parents=prefer, empty_boxes=True))
    without = drawn(render_charts(step_tree, "I1", parents=prefer, empty_boxes=False))
    assert "John PELL" not in with_empty and "John PELL" not in without
    assert "Mary PELL" in with_empty and "Mary PELL" in without
    assert "2" in with_empty and "2" not in without  # box 2's number
    assert "m. 1950" not in with_empty and "mp. Reno" not in with_empty

    # a continuation chart uses the mode too
    lines = []
    for xref, name, famc in (
        ("R", "Root", [("FR", "")]),
        ("A", "Aa", [("FA", "")]),
        ("B", "Bb", [("FB", "")]),
        ("C", "Cc", [("FC1", ""), ("FC2", "adopted")]),
        ("G", "Gg", []),
        ("H", "Hh", []),
        ("E", "Ee", []),
        ("F", "Ff", []),
    ):
        lines += indi(xref, f"{name} /X/", famc)
    for fam, husb, wife, child in (
        ("FR", "A", None, "R"),
        ("FA", "B", None, "A"),
        ("FB", "C", None, "B"),
        ("FC1", "G", "H", "C"),
        ("FC2", "E", "F", "C"),
    ):
        lines += (
            [f"0 @{fam}@ FAM", f"1 HUSB @{husb}@"]
            + ([f"1 WIFE @{wife}@"] if wife else [])
            + [f"1 CHIL @{child}@"]
        )
    cont_tree = read_gedcom(ged(*lines))
    cont_charts = plan_charts(cont_tree, "R", None, prefer)
    assert (cont_charts[1].slots[2], cont_charts[1].slots[3]) == (
        ("G", "H") if prefer == "birth" else ("E", "F")
    )


# ---------------------------------------------------------------- the root box


def joined_rows(pieces):
    """Join the label and value runs of mixed-font rows, such as "spouse: " and the
    spouse's name."""
    rows = []
    for piece in pieces:
        if rows and rows[-1].endswith(" "):
            rows[-1] += piece
        else:
            rows.append(piece)
    return rows


def test_the_root_box_and_its_family():
    marriages_ged = ged(
        "0 @R@ INDI",
        "1 NAME Root /vanDyke/",
        "1 DEAT Y",
        "1 FAMS @F1@",
        "1 FAMS @F2@",
        "0 @S1@ INDI",
        "1 NAME First /McClure/",
        "1 DEAT Y",
        "0 @S2@ INDI",
        "1 NAME Ada /deVries/",
        "1 DEAT Y",
        "0 @F1@ FAM",
        "1 HUSB @R@",
        "1 WIFE @S1@",
        "1 MARR",
        "2 DATE 1925",
        "2 PLAC First Town",
        "0 @F2@ FAM",
        "1 HUSB @R@",
        "1 WIFE @S2@",
        "1 MARR",
        "2 DATE 1935",
        "2 PLAC Other Town",
    )
    tree = read_gedcom(marriages_ged)
    # by default the first FAMS spouse and its matching marriage are shown
    text = joined_rows(drawn(render(tree, "R")))
    assert "spouse: First McCLURE" in text
    assert "m. 1925" in text and "mp. First Town" in text
    assert "spouse: Ada DEVRIES" not in text and "m. 1935" not in text
    # root_family switches spouse and marriage together; ancestors, continuations and
    # index membership do not change
    default_pdf, selected_pdf = render(tree, "R"), render(tree, "R", root_family="F2")
    text2 = joined_rows(drawn(selected_pdf))
    assert "spouse: Ada DEVRIES" in text2
    assert "m. 1935" in text2 and "mp. Other Town" in text2
    changed = {
        "First McCLURE",
        "Ada DEVRIES",
        "m. 1925",
        "m. 1935",
        "mp. First Town",
        "mp. Other Town",
    }
    default_first, selected_first = pages(default_pdf)[0], pages(selected_pdf)[0]
    assert [r for r in default_first if r.text not in changed] == [
        r for r in selected_first if r.text not in changed
    ]
    # a root with no family has an empty spouse line
    assert "spouse:" in drawn(render(Tree(people={"R": Person("R")}), "R"))
    # the spouse label is in German
    assert "Ehe mit: First McCLURE" in joined_rows(drawn(render(tree, "R", lang="de")))
    # the root box is centered between its neighbors (boxes 5 and 6), with equal gaps
    full = full_pedigree(5)
    pdf = render(full)
    boxes = rectangles(pdf, "B*")
    root_box = boxes[0]
    above, below = boxes[4], boxes[5]  # positions 5 and 6
    assert root_box[1] + root_box[3] / 2 == approx((above[1] + above[3] + below[1]) / 2)


# ---------------------------------------------------------------- record IDs


def test_record_ids(pedigree):
    def ids(pdf):
        return [t for t in drawn(pdf) if re.fullmatch(r"\[[A-Za-z0-9_]+\]", t)]

    # off by default; on with show_ids, one per known, drawn box; none for empty boxes
    assert ids(render_charts(pedigree)) == []
    found = ids(render_charts(pedigree, generations=3, show_ids=True))
    assert sorted(found) == sorted(f"[I{n}]" for n in range(1, 8))

    pdf = render_charts(pedigree, generations=1, show_ids=True)
    record = next(r for r in runs(pdf) if r.text == "[I1]")
    name = next(r for r in runs(pdf) if r.text == "Jane ASHFORD")
    # the ID's cap top aligns with the name's cap top (Helvetica capitals: 718/1000 em)
    assert record.y - record.size * 0.718 == approx(name.y - name.size * 0.718)
    assert record.font == "Helvetica" and record.size == 7

    # a long ID is cut to 40% of the text width, and the name fits in the room left
    XREF = "W" * 40
    long_tree = read_gedcom(
        ged(f"0 @{XREF}@ INDI", "1 NAME " + "Alexandrina Wilhelmina Fredericka " * 2)
    )
    pdf = render_charts(long_tree, XREF, generations=1, show_ids=True)
    geom = kincade.pdf.LETTER
    record = next(r for r in runs(pdf) if r.text.startswith("[W"))
    width = kincade.pdf.text_width(record.text, "Helvetica", geom.id_size)
    assert record.text.endswith("…]") and width <= geom.id_max + 1e-6
    name = next(r for r in runs(pdf) if r.text.startswith("Alexandrina"))
    assert name.right() <= record.x - geom.id_gap + 0.02

    # the index shows the ID after the name, before the years; empty boxes have none
    lines = kincade.pdf.build_index(
        pedigree,
        plan_charts(pedigree, "I1", 3),
        lambda pid: False,
        exclude_private=False,
        show_ids=True,
    )
    assert "ASHFORD, Jane [I1] (b. 1980), 1-1" in lines

    # the record_id template comes from the language
    strings = kincade.lang.load_strings(strings={"record_id": "<{id}>"})
    custom_lines = kincade.pdf.build_index(
        pedigree,
        plan_charts(pedigree, "I1", 1),
        lambda pid: False,
        exclude_private=False,
        strings=strings,
        show_ids=True,
    )
    assert any("<I1>" in line for line in custom_lines)


# ---------------------------------------------------------------- places


def test_places_are_shortened_to_fit():
    # the home country is dropped first, then middle parts marked with one ellipsis
    text = drawn(render_charts(read_gedcom(HOME_GED), generations=2))
    assert "bp. Springfield, …, Northern Missouri, Western Region" in text
    assert not any(t.startswith("bp. Springfield") and t.endswith("…") for t in text)
    # a single USA place is not a home country
    text = drawn(render_charts(read_gedcom(HOME_GED), generations=1))
    assert "bp. Springfield, …, Western Region, USA" in text
    # the language's ellipsis is used
    text = drawn(
        render_charts(read_gedcom(HOME_GED), generations=2, lang={"ellipsis": "..."})
    )
    assert "bp. Springfield, ..., Northern Missouri, Western Region" in text
    # a place made only of commas prints only its label
    commas_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Root /ROOT/", "1 BIRT", f"2 PLAC {',' * 100}")
    )
    line = next(
        t
        for t in drawn(render_charts(commas_tree, generations=1))
        if t.startswith("bp.")
    )
    assert line == "bp."


def test_no_shorten_places_only_truncates():
    tree = read_gedcom(HOME_GED)
    on = drawn(render_charts(tree, generations=2))
    off = drawn(render_charts(tree, generations=2, shorten_places=False))
    assert len(on) == len(off)
    changed = [(a, b) for a, b in zip(on, off, strict=True) if a != b]
    assert changed and all(b.endswith("…") for _, b in changed)
    truncated = "bp. Springfield, Greene County, Northern Missouri, Weste…"
    assert next(t for t in off if t.startswith("bp. Springfield")) == truncated


# ---------------------------------------------------------------- the index


def test_the_index_of_a_long_tree(long_index_tree):
    for paper in PAPERS:
        pdf = render(long_index_tree, paper=paper)
        assert count_pages(pdf) > len(plan_charts(long_index_tree, "I1")) + 1
        drawn_runs = runs(pdf)
        titles = [i for i, r in enumerate(drawn_runs) if r.text == "Index"]
        assert len(titles) >= 2
        geom = kincade.pdf.page_geom(paper)
        # the legend is on the first index page only, right under the title
        legend = "The numbers after each name indicate the chart number and box number. 6-1 is box 1 on chart 6."
        assert drawn_runs[titles[0] + 1].text == legend
        assert all(drawn_runs[i + 1].text != legend for i in titles[1:])
        # the body sits above the bottom margin and index pages are numbered
        assert all(
            r.y <= geom.y_bottom + 0.5 or r.y == geom.height - 42
            for r in drawn_runs
            if r.x >= kincade.pdf.INDEX_LEFT
        )
        numbered = [t for t in drawn(pdf) if re.fullmatch(r"Page \d+ of \d+", t)]
        assert len(numbered) == count_pages(pdf)
        # three columns, evenly spaced, each entry's first line flush with its
        # column's left edge (a literal 3, independent of kincade.pdf.INDEX_COLS)
        index_page_runs = [p for p in pages(pdf) if any(r.text == "Index" for r in p)]
        entry_xs = sorted(
            {
                round(r.x, 2)
                for p in index_page_runs
                for r in p
                if "," in r.text  # an index entry, not the title, legend or page text
            }
        )
        assert len(entry_xs) == 3
        assert entry_xs[0] == approx(kincade.pdf.INDEX_LEFT)
        gap1, gap2 = entry_xs[1] - entry_xs[0], entry_xs[2] - entry_xs[1]
        assert gap1 == approx(gap2) and gap1 > 0
    # an entry taller than a column stays on the page
    everywhere = dict.fromkeys(range(1, 16), "I1")
    tall_tree = read_gedcom(
        ged(
            "0 @I1@ INDI", "1 NAME Many /LOCATIONS/", "0 @I2@ INDI", "1 NAME Zed /ZULU/"
        )
    )
    charts = [kincade.charts.Chart(n, dict(everywhere)) for n in range(1, 141)]
    charts.append(kincade.charts.Chart(141, {**dict.fromkeys(range(1, 16)), 1: "I2"}))
    pdf = render_pdf(
        charts, tall_tree, Options(fonts="base14", compress=False, today=TODAY)
    )
    body = " ".join(r.text for r in runs(pdf))
    assert "140-15" in body and "ZULU" in body
    assert all(0 <= r.y <= 792 for r in runs(pdf))
    # a wrapped (continuation) line of that entry is indented past the column's edge
    tall_geom = kincade.pdf.page_geom("letter")
    tall_index = next(p for p in pages(pdf) if any(r.text == "Index" for r in p))
    many_runs = [
        r
        for r in tall_index
        if r.x >= kincade.pdf.INDEX_LEFT and r.y <= tall_geom.y_bottom + 0.5
    ]
    first_line = next(r for r in many_runs if r.text.startswith("LOCATIONS, Many"))
    wrapped_line = next(
        r for r in many_runs if r.y > first_line.y and r.x < tall_geom.index_col_w
    )
    assert wrapped_line.x > first_line.x  # indented past the column's own left edge
    # a literal 10, not kincade.pdf.INDEX_HANGING
    assert wrapped_line.x == approx(first_line.x + 10)


def test_the_index_order_and_entries():
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
            "0 @I6@ INDI",
            "1 NAME Zed /ZULU/",
            "0 @I7@ INDI",
            "1 NAME Bob /(UNKNOWN)/",
            "0 @I8@ INDI",
            "1 NAME Mia /GOOD/",
            "1 BIRT",
            "2 DATE c1950",
            "0 @I9@ INDI",
            "1 NAME Noa /GOOD/",
            "1 BIRT",
            "2 DATE unreadable text",
        )
    )
    chart = dict.fromkeys(range(1, 16))
    charts = [
        kincade.charts.Chart(
            1,
            {
                **chart,
                1: "I1",
                2: "I2",
                3: "I3",
                4: "I4",
                5: "I5",
                6: "I6",
                7: "I7",
                8: "I8",
                9: "I9",
            },
        )
    ]
    entries = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    heads = [e.split(" (")[0].split(", 1-")[0] for e in entries]
    # sorted by surname, given name without the title, then birth year; surnameless and
    # placeholder surnames come last
    assert heads == [
        "BLAKE, Ann",
        "BLAKE, Sarah",
        "BLAKE, Captain Timothy",
        "BLAKE, Timothy Jr.",
        "BLAKE, Major Timothy",
        "GOOD, Mia",
        "GOOD, Noa",
        "ZULU, Zed",
        "(UNKNOWN), Bob",
    ]
    # a year from text like "c1950" sorts as 1950; an unreadable year has none
    mia = next(e for e in entries if e.startswith("GOOD, Mia"))
    noa = next(e for e in entries if e.startswith("GOOD, Noa"))
    assert "(b. 1950)" in mia and "(b." not in noa
    # only drawn people are listed, and nothing is drawn when nobody is listed
    assert kincade.pdf._index_pages([], "Times-Roman", kincade.pdf.LETTER) == []


# ---------------------------------------------------------------- page numbers and footer


def test_page_numbers_and_footer(pedigree):
    pdf = render(pedigree, footer="Footer here")
    drawn_runs = runs(pdf)
    footer_run = next(r for r in drawn_runs if r.text == "Footer here")
    page_run = next(r for r in drawn_runs if r.text.startswith("Page "))
    assert page_run.text == "Page 1 of 7"
    assert page_run.x == approx(kincade.pdf.LEFT_MARGIN)
    assert page_run.y == approx(footer_run.y)  # the footer's baseline
    assert footer_run.x + kincade.pdf.text_width(
        "Footer here", "Helvetica", 8
    ) == approx(kincade.pdf.LETTER.footer_right)

    # a long footer is fitted 12 pt clear of the page number
    long_pdf = render(pedigree, footer="F" * 600, index=False)
    x = next(
        r.x for r in runs(long_pdf) if r.text.startswith("F") and r.text.endswith("…")
    )
    page_w = kincade.pdf.text_width("Page 1 of 1", "Helvetica", 8)
    assert x >= kincade.pdf.LEFT_MARGIN + page_w + 12 - 1e-6

    # footer=False keeps the numbers; page_numbers=False hides only them
    no_footer = drawn(render(pedigree, footer=False))
    assert any(t.startswith("Page ") for t in no_footer)
    assert not any(t.startswith("Created") for t in no_footer)
    no_numbers = drawn(render(pedigree, page_numbers=False))
    assert not any(t.startswith("Page ") for t in no_numbers)
    assert any(t.startswith("Created") for t in no_numbers)


# ---------------------------------------------------------------- text fitting


def test_long_text_is_squeezed_then_cut():
    # long names, titles and footers squeeze to 50% before the ellipsis
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME " + "1234 " * 12 + "/Smith/"))
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, index=False, footer=""),
    )
    (run,) = [
        r
        for r in runs(pdf)
        if r.text.endswith("…") and r.x == approx(kincade.pdf.BOX_X0[1] + 5)
    ]
    assert kincade.pdf.SQUEEZE <= run.scale < 1.0  # squeezed, not merely cut
    assert run.right() <= kincade.pdf.BOX_X0[1] + kincade.pdf.BOX_W - 3 + 1e-6

    out = kincade.pdf.fit("x" * 200, "Times-Roman", 9, 100)
    assert out.endswith("…") and kincade.pdf.stringWidth(out, "Times-Roman", 9) <= 100
    kept, scale = kincade.pdf.fit_squeezed("x" * 400, "Times-Roman", 9, 100)
    assert kept.endswith("…") and kincade.pdf.SQUEEZE <= scale < 1

    # controls are dropped, and drawable whitespace becomes a space
    assert kincade.pdf.clean("Ja\x00ne") == "Jane"
    assert kincade.pdf.clean("Jane\tAnn") == "Jane Ann"
    # base-14 text degrades to cp1252
    assert kincade.pdf.clean("Łódź") == "?ódz"
    # an accent in either Unicode form is drawn
    for name in ("Zoë /Müller/", "Zoë /Müller/"):
        accent_tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME {name}"))
        assert "Zoë MÜLLER" in drawn(render(accent_tree))


# ---------------------------------------------------------------- event stand-ins


def test_event_standins():
    # a christening stands in for a missing birth, a baptism if there is no christening
    for record in ("CHR", "BAPM"):
        tree = read_gedcom(
            ged(
                "0 @I1@ INDI",
                "1 NAME Jane /Doe/",
                f"1 {record}",
                "2 DATE 1900",
                "1 FAMC @F1@",
                "0 @I2@ INDI",
                "1 NAME John /Doe/",
                "1 BIRT",
                "2 PLAC Secretville",
                "0 @F1@ FAM",
                "1 HUSB @I2@",
                "1 CHIL @I1@",
            )
        )
        text = drawn(render_charts(tree, exclude_private=True))
        assert "bp. Secretville" in text, record  # Jane's christening bounds her birth
    # a burial stands in for a missing death, then a cremation
    for record, label in (("BURI", "bur."), ("CREM", "crem.")):
        tree = read_gedcom(
            ged(
                "0 @I1@ INDI",
                "1 NAME Old /Doe/",
                "1 BIRT",
                "2 DATE 1990",
                f"1 {record}",
                "2 DATE 2010",
            )
        )
        text = drawn(render_charts(tree))
        assert f"{label} 2010" in text, record
    # a christening beats a baptism when both are recorded
    both_chr = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            "1 CHR",
            "2 DATE 1900",
            "1 BAPM",
            "2 DATE 1905",
        )
    )
    chr_text = drawn(render_charts(both_chr))
    assert "chr. 1900" in chr_text and "1905" not in chr_text
    # a burial beats a cremation when both are recorded
    both_buri = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Old /Doe/",
            "1 BIRT",
            "2 DATE 1990",
            "1 BURI",
            "2 DATE 2010",
            "1 CREM",
            "2 DATE 2015",
        )
    )
    buri_text = drawn(render_charts(both_buri))
    assert "bur. 2010" in buri_text and "2015" not in buri_text
    # a birth or death place alone blocks the stand-in
    blocked = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            "1 BIRT",
            "2 PLAC Secretville",
            "1 CHR",
            "2 DATE 1900",
        )
    )
    assert "Secretville" not in drawn(render_charts(blocked, exclude_private=True))
    # the index years and sort use the stand-ins
    standin_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Jane /Doe/", "1 CHR", "2 DATE 1900")
    )
    lines = kincade.pdf.build_index(
        standin_tree,
        plan_charts(standin_tree, "I1", 1),
        lambda pid: False,
        exclude_private=False,
    )
    assert lines == ["DOE, Jane (chr. 1900), 1-1"]
    # event_standins=False draws births and deaths only
    off = drawn(render_charts(standin_tree, event_standins=False))
    assert "chr. 1900" not in off


# ---------------------------------------------------------------- names in boxes


DISPLAY_NAMES = [
    ("I1", 'Robert "Bob" WILKS'),  # nickname quotes kept
    ("I2", "Emily MILLARD\\MILLERS"),  # literal backslash kept
    ("I4", "Alan REED Jr"),  # FTW /Jr/ is a suffix, not a surname
    ("I5", "Capt Evan DALE"),  # FTW /{Capt}/ is a title
    ("I6", "FAIRWOOD"),  # no given name
]


def test_names_in_boxes(quirks):
    for xref, expected in DISPLAY_NAMES:
        text = drawn(render_charts(quirks, root=xref, generations=1))
        assert expected in text, xref
    # no repeated title or suffix when NPFX/NSFX repeat a word already in the payload
    dedup_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Dr. Alice /Jones/ Jr.", "2 NPFX Dr.", "2 NSFX Jr.")
    )
    assert "Dr. Alice JONES Jr." in drawn(render_charts(dedup_tree, generations=1))

    # placeholder versus real surnames
    for surname, placeholder in (
        ("(UNKNOWN)", True),
        ("?", True),
        ("N.N.", True),
        ("Smith", False),
        ("Nunez", False),
    ):
        assert kincade.lang.is_placeholder_surname(surname) is placeholder, surname

    # preserve_case draws the recorded case without changing the index order or the tree
    case_tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Root /Zed/",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Mary /McClure/",
            "1 BIRT",
            "2 DATE 1950",
            "0 @I3@ INDI",
            "1 NAME Amy /Adams/",
            "1 BIRT",
            "2 DATE 1920",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
        )
    )
    before = {pid: p.surname for pid, p in case_tree.people.items()}
    preserved = drawn(render_charts(case_tree, generations=2, preserve_case=True))
    assert "Mary McClure" in preserved and "Mary McCLURE" not in preserved
    after = {pid: p.surname for pid, p in case_tree.people.items()}
    assert after == before  # the tree is unchanged
    charts = plan_charts(case_tree, "I1", 2)
    index_plain = kincade.pdf.build_index(case_tree, charts, lambda pid: False, False)
    index_preserved = kincade.pdf.build_index(
        case_tree, charts, lambda pid: False, False, preserve_case=True
    )
    # Adams sorts before McClure either way
    assert [e.split(",")[0] for e in index_plain] == ["ADAMS", "McCLURE", "ZED"]
    assert [e.split(",")[0] for e in index_preserved] == ["Adams", "McClure", "Zed"]


# ---------------------------------------------------------------- the blank chart


def blank(**opts):
    opts.setdefault("today", TODAY)
    opts.setdefault("fonts", "base14")
    opts.setdefault("compress", False)
    return kincade.pdf.render_blank(Options(**opts))


def chart1(tree, root="I1", **opts):
    """Chart 1 of `tree`, planned and drawn alone, with the test defaults."""
    chart = plan_charts(tree, root)[0]
    opts.setdefault("today", TODAY)
    opts.setdefault("fonts", "base14")
    opts.setdefault("compress", False)
    return render_pdf([chart], tree, Options(index=False, **opts))


def test_the_blank_chart_matches_a_filled_chart(pedigree):
    # the boxes and lines are those of chart 1
    ours, real = blank(), chart1(pedigree)
    assert rectangles(ours, "B*") == rectangles(real, "B*")
    assert pdf_lines(ours) == pdf_lines(real)

    # labels sit where a filled box's labels sit, below an empty name line
    ours_runs, real_runs = runs(ours), runs(real)
    for label in ("b.", "bp.", "spouse:", "m.", "mp.", "d.", "dp."):
        want = {
            (r.x, r.y)
            for r in real_runs
            if r.text == label or r.text.startswith(label + " ")
        }
        mine = {(r.x, r.y) for r in ours_runs if r.text == label}
        assert mine and mine <= want, label

    # marriage lines are on box 1 and the fathers' boxes only
    geom = kincade.pdf.LETTER
    married = {
        pos for pos in range(1, 2**geom.gens) if kincade.pdf.has_marriage_lines(pos)
    }
    assert married == {1, 2, 4, 6, 8, 10, 12, 14}

    # header and footer are where a real chart's are
    title_ours = next((r.x, r.y) for r in ours_runs if r.text == "Cascading Pedigree")
    title_real = next(
        (r.x, r.y) for r in real_runs if r.text.startswith("Cascading Pedigree — ")
    )
    assert title_ours == title_real
    footer_ours = next(r.y for r in ours_runs if r.text == "Created using Kincade")
    footer_real = next(r.y for r in real_runs if r.text.startswith("Created "))
    assert footer_ours == footer_real

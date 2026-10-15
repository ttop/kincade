"""--generations N is a guarantee about what each page shows. A continuation chart is
made only for a last-column person with a known parent inside the limit, so no chart
page except chart 1 has all its boxes beyond box 1 empty; boxes past the limit are not
drawn at all, so an empty box appears only inside the requested range, where a known
line runs out. Checked for every root of the synthetic fixtures (and of some generated
trees with gaps, shared ancestors and adoptions), for generations None and 1 to 9, in
normal and large print, and for both parent modes.

Synthetic fixtures only."""

import itertools
import random

import pytest

import kincade.charts
import kincade.gedcom
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import FIX, PRINTS, ged
from pdfread import rectangles, streams

LIMITS = [None, *range(1, 10)]
MODES = ["birth", "adoptive"]


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
    """Every violation of the guarantee in the charts planned for this root, as texts
    (none: it holds).
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
        # what the renderer draws is what the chart says it draws
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
                    f"{where}: box {pos} is generation {chart.offset + kincade.charts.box_generation(pos)}"
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
                    f"{where}: continuation {pos} -> {number} is not the person's own chart"
                )
    return problems


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("name", TREES)
def test_every_chart_has_a_known_parent_inside_the_limit_and_no_box_past_it(
    name, large_print
):
    tree = TREES[name]
    problems = [
        problem
        for root, generations, parents in itertools.product(tree.people, LIMITS, MODES)
        for problem in guarantee(tree, root, generations, large_print, parents)
    ]
    assert problems == []


def test_the_generated_trees_are_varied_enough_to_mean_something():
    """The property test above would pass vacuously on trees that never reach the edge
    cases.
    """
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
    assert shared >= 1  # two boxes that continue on the same chart (pedigree collapse)
    adopted = TREES["random 1"]
    # the two parent modes really differ somewhere
    assert any(
        plan_charts(adopted, root, None, "birth")[0].slots
        != plan_charts(adopted, root, None, "adoptive")[0].slots
        for root in adopted.people
    )


@pytest.mark.parametrize("large_print", PRINTS, ids=["normal", "large"])
@pytest.mark.parametrize("generations", LIMITS)
def test_the_boxes_drawn_on_each_page_are_the_ones_the_plan_shows(
    generations, large_print
):
    """The same guarantee as the pages themselves show it: the box outlines of every
    page of the PDF, with and without --no-empty.
    """
    tree = TREES["pedigree"]
    for no_empty in (False, True):
        charts = plan_charts(tree, "I1", generations, "birth", large_print)
        pdf = render_pdf(
            charts,
            tree,
            Options(
                large_print=large_print,
                empty_boxes=not no_empty,
                index=False,
                fonts="base14",
                compress=False,
            ),
        )
        assert len(streams(pdf)) == len(charts)
        for page, chart in enumerate(charts):
            outlines = len(rectangles(pdf, "B*", page))
            assert outlines == sum(
                1
                for pos in range(1, 2**chart.depth)
                if kincade.pdf._shown(chart, pos, empty_boxes=not no_empty)
            )
            if chart.number != 1:
                assert outlines >= 2  # a continuation page is never a lone box 1


@pytest.mark.parametrize(
    "large_print,step", [(False, 3), (True, 2)], ids=["normal", "large"]
)
def test_a_continuation_chart_needs_its_first_parent_inside_the_limit(
    large_print, step
):
    """On a line of 14 people (13 parent links) the chart that starts k continuations on
    has its box 1 at generation step * k + 1, so its box 2 is generation step * k + 2:
    it exists exactly when that is within N and the person is in the file.
    """
    tree = TREES["line of fathers"]
    for generations in [None, *range(1, 16)]:
        limit = generations if generations is not None else 99
        charts = plan_charts(tree, "P0", generations, "birth", large_print)
        wanted = [
            k for k in range(1, 14) if step * k + 2 <= limit and step * k + 1 <= 13
        ]
        assert [chart.offset for chart in charts] == [0] + [step * k for k in wanted], (
            generations
        )
        assert all(
            chart.slots[2] is not None and chart.slots[2] in tree.people
            for chart in charts[1:]
        )

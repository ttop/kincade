"""Continuation charts: the person and the marriage a continuation chart starts from."""

import itertools

import pytest

import kincade
import kincade.charts
import kincade.pdf
from kincade import Date, Day, Event, Family, Options, ParentLink, Person, Tree
from kincade.charts import plan_charts

from conftest import TODAY, render_charts
from pdfread import drawn

# ----------------------------------------------------------------
# a continuation chart keeps the marriage it came with


def chain_tree(depth, line="father", step=False, union_first=True):
    """A chain p0 -> p1 -> ... -> x -> d, each the father of the one before
    (`line="father"`) or the mother (`"mother"`), with x in a box of the last generation
    of chart 1 (`depth` is 4 in normal print, 3 in large print) and a parent d, so that
    x roots chart 2. x is in two unions: F, with the other parent of the person just
    below x on the chain, married in 1930 in Xville, and Z, married in 1950 in Zville,
    which is listed first in x's families when `union_first` is false. With `step` that
    other parent is the stepmother (or stepfather) of the person below x. Nobody else is
    married."""
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


@pytest.mark.parametrize("empty_boxes", [True, False])
@pytest.mark.parametrize("large_print", [False, True])
@pytest.mark.parametrize("union_first", [True, False])
@pytest.mark.parametrize("line", ["father", "mother"])
def test_a_step_marriage_that_chart_1_leaves_out_is_left_out_of_chart_2_too(
    line, union_first, large_print, empty_boxes
):
    depth = 3 if large_print else 4
    tree = chain_tree(depth, line, step=True, union_first=union_first)
    charts = plan_charts(tree, "p0", None, "birth", large_print)
    # x roots chart 2, reached from the box below it on chart 1
    assert [c.slots[1] for c in charts] == ["p0", "x"]
    pdf = render_charts(tree, "p0", large_print=large_print, empty_boxes=empty_boxes)
    # not Xville's and not Zville's: the union with the step-parent is not drawn
    assert marriages(pdf) == []


@pytest.mark.parametrize("empty_boxes", [True, False])
@pytest.mark.parametrize("large_print", [False, True])
@pytest.mark.parametrize("union_first", [True, False])
@pytest.mark.parametrize("line", ["father", "mother"])
def test_chart_2_shows_the_marriage_that_chart_1_shows_for_the_parents_it_came_from(
    line, union_first, large_print, empty_boxes
):
    depth = 3 if large_print else 4
    tree = chain_tree(depth, line, step=False, union_first=union_first)
    pdf = render_charts(tree, "p0", large_print=large_print, empty_boxes=empty_boxes)
    # the parents of the child below x are married in Xville in 1930: x's box on chart 1
    # (a father) or the other parent's (x a mother) shows it, and box 1 of chart 2 shows
    # the same marriage, whichever union x lists first
    assert marriages(pdf) == ["m. 1930", "mp. Xville", "m. 1930", "mp. Xville"]


def test_the_union_above_a_person_is_the_drawn_family_unless_it_is_with_a_step_parent():
    tree = chain_tree(4, step=False)
    assert tree.parents_union("p2").id == "f2" and tree.parents_union(
        "p2"
    ) is tree.parent_family("p2")
    # no parent family
    assert tree.parents_union("d") is None and tree.parents_union("nobody") is None
    for father, mother in (("step", "birth"), ("birth", "step"), ("step", "step")):
        tree.people["p2"].parents = [ParentLink("f2", father, mother)]
        # his parent family all the same
        assert tree.parents_union("p2") is None and tree.parent_family("p2").id == "f2"
    tree.people["p2"].parents = [ParentLink("f2", "adopted", "foster")]
    assert tree.parents_union("p2").id == "f2"  # adopted and foster parents are drawn
    with pytest.raises(ValueError, match="parents"):
        tree.parents_union("p2", "sideways")


def test_the_first_chart_shows_its_roots_first_marriage():
    tree = chain_tree(4, "father", step=False, union_first=False)
    # the root's own first FAMS (an unrelated family here)
    tree.people["p0"].families = ["fz"]
    assert marriages(render_charts(tree, "p0", generations=1)) == [
        "m. 1950",
        "mp. Zville",
    ]


def test_a_continuation_chart_knows_the_person_below_its_first_box():
    tree = chain_tree(4)
    charts = plan_charts(tree, "p0")
    assert (
        charts[0].via is None and charts[1].via == "p2" and charts[1].origin == (1, 8)
    )
    assert [c.via for c in plan_charts(chain_tree(3), "p0", None, "birth", True)] == [
        None,
        "p1",
    ]


def parents_of(tree, child, fid, father="", mother="", marriage=None, step=None):
    """Family `fid` becomes the parents of `child`, which it adds to the tree (with any
    parent that is not there yet). `step` ("father" or "mother") makes that parent the
    child's step-parent.
    """
    for pid in (child, father, mother):
        if pid and pid not in tree.people:
            tree.people[pid] = Person(pid, given=pid, surname="Pell")
    tree.families[fid] = Family(fid, father, mother, marriage, [child])
    tree.people[child].parents.append(ParentLink(fid, **{step: "step"} if step else {}))
    for pid in (father, mother):
        if pid:
            tree.people[pid].families.append(fid)


def collapse_tree(depth, x_is="father", step=None, first_listed=True, second_on=1):
    """A pedigree where x is an ancestor of p0 twice, through two children by different
    partners, in two unions. p0 has a father line a1 a2 ... and a mother line b1 b2 ...,
    each depth - 2 people long (`depth` is 4 in normal print, 3 in large print), so that
    the parents of the last person of a line stand in the last column of chart 1. x is
    the father (`x_is="father"`) or the mother of two such children, with a different
    partner in each union:
      union 1, married in 1930 in Xville: x's first box, which roots the chart that
      continues x. Its child is the last
        person of the father line (of the mother line, with `second_on=2`).
      union 2, married in 1940 in Yville. Its child is the last person of the other line
      (`second_on=1`: x has two
        boxes on chart 1), or the last person of a line n1 n2 ... of fathers above a y,
        who is the father of the other line's last person (x has its second box on y's
        chart: chart 3 with `second_on=3`, chart 2 with `second_on=2`).
    `step` (1 or 2) makes the partner in that union the child's step-parent. x lists
    union 2 first unless `first_listed`. x's father is d, so that x roots a chart."""
    tree = Tree()
    other = "mother" if x_is == "father" else "father"
    marriage = {
        1: Event(Date("exact", Day(1930)), "Xville"),
        2: Event(Date("exact", Day(1940)), "Yville"),
    }

    # each name is the `role` parent of the one before, starting from `child`
    def line_up(child, names, role):
        for kid, parent in itertools.pairwise([child, *names]):
            parents_of(tree, kid, f"g{kid}", **{role: parent})

    def union(number, child):
        parents_of(
            tree,
            child,
            f"u{number}",
            **{x_is: "x", other: f"w{number}"},
            marriage=marriage[number],
            step=other if step == number else None,
        )

    a, b, n = ([f"{line}{i}" for i in range(1, depth - 1)] for line in "abn")
    parents_of(tree, "p0", "f0", father="a1", mother="b1")
    line_up(a[0], a[1:], "father")
    line_up(b[0], b[1:], "mother")
    first, second = (b, a) if second_on == 2 else (a, b)
    union(1, first[-1])
    if second_on == 1:
        union(2, second[-1])
    else:
        parents_of(tree, second[-1], "fy", father="y")
        line_up("y", n, "father")
        union(2, n[-1])
    parents_of(tree, "x", "fx", father="d")
    if not first_listed:
        tree.people["x"].families.reverse()
    return tree


def cross_references(pdf):
    """The (box, chart) pairs a PDF draws: a box number followed at once by the number
    of the chart it continues on.
    """
    texts = drawn(pdf)
    return [
        (int(box), int(chart))
        for box, chart in itertools.pairwise(texts)
        if box.isdigit() and chart.isdigit()
    ]


@pytest.mark.parametrize("second_on", [1, 2, 3])
@pytest.mark.parametrize("x_is", ["father", "mother"])
@pytest.mark.parametrize("large_print", [False, True])
def test_a_person_in_two_boxes_has_one_continuation_chart_that_starts_from_the_first_box(
    large_print, x_is, second_on
):
    depth = 3 if large_print else 4
    tree = collapse_tree(depth, x_is, second_on=second_on)
    # the last column's box of the father of each line's last person
    end = {"a": 2 ** (depth - 1), "b": 2**depth - 2}
    # x's: that father's box, or the mother's
    x_box = {line: box + (x_is == "mother") for line, box in end.items()}
    charts = plan_charts(tree, "p0", None, "birth", large_print)
    pdf = render_charts(tree, "p0", large_print=large_print)
    if second_on == 1:  # x's second box is on chart 1 too, and points at the same chart
        assert [c.slots[1] for c in charts] == ["p0", "x"] and charts[0].slots[
            x_box["b"]
        ] == "x"
        assert (charts[1].origin, charts[1].via) == ((1, x_box["a"]), f"a{depth - 2}")
        assert charts[0].continuations == {x_box["a"]: 2, x_box["b"]: 2}
        assert cross_references(pdf) == [(x_box["a"], 2), (x_box["b"], 2)]
    # x roots chart 2, y chart 3, and on chart 3 x is a reference back to chart 2
    elif second_on == 3:
        assert [c.slots[1] for c in charts] == ["p0", "x", "y"] and charts[2].slots[
            x_box["a"]
        ] == "x"
        assert (charts[1].origin, charts[1].via) == ((1, x_box["a"]), f"a{depth - 2}")
        assert charts[0].continuations == {x_box["a"]: 2, end["b"]: 3} and charts[
            2
        ].continuations == {x_box["a"]: 2}
        assert cross_references(pdf) == [
            (x_box["a"], 2),
            (end["b"], 3),
            (x_box["a"], 2),
        ]
    # y roots chart 2 and x chart 3, from its box on the mother line; on chart 2 x
    # refers forward to chart 3
    else:
        assert [c.slots[1] for c in charts] == ["p0", "y", "x"] and charts[1].slots[
            x_box["a"]
        ] == "x"
        assert (charts[2].origin, charts[2].via) == ((1, x_box["b"]), f"b{depth - 2}")
        assert charts[0].continuations == {end["a"]: 2, x_box["b"]: 3} and charts[
            1
        ].continuations == {x_box["a"]: 3}
        assert cross_references(pdf) == [
            (end["a"], 2),
            (x_box["b"], 3),
            (x_box["a"], 3),
        ]


@pytest.mark.parametrize("second_on", [1, 2, 3])
@pytest.mark.parametrize("first_listed", [True, False])
@pytest.mark.parametrize("step", [None, 1, 2])
@pytest.mark.parametrize("x_is", ["father", "mother"])
@pytest.mark.parametrize("large_print", [False, True])
def test_the_continuation_of_a_collapsed_pedigree_shows_the_marriage_of_the_first_union_reached(
    large_print, x_is, step, first_listed, second_on
):
    tree = collapse_tree(3 if large_print else 4, x_is, step, first_listed, second_on)
    # A union with a step-parent is left out where it would be drawn. The first box of x
    # (in union 1) roots the chart that continues x, so that chart's box 1 shows union 1
    # or, with a step-parent in it, nothing: not union 2, which is the other box of x,
    # and not the union x lists first
    one = [] if step == 1 else ["m. 1930", "mp. Xville"]
    two = [] if step == 2 else ["m. 1940", "mp. Yville"]
    # in page order: with x's second box on chart 1, chart 1 draws union 1 then 2 and
    # chart 2 (x) union 1; with it on chart 3 (the chart of y), chart 1 draws union 1,
    # chart 2 (x) union 1 and chart 3 union 2; with it on chart 2 (y), chart 1 draws
    # union 1, chart 2 union 2 and chart 3 (x) union 1
    expected = {1: one + two + one, 2: one + two + one, 3: one + one + two}
    assert (
        marriages(render_charts(tree, "p0", large_print=large_print))
        == expected[second_on]
    )


def test_a_hand_built_chart_without_a_context_shows_the_first_marriage():
    tree = chain_tree(4, step=False, union_first=False)
    chart = kincade.charts.Chart(1, {**dict.fromkeys(range(1, 16)), 1: "x"})
    assert marriages(
        kincade.pdf.render_pdf(
            [chart],
            tree,
            Options(today=TODAY, fonts="base14", compress=False, index=False),
        )
    ) == ["m. 1950", "mp. Zville"]


def test_the_adoptive_mode_chooses_the_family_the_continuation_came_from():
    # x is an adopted father in one family (married 1930)
    # and a birth father in another (married 1940)
    tree = chain_tree(4, step=False)
    tree.people["p2"].parents = [
        ParentLink("f2"),
        ParentLink("fa", "adopted", "adopted"),
    ]
    tree.families["fa"] = Family(
        "fa",
        father="x",
        mother="amy",
        children=["p2"],
        marriage=Event(Date("exact", Day(1940))),
    )
    tree.people["amy"] = Person("amy", given="Amy", surname="Pell", families=["fa"])
    tree.people["x"].families = ["fz", "f2", "fa"]
    birth = marriages(render_charts(tree, "p0"))
    adoptive = marriages(render_charts(tree, "p0", adoptive_parents=True))
    assert birth == ["m. 1930", "mp. Xville", "m. 1930", "mp. Xville"]
    assert adoptive == ["m. 1940", "m. 1940"]

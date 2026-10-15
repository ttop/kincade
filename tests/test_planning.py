"""Chart planning: box positions, numbering, generations, collapse and cycles."""

import pytest

from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom

from conftest import FIX


def test_chart_one_positions(pedigree):
    c1 = plan_charts(pedigree, "I1")[0]
    assert [c1.slots[p] for p in range(1, 16)] == [f"I{n}" for n in range(1, 16)]
    assert c1.origin is None and c1.offset == 0 and c1.drawn == frozenset(range(1, 16))


def test_bfs_numbering(pedigree):
    charts = plan_charts(pedigree, "I1")
    assert [c.number for c in charts] == [1, 2, 3, 4, 5, 6]
    # 9: father only, 12: mother only
    assert charts[0].continuations == {8: 2, 9: 3, 12: 4, 14: 5}
    assert charts[1].continuations == {8: 6}
    # box 1 of a continuation is generation offset + 1
    assert [(c.slots[1], c.origin, c.offset) for c in charts[1:]] == [
        ("I8", (1, 8), 3),
        ("I9", (1, 9), 3),
        ("I12", (1, 12), 3),
        ("I14", (1, 14), 3),
        ("I24", (2, 8), 6),
    ]
    assert (charts[4].slots[2], charts[4].slots[3]) == ("I20", "I21")


def test_generations_limit_which_boxes_are_drawn(pedigree):
    one = plan_charts(pedigree, "I1", generations=1)
    assert len(one) == 1 and one[0].continuations == {}
    assert one[0].drawn == frozenset({1})
    # not drawn, so not even unknown boxes
    assert [one[0].slots[p] for p in range(2, 16)] == [None] * 14
    three = plan_charts(pedigree, "I1", generations=3)
    # no right column, no continuation charts
    assert len(three) == 1 and three[0].continuations == {}
    assert three[0].drawn == frozenset(range(1, 8))
    assert all(three[0].slots[p] is None for p in range(8, 16))
    assert plan_charts(pedigree, "I1", generations=4)[0].drawn == frozenset(
        range(1, 16)
    )


def test_generations_limit_chart_creation(pedigree):
    four = plan_charts(pedigree, "I1", generations=4)
    # the great-grandparents' parents are generation 5
    assert len(four) == 1 and four[0].continuations == {}
    five = plan_charts(pedigree, "I1", generations=5)
    assert [c.number for c in five] == [1, 2, 3, 4, 5]
    assert five[0].continuations == {8: 2, 9: 3, 12: 4, 14: 5}
    # generations 4 and 5 only
    assert all(c.drawn == frozenset({1, 2, 3}) for c in five[1:])
    assert all(c.continuations == {} for c in five[1:])
    seven = plan_charts(pedigree, "I1", generations=7)
    # generations 7: chart 1 and its four continuations
    assert [c.number for c in seven] == [1, 2, 3, 4, 5]
    assert all(c.drawn == frozenset(range(1, 16)) for c in seven)
    assert seven[1].continuations == {}
    eight = plan_charts(pedigree, "I1", generations=8)
    assert [c.number for c in eight] == [1, 2, 3, 4, 5, 6] and eight[
        1
    ].continuations == {8: 6}
    assert eight[5].drawn == frozenset({1, 2, 3})
    assert [c.number for c in plan_charts(pedigree, "I1", generations=10)] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    # default: all
    assert [c.number for c in plan_charts(pedigree, "I1")] == [1, 2, 3, 4, 5, 6]


def test_generations_must_be_at_least_one(pedigree):
    with pytest.raises(ValueError):
        plan_charts(pedigree, "I1", generations=0)


def test_pedigree_collapse_references_the_first_chart():
    tree = read_gedcom(FIX / "collapse.ged")
    charts = plan_charts(tree, "I1")
    c1 = charts[0]
    assert c1.slots[4] == c1.slots[6] == "I4"
    assert c1.slots[8] == c1.slots[12] == "I8" and c1.slots[9] == c1.slots[13] == "I9"
    assert c1.continuations == {8: 2, 12: 2, 9: 3, 13: 3}
    assert len(charts) == 3  # no extra charts for the second sighting


def test_cycle_terminates():
    tree = read_gedcom(FIX / "cycle.ged")
    charts = plan_charts(tree, "I1")
    assert [c.slots[1] for c in charts] == ["I1", "I2"]
    assert charts[0].continuations == {8: 2}
    # back to the chart rooted at the first person
    assert charts[1].continuations == {8: 1}


def test_unknown_root_raises(pedigree):
    with pytest.raises(KeyError):
        plan_charts(pedigree, "I999")

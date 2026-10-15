"""A child's relationship to each parent, and who is drawn. A pedigree chart shows
ancestors, so a step-parent is never placed in a box.

`ParentLink(family, father="birth", mother="birth")` says how the child is related to
the family's father and to its mother: birth, adopted, foster, step or other. Kincade
draws the father and the mother of one parent family per person, and a step-parent is
left out of it: the box stays empty, like the box of any unknown ancestor.

  * In birth mode the families of a person are ranked by most birth relationships,
    then fewest step relationships, then file order. With no step links that is the
    first family whose parents are both birth parents, if there is one.
  * `adoptive` mode takes the first family with an adopted parent, else the first with a
    foster parent, else as birth.
  * The note after a name (adopted, foster) comes from the drawn, non-blank parents:
    adopted beats foster; birth and other parents, and a blanked step-parent, give none.
  * The age estimate follows a child-to-parent edge only to a parent who is the child's
    birth parent, per parent.

Synthetic fixtures only: trees built in code, with no GEDCOM.
"""

import pytest

import kincade.charts
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.model import Date, Day, Event, Family, ParentLink, Tree

from conftest import SECRETVILLE, built_person, render_charts, tom_tree
from pdfread import drawn


def render_tom(tree, **opts):
    """The chart pages from Tom."""
    return render_charts(tree, "tom", **opts)


def year(y):
    return Event(Date("exact", Day(y)))


# ----------------------------------------------------------------
# Tom: a stepfather is never drawn


def test_toms_only_family_draws_his_mother_and_leaves_the_father_box_empty():
    tree = tom_tree()
    assert tree.parent_ids("tom") == (None, "mary")
    assert tree.parent_family("tom").id == "f1"  # Tom's parent family all the same
    charts = plan_charts(tree, "tom")
    assert [charts[0].slots[pos] for pos in (1, 2, 3)] == ["tom", None, "mary"]


def test_a_stepmother_is_left_out_the_same_way():
    tree = tom_tree(ParentLink("f1", "birth", "step"))
    assert tree.parent_ids("tom") == ("john", None)


def test_a_family_of_two_step_parents_draws_nobody():
    tree = tom_tree(ParentLink("f1", "step", "step"))
    assert tree.parent_ids("tom") == (None, None)
    charts = plan_charts(tree, "tom")
    assert charts[0].slots[2] is None and charts[0].slots[3] is None


@pytest.mark.parametrize(
    "links",
    [
        (ParentLink("f1", "step", "birth"), ParentLink("f2")),
        (ParentLink("f2"), ParentLink("f1", "step", "birth")),
    ],
    ids=["step family first", "birth family first"],
)
@pytest.mark.parametrize("prefer", ["birth", "adoptive"])
def test_with_bob_in_the_file_the_family_of_two_birth_parents_wins_whatever_the_order(
    links, prefer
):
    tree = tom_tree(*links, bob=True)
    assert tree.parent_ids("tom", prefer) == ("bob", "mary")
    assert tree.parent_family("tom", prefer).id == "f2"


def test_the_ranking_counts_the_relationships_a_link_gives_not_the_parents_a_family_names():
    # Bob's family f2 names no mother, but Tom is a birth child of it (two birth
    # relationships against one in f1), so it is drawn: the choice never depends on who
    # happens to be recorded
    tree = tom_tree(ParentLink("f1", "step", "birth"), ParentLink("f2"), bob=True)
    tree.families["f2"].mother = ""
    assert tree.parent_ids("tom") == ("bob", None)


def test_a_stepfather_leaves_no_trace_on_the_chart():
    text = drawn(render_tom(tom_tree()))
    assert "Mary PELL" in text and "Tom PELL" in text
    assert not [t for t in text if "John" in t]
    # no note on Tom: no "(step)" or anything else
    assert not [t for t in text if "(" in t and "Pell" in t]


def test_the_empty_father_box_is_drawn_and_numbered_with_empty_boxes_and_left_out_with_no_empty():
    tree = tom_tree()
    with_empty = drawn(render_tom(tree, empty_boxes=True))
    without = drawn(render_tom(tree, empty_boxes=False))
    assert "2" in with_empty and "3" in with_empty
    assert "2" not in without and "3" in without  # box 2 is not drawn; box 3 (Mary) is
    assert not [t for t in without if "John" in t]


def test_the_marriage_of_a_step_parent_is_not_shown_in_the_empty_box():
    # John and Mary married in 1950 in Reno; that is not the marriage of Tom's parents
    for empty in (True, False):
        text = drawn(render_tom(tom_tree(), empty_boxes=empty))
        assert "m. 1950" not in text and "mp. Reno" not in text


def test_the_marriage_of_a_birth_father_and_a_stepmother_is_not_shown_in_the_fathers_box():
    text = drawn(render_tom(tom_tree(ParentLink("f1", "birth", "step"))))
    assert "John PELL" in text
    assert "m. 1950" not in text and "mp. Reno" not in text


def test_the_marriage_of_two_birth_parents_is_shown_in_the_fathers_box():
    text = drawn(render_tom(tom_tree(ParentLink("f1"))))
    assert "John PELL" in text and "m. 1950" in text and "mp. Reno" in text


def test_a_blanked_parent_has_no_continuation_chart_and_no_index_entry():
    # Tom <- Mary; John, Tom's stepfather, has parents of his own (Jack and Jill):
    # nobody follows John
    tree = tom_tree()
    tree.people["john"].parents = [ParentLink("f3")]
    tree.people["jack"] = built_person("jack", "Jack", 1840, 1910, families=["f3"])
    tree.people["jill"] = built_person("jill", "Jill", 1845, 1915, families=["f3"])
    tree.families["f3"] = Family("f3", "jack", "jill", None, ["john"])
    charts = plan_charts(tree, "tom")
    assert len(charts) == 1 and charts[0].continuations == {}
    index = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    assert [line.split(",")[0] for line in index] == ["PELL"] * 2  # Tom and Mary only
    assert not [
        line for line in index if "John" in line or "Jack" in line or "Jill" in line
    ]


def test_a_step_link_at_the_edge_of_a_chart_gives_no_continuation():
    # Root r <- a (box 2) <- b (4) <- c (8, the last generation). c has a father d, so c
    # gets a continuation chart, unless c is b's step-parent
    def chain(link):
        people = {
            pid: built_person(pid, pid.upper(), 1800 - 30 * i)
            for i, pid in enumerate("rabcd")
        }
        people["r"].parents = [ParentLink("fr")]
        people["a"].parents = [ParentLink("fa")]
        people["b"].parents = [link]
        people["c"].parents = [ParentLink("fc")]
        families = {
            "fr": Family("fr", "a", "", children=["r"]),
            "fa": Family("fa", "b", "", children=["a"]),
            "fb": Family("fb", "c", "", children=["b"]),
            "fc": Family("fc", "d", "", children=["c"]),
        }
        return Tree(people, families)

    assert [c.slots[8] for c in plan_charts(chain(ParentLink("fb")), "r")[:1]] == ["c"]
    assert len(plan_charts(chain(ParentLink("fb")), "r")) == 2
    stepped = plan_charts(chain(ParentLink("fb", "step", "birth")), "r")
    assert (
        len(stepped) == 1
        and stepped[0].slots[8] is None
        and stepped[0].continuations == {}
    )


# ----------------------------------------------------------------
# choosing a family: no step links


@pytest.mark.parametrize(
    "words,first_birth",
    [
        (["birth", "birth"], 0),
        (["adopted", "birth"], 1),
        (["foster", "birth"], 1),
        (["other", "birth"], 1),
        (["adopted", "foster", "birth"], 2),
        (["adopted", "adopted"], 0),
        (["foster", "adopted", "other"], 0),
        (["other", "foster"], 0),
        (["birth", "adopted", "birth"], 0),
    ],
)
def test_without_step_links_birth_mode_takes_the_first_birth_family_else_the_first(
    words, first_birth
):
    people = {
        "kid": built_person(
            "kid",
            "Kid",
            parents=[ParentLink(f"f{i}", w, w) for i, w in enumerate(words)],
        )
    }
    families = {}
    for i in range(len(words)):
        people[f"p{i}"] = built_person(f"p{i}", f"P{i}")
        families[f"f{i}"] = Family(f"f{i}", f"p{i}", "", children=["kid"])
    assert Tree(people, families).parent_family("kid").id == f"f{first_birth}"


def test_a_birth_family_with_nobody_in_it_comes_first_when_it_is_listed_first():
    people = {
        "kid": built_person("kid", "Kid", parents=[ParentLink("f1"), ParentLink("f2")]),
        "p": built_person("p", "P"),
    }
    tree = Tree(
        people,
        {
            "f1": Family("f1", children=["kid"]),
            "f2": Family("f2", "p", children=["kid"]),
        },
    )
    assert tree.parent_family("kid").id == "f1"


@pytest.mark.parametrize(
    "words,expected",
    [
        (["birth", "birth"], 0),
        (["adopted", "birth"], 0),
        (["birth", "adopted"], 1),
        (["birth", "foster"], 1),
        (["other", "foster"], 1),
        (["foster", "other"], 0),
        (["foster", "adopted"], 1),
        (["other", "other"], 0),
        (["birth", "birth", "adopted"], 2),
    ],
)
def test_adoptive_mode_without_step_links_takes_adopted_then_foster_then_as_birth(
    words, expected
):
    people = {
        "kid": built_person(
            "kid",
            "Kid",
            parents=[ParentLink(f"f{i}", w, w) for i, w in enumerate(words)],
        )
    }
    families = {}
    for i in range(len(words)):
        people[f"p{i}"] = built_person(f"p{i}", f"P{i}")
        families[f"f{i}"] = Family(f"f{i}", f"p{i}", "", children=["kid"])
    chosen = Tree(people, families).parent_family("kid", "adoptive").id
    adopted = [i for i, w in enumerate(words) if w == "adopted"]
    foster = [i for i, w in enumerate(words) if w == "foster"]
    birth = [i for i, w in enumerate(words) if w == "birth"]
    assert chosen == f"f{(adopted or foster or birth or [0])[0]}"


# ----------------------------------------------------------------
# choosing a family: ranking with step links


def ranked(*pairs, prefer="birth"):
    """The index of the family drawn for a child whose links are the (father, mother)
    relationship pairs, in order.
    """
    people = {
        "kid": built_person(
            "kid",
            "Kid",
            parents=[ParentLink(f"f{i}", *pair) for i, pair in enumerate(pairs)],
        )
    }
    families = {}
    for i in range(len(pairs)):
        people[f"p{i}"], people[f"q{i}"] = (
            built_person(f"p{i}", f"P{i}"),
            built_person(f"q{i}", f"Q{i}"),
        )
        families[f"f{i}"] = Family(f"f{i}", f"p{i}", f"q{i}", children=["kid"])
    return int(Tree(people, families).parent_family("kid", prefer).id[1:])


def test_more_birth_parents_beat_fewer_whatever_the_order():
    assert ranked(("step", "birth"), ("birth", "birth")) == 1
    assert ranked(("birth", "birth"), ("step", "birth")) == 0
    # one birth parent against none
    assert ranked(("adopted", "adopted"), ("birth", "adopted")) == 1
    assert ranked(("other", "other"), ("adopted", "birth"), ("birth", "birth")) == 2


def test_equal_birth_parents_fall_back_to_file_order():
    assert ranked(("step", "birth"), ("birth", "step")) == 0
    assert ranked(("birth", "step"), ("step", "birth")) == 0
    assert ranked(("adopted", "birth"), ("birth", "foster")) == 0
    assert ranked(("step", "step"), ("step", "step")) == 0


def test_a_family_that_draws_somebody_beats_one_that_draws_nobody_when_birth_parents_tie():
    # the adoptive parents, as with no birth family
    assert ranked(("step", "step"), ("adopted", "adopted")) == 1
    assert ranked(("step", "step"), ("other", "foster")) == 1
    # two drawn beat one
    assert ranked(("step", "adopted"), ("adopted", "adopted")) == 1
    assert ranked(("step", "foster"), ("adopted", "step")) == 0  # equal: file order


def test_one_birth_parent_against_two_non_birth_parents_goes_to_the_birth_parent():
    # Mary alone beats two adoptive parents in birth mode
    assert ranked(("adopted", "adopted"), ("step", "birth")) == 1


def test_adoptive_mode_takes_the_first_family_with_an_adopted_parent_then_foster_then_as_birth():
    assert ranked(("birth", "birth"), ("adopted", "step"), prefer="adoptive") == 1
    assert ranked(("birth", "birth"), ("step", "adopted"), prefer="adoptive") == 1
    # the first adopted family
    assert ranked(("birth", "adopted"), ("adopted", "adopted"), prefer="adoptive") == 0
    assert (
        ranked(
            ("birth", "birth"),
            ("foster", "step"),
            ("adopted", "adopted"),
            prefer="adoptive",
        )
        == 2
    )
    assert ranked(("birth", "birth"), ("birth", "foster"), prefer="adoptive") == 1
    # as for birth mode
    assert ranked(("step", "birth"), ("birth", "birth"), prefer="adoptive") == 1
    assert ranked(("step", "step"), ("other", "other"), prefer="adoptive") == 1


# ----------------------------------------------------------------
# the adopted parent beside a birth parent


def adoption_tree(father="adopted", mother="birth", **opts):
    """Tom's family f1: John (his adoptive father) and Mary (his mother); Tom's link
    says how he is related to each.
    """
    return tom_tree(ParentLink("f1", father, mother), **opts)


def test_a_child_adopted_by_his_mothers_husband_draws_both_parents_in_either_mode():
    tree = adoption_tree()
    for prefer in ("birth", "adoptive"):
        assert tree.parent_ids("tom", prefer) == ("john", "mary")


def test_one_adopted_parent_and_one_birth_parent_give_the_one_note_adopted():
    text = drawn(render_tom(adoption_tree()))
    assert "Tom PELL (adopted)" in text
    # the parents carry no note of their own here
    assert "John PELL" in text and "Mary PELL" in text


@pytest.mark.parametrize(
    "father,mother,note",
    [
        ("adopted", "birth", "adopted"),
        ("birth", "adopted", "adopted"),
        ("adopted", "adopted", "adopted"),
        ("foster", "birth", "foster"),
        ("birth", "foster", "foster"),
        ("foster", "foster", "foster"),
        ("other", "birth", "birth"),
        ("birth", "other", "birth"),
        ("other", "other", "birth"),
        ("adopted", "foster", "adopted"),
        ("foster", "adopted", "adopted"),
        ("foster", "other", "foster"),
        ("other", "foster", "foster"),
        ("adopted", "other", "adopted"),
        ("birth", "birth", "birth"),
    ],
)
def test_the_note_is_adopted_before_foster_and_birth_or_other_parents_give_none(
    father, mother, note
):
    tree = adoption_tree(father, mother)
    assert tree.parent_relationship("tom") == note
    expected = "" if note == "birth" else f" ({note})"
    assert f"Tom PELL{expected}" in drawn(render_tom(tree))


@pytest.mark.parametrize(
    "father,mother,note",
    [
        ("step", "birth", "birth"),
        ("birth", "step", "birth"),
        ("step", "adopted", "adopted"),
        ("adopted", "step", "adopted"),
        ("step", "foster", "foster"),
        ("foster", "step", "foster"),
        ("step", "other", "birth"),
        ("step", "step", "birth"),
    ],
)
def test_a_blanked_step_parent_does_not_count_for_the_note(father, mother, note):
    tree = adoption_tree(father, mother)
    assert tree.parent_relationship("tom") == note
    assert tree.parent_relationship("tom", "adoptive") == note


def test_the_note_follows_the_parents_that_are_drawn_not_the_ones_that_are_missing():
    tree = adoption_tree("adopted", "birth")
    # John is not recorded: only Mary, a birth parent, is drawn
    tree.families["f1"].father = ""
    assert (
        tree.parent_ids("tom") == (None, "mary")
        and tree.parent_relationship("tom") == "birth"
    )
    tree = adoption_tree("adopted", "birth")
    del tree.people["john"]  # ... or he is named but not in the file
    assert (
        tree.parent_ids("tom") == (None, "mary")
        and tree.parent_relationship("tom") == "birth"
    )
    assert "Tom PELL" in drawn(render_tom(tree))


def test_when_nobody_is_drawn_the_note_follows_the_family():
    tree = adoption_tree("adopted", "adopted")
    del tree.people["john"], tree.people["mary"]
    assert (
        tree.parent_ids("tom") == (None, None)
        and tree.parent_relationship("tom") == "adopted"
    )
    tree = adoption_tree("step", "step")
    assert (
        tree.parent_ids("tom") == (None, None)
        and tree.parent_relationship("tom") == "birth"
    )


def test_a_person_with_no_parent_family_has_no_note():
    assert (
        tom_tree().parent_relationship("mary") == "birth"
        and tom_tree().parent_relationship("nobody") == "birth"
    )


def test_a_step_note_in_a_language_file_is_an_unknown_key(tmp_path, capsys):
    path = tmp_path / "steps.toml"
    path.write_text(
        '[relationship]\nstep = "(Stief)"\nadopted = "(adopt.)"\n', encoding="utf-8"
    )
    with pytest.warns(UserWarning, match="unknown key 'relationship.step' ignored"):
        strings = kincade.lang.load_strings(str(path))
    assert (
        strings["relationship"]["adopted"] == "(adopt.)"
        and "step" not in strings["relationship"]
    )
    assert capsys.readouterr() == ("", "")


# ----------------------------------------------------------------
# privacy: the age follows birth parents, per parent


def aged(tree):
    """`tree` with Tom born in 1950 and everyone else without dates or death records but
    with a birth place that is not for the public. Only a birth parent can be aged from
    Tom's birth.
    """
    tree.people["tom"].birth, tree.people["tom"].death = year(1950), None
    for pid, p in tree.people.items():
        if pid != "tom":
            p.birth, p.death = Event(None, SECRETVILLE), None
    return tree


def aged_tree(father, mother):
    """Tom with parents John and Mary in one family f1, aged."""
    return aged(adoption_tree(father, mother))


def estimates(tree, prefer="birth"):
    return kincade.charts._birth_estimates(
        tree, plan_charts(tree, "tom", None, prefer), 2026
    )


@pytest.mark.parametrize("prefer", ["birth", "adoptive"])
def test_mary_is_aged_from_toms_birth_and_the_adoptive_john_is_not_in_a_built_tree(
    prefer,
):
    tree = aged_tree("adopted", "birth")
    est = estimates(tree, prefer)
    assert est["mary"] == 1925 and "john" not in est
    text = drawn(render_tom(tree, parents=prefer, exclude_private=True))
    # Mary's, over 100 years ago; John may be living
    assert text.count(f"bp. {SECRETVILLE}") == 1


@pytest.mark.parametrize("prefer", ["birth", "adoptive"])
def test_john_is_aged_and_the_foster_mary_is_not(prefer):
    tree = aged_tree("birth", "foster")
    est = estimates(tree, prefer)
    assert est["john"] == 1925 and "mary" not in est


def test_a_birth_parent_is_aged_and_an_other_parent_is_not():
    est = estimates(aged_tree("other", "birth"))
    assert est["mary"] == 1925 and "john" not in est


def test_two_birth_parents_are_both_aged():
    est = estimates(aged_tree("birth", "birth"))
    assert est["john"] == 1925 and est["mary"] == 1925


def test_two_non_birth_parents_are_neither_aged():
    assert not {"john", "mary"} & set(estimates(aged_tree("adopted", "foster")))


def test_a_stepfathers_age_can_come_from_nowhere_and_marys_comes_from_tom():
    tree = aged_tree("step", "birth")
    est = estimates(tree)
    assert est["mary"] == 1925 and "john" not in est
    assert not tree.is_birth_parent("john", "tom")


def test_is_birth_parent_is_per_parent_and_reads_every_family_of_the_child():
    tree = aged_tree("adopted", "birth")
    assert tree.is_birth_parent("mary", "tom") and not tree.is_birth_parent(
        "john", "tom"
    )
    assert not tree.is_birth_parent("tom", "mary") and not tree.is_birth_parent(
        "mary", "nobody"
    )
    assert not tree.is_birth_parent("nobody", "tom")
    tree = tom_tree(bob=True)  # f1 (John step, Mary birth), f2 (Bob, Mary: both birth)
    assert [tree.is_birth_parent(p, "tom") for p in ("bob", "mary", "john")] == [
        True,
        True,
        False,
    ]
    tree = tom_tree(ParentLink("f1", "birth", "step"))
    assert tree.is_birth_parent("john", "tom") and not tree.is_birth_parent(
        "mary", "tom"
    )


def test_a_person_who_is_a_birth_parent_in_one_family_and_not_in_another_is_aged_from_the_birth_link():
    tree = aged(
        tom_tree(ParentLink("f1", "adopted", "adopted"), ParentLink("f2"), bob=True)
    )
    # John and Mary adopted Tom, who is Bob and Mary's child by birth
    est = estimates(tree, "adoptive")
    assert tree.parent_ids("tom", "adoptive") == ("john", "mary")
    assert "john" not in est and est["mary"] == 1925  # Mary: a birth parent through f2


# ----------------------------------------------------------------
# calls without a mode; a tree built in code


def test_the_calls_without_a_mode_are_the_birth_mode():
    tree = tom_tree(bob=True)
    assert tree.parent_family("tom") is tree.parent_family("tom", "birth")
    assert tree.parent_ids("tom") == tree.parent_ids("tom", "birth")
    assert tree.parent_relationship("tom") == tree.parent_relationship("tom", "birth")


def test_a_link_to_a_family_not_in_the_tree_is_skipped():
    tree = tom_tree(ParentLink("f404"), ParentLink("f1", "step", "birth"))
    assert tree.parent_family("tom").id == "f1" and tree.parent_ids("tom") == (
        None,
        "mary",
    )


def test_a_tree_built_in_code_with_step_links_plans_and_renders_without_gedcom():
    tree = tom_tree(bob=True)
    tree.people["tom"].parents = [
        ParentLink("f1", "step", "birth"),
        ParentLink("f2", "birth", "step"),
    ]
    # f1 gives Mary (one birth parent), f2 gives Bob (one birth parent): a tie, so the
    # first family is drawn
    pdf = render_tom(tree)
    text = drawn(pdf)
    assert pdf.startswith(b"%PDF") and "Mary PELL" in text and "Tom PELL" in text
    assert "Bob PELL" not in text and "John PELL" not in text
    assert tree.parent_ids("tom") == (None, "mary")

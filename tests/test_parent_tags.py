"""The tags that give a child's relationship to each parent, as the GEDCOM reader reads
them, and what a chart draws.

Every source sets a ParentLink(family, father, mother), the child's relationship to the
family's father and mother:

  * `PEDI` under the person's `FAMC` applies to both parents: birth, adopted, foster,
    sealing and other (sealing counts as other), and the non-standard step and stepchild
    (Gramps writes stepchild), both read as step.
  * The adoption event: `1 ADOP` / `2 FAMC @F1@` / `3 ADOP HUSB|WIFE|BOTH`. That
    family's link is adopted for the father, the mother or both (BOTH, a missing `3
    ADOP` and anything else mean both).
  * `_FREL` and `_MREL`, one parent each, which Gramps writes under the person's `FAMC`
    and Family Tree Maker under the family's `CHIL` line: natural or birth, adopted,
    step or stepchild, foster, sponsored or family member (other).
  * Precedence, per parent: `_FREL`/`_MREL`, then `PEDI`, then the adoption event, then
    birth. A value that is not recognized (unknown, none, empty, anything else) says
    nothing and falls through to the next source, and in the end to birth. Values are
    case-insensitive and whitespace-trimmed.
  * a non-standard `CSTA` child status is not read.

Synthetic fixtures only.
"""

import pytest

import kincade.charts
import kincade.cli
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import _relationship_word, read_gedcom
from kincade.model import ParentLink

from conftest import (
    ADA,
    ADAM,
    KID,
    ged,
    kid_tree,
    parents_of,
    render_charts,
)
from pdfread import drawn

TOM, MARY, JOHN, BOB = "I1", "I2", "I3", "I4"
# John and Mary (married 1950, Reno), Bob and Mary (married 1940, Dayton)
F1, F2 = "F1", "F2"


def family(
    *extra, fam=F1, husb=JOHN, wife=MARY, year=1950, place="Reno", kid=(TOM, ())
):
    """A FAM record with the child `kid` = (record ID, lines under its CHIL), and any
    extra lines (more children...).
    """
    child, under = kid
    return [
        f"0 @{fam}@ FAM",
        f"1 HUSB @{husb}@",
        f"1 WIFE @{wife}@",
        "1 MARR",
        f"2 DATE {year}",
        f"2 PLAC {place}",
        f"1 CHIL @{child}@",
        *under,
        *extra,
    ]


def people(*, bob=False, tom_famc=(), tom_lines=()):
    """Tom (b. 1900) with his FAMC lines `tom_famc`, Mary, John and, with bob, Bob; all
    with a death date.
    """

    def person(xref, name, *lines):
        return [
            f"0 @{xref}@ INDI",
            f"1 NAME {name} /TURNER/",
            "1 BIRT",
            "2 DATE 1 JAN 1850",
            "1 DEAT",
            "2 DATE 1 JAN 1920",
            *lines,
        ]

    out = [
        *person(TOM, "Tom", *tom_famc, *tom_lines),
        *person(MARY, "Mary"),
        *person(JOHN, "John"),
    ]
    return out + (person(BOB, "Bob") if bob else [])


def tom_file(famc1=(), chil1=(), *, bob=False, famc2=(), tom_lines=(), kid_in_f2=True):
    """The Tom example: Tom's mother Mary is married to John. `famc1` are the lines
    under Tom's `FAMC @F1@` (the Gramps way to say what John is to him), `chil1` those
    under his `CHIL` line in F1 (the Family Tree Maker way). With bob, Bob and Mary's
    family F2 is in the file, with Tom as a child of it.
    """
    famc = [f"1 FAMC @{F1}@", *famc1] + (
        [f"1 FAMC @{F2}@", *famc2] if bob and kid_in_f2 else []
    )
    lines = [
        "0 HEAD",
        *people(bob=bob, tom_famc=famc, tom_lines=tom_lines),
        *family(kid=(TOM, chil1)),
    ]
    if bob:
        lines += family(
            fam=F2, husb=BOB, wife=MARY, year=1940, place="Dayton", kid=(TOM, ())
        )
    return read_gedcom(ged(*lines))


def link(tree, fam=F1, child=TOM):
    return next(pl for pl in tree.people[child].parents if pl.family == fam)


def pair(tree, fam=F1, child=TOM):
    """(father, mother): the child's relationships in its link to the family."""
    found = link(tree, fam, child)
    return found.father, found.mother


# ---------------------------------------------------------------- PEDI: both parents


@pytest.mark.parametrize(
    "pedi,expected",
    [
        ("step", "step"),
        ("STEP", "step"),
        ("Step", "step"),
        ("stepchild", "step"),
        ("Stepchild", "step"),
        ("  StepChild  ", "step"),
        ("birth", "birth"),
        ("adopted", "adopted"),
        ("foster", "foster"),
        ("sealing", "other"),
        ("other", "other"),
        ("  FOSTER ", "foster"),
    ],
)
def test_a_pedi_gives_the_same_relationship_to_both_parents(pedi, expected):
    tree = tom_file([f"2 PEDI {pedi}"])
    assert link(tree) == ParentLink(F1, expected, expected)


@pytest.mark.parametrize(
    "pedi", ["", "unknown", "natural", "step child", "step-child", "stepson"]
)
def test_a_pedi_that_is_not_one_of_the_words_says_nothing(pedi):
    assert link(tom_file([f"2 PEDI {pedi}"])) == ParentLink(F1, "birth", "birth")


def test_the_pedi_words_are_what_relationship_word_reads():
    assert [
        _relationship_word(w)
        for w in ("step", "Stepchild", "sealing", "adopted", "", "bogus")
    ] == ["step", "step", "other", "adopted", None, None]


def test_a_step_pedi_draws_neither_step_parent():
    tree = tom_file(["2 PEDI stepchild"])
    assert tree.parent_ids(TOM) == (None, None)
    text = drawn(render_charts(tree))
    assert "Tom TURNER" in text and not [t for t in text if "Mary" in t or "John" in t]


# ---------------------------------------------------------------- the adoption event


@pytest.mark.parametrize(
    "which,expected",
    [
        ("HUSB", ("adopted", "birth")),
        ("WIFE", ("birth", "adopted")),
        ("BOTH", ("adopted", "adopted")),
        ("husb", ("adopted", "birth")),
        (" Wife ", ("birth", "adopted")),
        ("both", ("adopted", "adopted")),
        ("", ("adopted", "adopted")),  # a `3 ADOP` with no value
        (
            "FATHER",
            ("adopted", "adopted"),
        ),  # not one of the three: the event names the family, so both
    ],
)
def test_the_adoption_event_names_the_parent_or_parents_who_adopted(which, expected):
    tree = tom_file(tom_lines=["1 ADOP", f"2 FAMC @{F1}@", f"3 ADOP {which}"])
    assert pair(tree) == expected


def test_an_adoption_event_with_no_adop_line_under_its_famc_means_both_parents():
    tree = tom_file(tom_lines=["1 ADOP", f"2 FAMC @{F1}@"])
    assert pair(tree) == ("adopted", "adopted")


def test_an_adoption_event_with_a_date_and_a_place_is_read_the_same():
    tree = tom_file(
        tom_lines=[
            "1 ADOP",
            "2 DATE 9 JUL 1950",
            "2 PLAC Reno",
            f"2 FAMC @{F1}@",
            "3 ADOP HUSB",
        ]
    )
    assert pair(tree) == ("adopted", "birth")


def test_an_adoption_event_that_names_no_family_changes_nothing():
    tree = tom_file(tom_lines=["1 ADOP", "2 DATE 1950", "2 NOTE adopted at birth"])
    # some programs write an ADOP event with no FAMC under it
    assert pair(tree) == ("birth", "birth")


def test_an_adoption_event_for_a_family_the_person_has_no_famc_for_changes_nothing():
    tree = tom_file(
        bob=True, tom_lines=["1 ADOP", f"2 FAMC @{F2}@", "3 ADOP BOTH"], kid_in_f2=False
    )
    # no link is made for F2 out of the event alone
    assert tree.people[TOM].parents == [ParentLink(F1)]


def test_only_the_family_the_adoption_event_names_is_adopted():
    tree = tom_file(bob=True, tom_lines=["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP HUSB"])
    assert pair(tree, F1) == ("adopted", "birth") and pair(tree, F2) == (
        "birth",
        "birth",
    )


def test_two_adoption_events_for_one_family_add_up():
    tree = tom_file(
        tom_lines=[
            "1 ADOP",
            f"2 FAMC @{F1}@",
            "3 ADOP HUSB",
            "1 ADOP",
            f"2 FAMC @{F1}@",
            "3 ADOP WIFE",
        ]
    )
    assert pair(tree) == ("adopted", "adopted")


# ----------------------------------------------------------------
# _FREL and _MREL: Gramps and FTM


VALUES = [
    ("Natural", "birth"),
    ("natural", "birth"),
    ("NATURAL", "birth"),
    ("Birth", "birth"),
    ("birth", "birth"),
    ("Adopted", "adopted"),
    ("ADOPTED", "adopted"),
    ("Step", "step"),
    ("step", "step"),
    ("Stepchild", "step"),
    ("STEPCHILD", "step"),
    ("Foster", "foster"),
    ("foster", "foster"),
    ("Sponsored", "other"),
    ("sponsored", "other"),
    ("Family member", "other"),
    ("FAMILY MEMBER", "other"),
    ("  Step  ", "step"),
    ("Family  member", "other"),
]


@pytest.mark.parametrize("text,expected", VALUES)
def test_gramps_writes_frel_and_mrel_under_famc_one_parent_each(text, expected):
    both_ways = (
        tom_file([f"2 _FREL {text}", "2 _MREL Adopted"]),
        tom_file(["2 _FREL Foster", f"2 _MREL {text}"]),
    )
    assert pair(both_ways[0]) == (expected, "adopted")
    assert pair(both_ways[1]) == ("foster", expected)


@pytest.mark.parametrize("text,expected", VALUES)
def test_family_tree_maker_writes_frel_and_mrel_under_the_chil_line(text, expected):
    assert pair(tom_file(chil1=[f"2 _FREL {text}", "2 _MREL Adopted"])) == (
        expected,
        "adopted",
    )
    assert pair(tom_file(chil1=["2 _FREL Foster", f"2 _MREL {text}"])) == (
        "foster",
        expected,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Unknown",
        "unknown",
        "None",
        "none",
        "",
        "  ",
        "Guardian",
        "Related",
        "Sealed",
        "Private",
        "Nonsense",
        "Natural Child",
        "Step-Child",
    ],
)
@pytest.mark.parametrize("style", ["gramps", "ftm"])
def test_an_unknown_none_empty_or_unrecognized_value_is_birth(text, style):
    lines = [f"2 _FREL {text}", f"2 _MREL {text}"]
    tree = tom_file(lines) if style == "gramps" else tom_file(chil1=lines)
    assert pair(tree) == ("birth", "birth")


def test_the_gramps_example_a_stepchild_of_the_father_and_a_birth_child_of_the_mother():
    tree = tom_file(["2 _FREL Stepchild", "2 _MREL Birth"])
    assert link(tree) == ParentLink(F1, "step", "birth")


def test_the_family_tree_maker_example_a_natural_child_of_the_father_and_a_step_child_of_the_mother():
    tree = tom_file(chil1=["2 _FREL Natural", "2 _MREL Step"])
    assert link(tree) == ParentLink(F1, "birth", "step")


def test_frel_alone_leaves_the_mother_to_the_other_sources_and_in_the_end_birth():
    assert pair(tom_file(["2 _FREL Step"])) == ("step", "birth")
    assert pair(tom_file(chil1=["2 _MREL Step"])) == ("birth", "step")
    assert pair(tom_file(["2 _FREL Step", "2 PEDI adopted"])) == ("step", "adopted")


def test_a_chil_lines_frel_belongs_to_that_child_only():
    ann = ["0 @I9@ INDI", "1 NAME Ann /TURNER/", f"1 FAMC @{F1}@"]
    fam = family(
        "1 CHIL @I9@", "2 _FREL Step", "2 _MREL Step", kid=(TOM, ["2 _MREL Adopted"])
    )
    tree = read_gedcom(ged("0 HEAD", *people(tom_famc=[f"1 FAMC @{F1}@"]), *ann, *fam))
    assert pair(tree, child=TOM) == ("birth", "adopted")
    # the lines under Ann's CHIL line are hers
    assert pair(tree, child="I9") == ("step", "step")


def test_the_family_record_may_come_before_or_after_the_person():
    body = [*people(tom_famc=[f"1 FAMC @{F1}@"])]
    fam = family(kid=(TOM, ["2 _FREL Step"]))
    after = read_gedcom(ged("0 HEAD", *body, *fam))
    before = read_gedcom(ged("0 HEAD", *fam, *body))
    assert pair(after) == pair(before) == ("step", "birth")


def test_a_chil_line_for_a_child_with_no_famc_to_that_family_makes_no_link():
    tree = read_gedcom(ged("0 HEAD", *people(), *family(kid=(TOM, ["2 _FREL Step"]))))
    assert tree.people[TOM].parents == []
    assert tree.parent_ids(TOM) == (None, None)


# ---------------------------------------------------------------- precedence


def test_frel_and_mrel_beat_pedi_for_their_own_parent_only():
    tree = tom_file(["2 PEDI adopted", "2 _FREL Birth"])
    # the father from _FREL, the mother from PEDI
    assert pair(tree) == ("birth", "adopted")
    tree = tom_file(["2 PEDI birth", "2 _FREL Step", "2 _MREL Foster"])
    assert pair(tree) == ("step", "foster")


def test_pedi_beats_the_adoption_event():
    tom_adop = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP BOTH"]
    assert pair(tom_file(["2 PEDI birth"], tom_lines=tom_adop)) == ("birth", "birth")
    husb = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP HUSB"]
    assert pair(tom_file(["2 PEDI foster"], tom_lines=husb)) == ("foster", "foster")
    assert pair(tom_file(["2 PEDI stepchild"], tom_lines=tom_adop)) == ("step", "step")


def test_the_adoption_event_beats_nothing_and_a_pedi_that_says_nothing():
    tom_adop = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP WIFE"]
    assert pair(tom_file(tom_lines=tom_adop)) == ("birth", "adopted")
    assert pair(tom_file(["2 PEDI nonsense"], tom_lines=tom_adop)) == (
        "birth",
        "adopted",
    )
    assert pair(tom_file(["2 PEDI"], tom_lines=tom_adop)) == ("birth", "adopted")


def test_frel_and_mrel_beat_the_adoption_event_too():
    tree = tom_file(
        ["2 _FREL Natural"], tom_lines=["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP BOTH"]
    )
    # _FREL says birth for the father; the event gives the mother
    assert pair(tree) == ("birth", "adopted")


def test_an_unrecognized_frel_falls_through_to_pedi_then_the_event_then_birth():
    assert pair(tom_file(["2 _FREL Unknown", "2 PEDI foster"])) == ("foster", "foster")
    husb = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP HUSB"]
    assert pair(tom_file(["2 _FREL Unknown"], tom_lines=husb)) == ("adopted", "birth")
    assert pair(tom_file(["2 _FREL Unknown", "2 _MREL None"])) == ("birth", "birth")


def test_the_famc_level_value_beats_the_chil_level_one():
    tree = tom_file(["2 _FREL Step"], chil1=["2 _FREL Adopted", "2 _MREL Foster"])
    # the father from the FAMC, the mother (not on the FAMC) from the CHIL
    assert pair(tree) == ("step", "foster")


def test_an_unrecognized_famc_value_lets_the_chil_value_speak():
    assert pair(tom_file(["2 _FREL Unknown"], chil1=["2 _FREL Adopted"])) == (
        "adopted",
        "birth",
    )


def test_two_famc_lines_for_one_family_give_both_links_the_one_relationship():
    # the first says nothing, the second has the _MREL
    famc = [f"1 FAMC @{F1}@", f"1 FAMC @{F1}@", "2 _MREL Step"]
    tree = read_gedcom(ged("0 HEAD", *people(tom_famc=famc), *family()))
    assert [(pl.father, pl.mother) for pl in tree.people[TOM].parents] == [
        ("birth", "step")
    ] * 2


# ----------------------------------------------------------------
# the Tom example, read from files


@pytest.mark.parametrize("style", ["gramps", "ftm"])
def test_toms_only_family_is_his_mother_and_her_husband_who_is_his_stepfather(style):
    tree = (
        tom_file(["2 _FREL Stepchild", "2 _MREL Birth"])
        if style == "gramps"
        else tom_file(chil1=["2 _FREL Step", "2 _MREL Natural"])
    )
    assert tree.parent_ids(TOM) == (None, MARY)
    text = drawn(render_charts(tree))
    assert "Mary TURNER" in text and "Tom TURNER" in text
    assert not [t for t in text if "John" in t]
    assert not [t for t in text if "(" in t]  # no "(step)" and no note of any kind
    # John and Mary's marriage is not drawn either
    assert "m. 1950" not in text and "mp. Reno" not in text
    assert plan_charts(tree, TOM)[0].continuations == {}


@pytest.mark.parametrize("style", ["gramps", "ftm"])
def test_with_bob_in_the_file_his_family_gives_toms_father(style):
    kwargs = (
        {"famc1": ["2 _FREL Stepchild", "2 _MREL Birth"]}
        if style == "gramps"
        else {"chil1": ["2 _FREL Step", "2 _MREL Natural"]}
    )
    tree = tom_file(**kwargs, bob=True)
    for prefer in ("birth", "adoptive"):
        assert tree.parent_ids(TOM, prefer) == (BOB, MARY)
    text = drawn(render_charts(tree))
    assert (
        "Bob TURNER" in text
        and "Mary TURNER" in text
        and not [t for t in text if "John" in t]
    )
    # Bob and Mary's marriage, not John and Mary's
    assert "m. 1940" in text and "m. 1950" not in text
    assert not [t for t in text if "(" in t]


def test_with_bob_in_the_file_the_order_of_the_families_does_not_matter():
    tree = tom_file(["2 _FREL Step"], bob=True)
    tree.people[TOM].parents.reverse()
    assert tree.parent_ids(TOM) == (BOB, MARY)


def test_no_empty_leaves_out_the_blanked_fathers_box_and_keeps_the_mothers():
    tree = tom_file(chil1=["2 _FREL Step"])
    text = drawn(render_charts(tree, empty_boxes=False))
    assert "2" not in text and "3" in text  # no box 2; Mary is box 3
    assert not [t for t in text if "John" in t]
    text = drawn(render_charts(tree, empty_boxes=True))
    # the empty box is drawn, without a name or a marriage
    assert "2" in text and "3" in text
    assert "m. 1950" not in text and not [t for t in text if "John" in t]


def test_no_empty_through_the_command_line(tmp_path, drawn_charts):
    path = tmp_path / "tom.ged"
    path.write_bytes(
        ged(
            "0 HEAD",
            *people(tom_famc=[f"1 FAMC @{F1}@", "2 _FREL Stepchild"]),
            *family(),
        )
    )
    out = tmp_path / "x.pdf"
    assert (
        kincade.cli.main(
            [
                str(path),
                "--root",
                TOM,
                "--no-empty",
                "--generations",
                "2",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    charts, opts = drawn_charts[-1]
    assert (
        opts.empty_boxes is False
        and charts[0].slots[2] is None
        and charts[0].slots[3] == MARY
    )


def test_a_blanked_parent_has_no_index_entry():
    tree = tom_file(["2 _FREL Step"])
    charts = plan_charts(tree, TOM)
    index = kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    )
    assert [line.split(",")[1].split()[0] for line in index] == ["Mary", "Tom"]
    assert not [line for line in index if "John" in line]


# ----------------------------------------------------------------
# a step-parent adoption


STEP_ADOPTION = {
    "gramps": {"famc1": ["2 _FREL Adopted", "2 _MREL Birth"]},
    "ftm": {"chil1": ["2 _FREL Adopted", "2 _MREL Natural"]},
    "event": {"tom_lines": ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP HUSB"]},
}


@pytest.mark.parametrize("style", STEP_ADOPTION)
def test_a_child_adopted_by_his_mothers_husband(style):
    tree = tom_file(**STEP_ADOPTION[style])
    assert link(tree) == ParentLink(F1, "adopted", "birth")
    # the only family: drawn in either mode, with both parents
    for prefer in ("birth", "adoptive"):
        assert tree.parent_ids(TOM, prefer) == (JOHN, MARY)
    text = drawn(render_charts(tree))
    # one drawn parent is adopted, the other is a birth parent: one note
    assert "Tom TURNER (adopted)" in text
    assert "John TURNER" in text and "Mary TURNER" in text and "m. 1950" in text


@pytest.mark.parametrize("style", STEP_ADOPTION)
def test_with_his_birth_father_in_the_file_the_default_is_birth_and_adoptive_is_the_adoption(
    style,
):
    tree = tom_file(**STEP_ADOPTION[style], bob=True)
    assert tree.parent_ids(TOM) == (BOB, MARY) and tree.parent_ids(TOM, "adoptive") == (
        JOHN,
        MARY,
    )
    birth = drawn(render_charts(tree))
    adoptive = drawn(render_charts(tree, parents="adoptive"))
    # no note: birth parents
    assert (
        "Bob TURNER" in birth and "John TURNER" not in birth and "Tom TURNER" in birth
    )
    assert (
        "John TURNER" in adoptive
        and "Bob TURNER" not in adoptive
        and "Tom TURNER (adopted)" in adoptive
    )


# ---------------------------------------------------------------- privacy, per parent


def aged_file(famc1=(), chil1=(), tom_lines=()):
    """Tom born 1950; Mary and John have a birth place that is not for the public and no
    dates at all.
    """
    lines = [
        "0 HEAD",
        "0 @I1@ INDI",
        "1 NAME Tom /TURNER/",
        "1 BIRT",
        "2 DATE 1950",
        f"1 FAMC @{F1}@",
        *famc1,
        *tom_lines,
        "0 @I2@ INDI",
        "1 NAME Mary /TURNER/",
        "1 BIRT",
        "2 PLAC Mary's secret place",
        "0 @I3@ INDI",
        "1 NAME John /TURNER/",
        "1 BIRT",
        "2 PLAC John's secret place",
        *family(kid=(TOM, chil1)),
    ]
    return read_gedcom(ged(*lines))


def estimates(tree, prefer="birth"):
    return kincade.charts._birth_estimates(
        tree, plan_charts(tree, TOM, None, prefer), 2026
    )


@pytest.mark.parametrize("style", STEP_ADOPTION)
@pytest.mark.parametrize("prefer", ["birth", "adoptive"])
def test_mary_is_aged_from_toms_birth_and_the_adoptive_john_is_not_in_a_gedcom_file(
    style, prefer
):
    tree = aged_file(**STEP_ADOPTION[style])
    est = estimates(tree, prefer)
    assert est[MARY] == 1925 and JOHN not in est
    text = drawn(render_charts(tree, parents=prefer, exclude_private=True))
    assert "bp. Mary's secret place" in text and "bp. John's secret place" not in text
    shown = drawn(render_charts(tree, parents=prefer))
    # without --exclude-private he is drawn, so the line above is privacy
    assert "bp. John's secret place" in shown


def test_and_the_other_way_round_the_father_is_aged_and_the_adoptive_mother_is_not():
    tree = aged_file(famc1=["2 _FREL Natural", "2 _MREL Adopted"])
    est = estimates(tree)
    assert est[JOHN] == 1925 and MARY not in est


def test_a_stepfather_is_not_drawn_and_so_not_aged_but_mary_is():
    tree = aged_file(famc1=["2 _FREL Step", "2 _MREL Birth"])
    est = estimates(tree)
    assert est[MARY] == 1925 and JOHN not in est
    text = drawn(render_charts(tree, exclude_private=True))
    assert "bp. Mary's secret place" in text and not [t for t in text if "John" in t]


F3 = "F3"  # Carl+Cora (1970), the third family of kid_tree()


# ----------------------------------------------------------------
# reading the relationship


@pytest.mark.parametrize(
    "text",
    [
        "Adopted",
        "adopted",
        "Foster",
        "Step",
        "Stepchild",
        "Other",
        "Twin",
        "Died as Infant",
        "Stillborn",
        "Illegitimate",
    ],
)
def test_a_csta_status_is_ignored_so_the_child_reads_as_a_birth_child(text):
    tree = kid_tree([(F1, "")], status={F1: text})
    assert tree.people[KID].parents == [ParentLink(F1, "birth", "birth")]


def test_the_csta_record_is_ignored_wherever_it_is_and_whether_it_is_a_pointer_or_inline():
    # a CSTA record at the end of the file, then a CSTA text on the CHIL line
    for inline in (False, True):
        tree = kid_tree([(F1, "")], status={F1: "Adopted"}, inline=inline)
        assert pair(tree, F1, KID) == ("birth", "birth")


def test_a_file_that_records_adoption_only_with_csta_draws_the_first_family_as_a_birth_family():
    tree = kid_tree([(F1, ""), (F2, "")], status={F1: "Adopted"})
    assert parents_of(tree) == (ADAM, ADA) and parents_of(tree, prefer="adoptive") == (
        ADAM,
        ADA,
    )
    for mode in ("birth", "adoptive"):
        assert "(adopted)" not in " ".join(drawn(render_charts(tree, parents=mode)))


def test_the_relationship_is_per_child_and_family():
    tree = kid_tree([(F1, "adopted"), (F2, "")])
    assert pair(tree, F1, KID) == ("adopted", "adopted")
    assert pair(tree, F2, KID) == ("birth", "birth")


def test_the_pedi_is_read_whatever_the_csta_status_says():
    for pedi, status, expected in [
        ("foster", "Adopted", ("foster", "foster")),
        ("birth", "Adopted", ("birth", "birth")),
        ("adopted", "Twin", ("adopted", "adopted")),
        ("unheard of", "Adopted", ("birth", "birth")),
    ]:
        assert pair(kid_tree([(F1, pedi)], status={F1: status}), F1, KID) == expected


def test_a_csta_pointer_to_a_missing_record_is_unmarked():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 FAMC @F1@", "0 @F1@ FAM", "1 CHIL @I1@", "2 CSTA @C404@")
    )
    assert pair(tree, "F1", "I1") == ("birth", "birth")


def test_a_csta_status_gives_no_note():
    tree = kid_tree([(F1, ""), (F2, "")], status={F1: "Adopted", F2: "Foster"})
    assert not any(
        "(" in t and "KID" in t for t in drawn(render_charts(tree, parents="adoptive"))
    )

"""The neutral data model (kincade.model): dates as structure, events, parent links with
a plain relationship to each parent, and trees built in code with no GEDCOM. The GEDCOM
reader parses dates once (gedcom.parse_date); formatting, the index and the living
estimate read the structure.

Synthetic fixtures only.
"""

import dataclasses

import pytest

from kincade.charts import living_checker, plan_charts
from kincade.gedcom import parse_date, read_gedcom
from kincade.model import Date, Day, Event, Family, ParentLink, Person, Tree
from kincade.pdf import Options, render_pdf

from conftest import TODAY, ged

# ---------------------------------------------------------------- the classes


def test_a_date_needs_a_known_form_and_quality():
    with pytest.raises(ValueError, match=r"Date\.form"):
        Date("roughly", Day(1900))
    with pytest.raises(ValueError, match=r"Date\.quality"):
        Date("exact", Day(1900), quality="guessed")
    assert Date("text", text="spring").start is None  # structure is optional


def test_a_day_may_lack_parts_but_the_month_must_be_a_month():
    assert Day(1900) == Day(year=1900, month=None, day=None, dual_year=None)
    assert Day(month=5, day=19).year is None  # "19 MAY" in a file that gives no year
    with pytest.raises(ValueError, match=r"Day\.month"):
        Day(1900, 13)


def test_an_event_is_filled_by_a_date_or_a_place():
    assert not Event().filled()
    assert Event(Date("exact", Day(1900))).filled() and Event(place="Dayton").filled()
    # "()": a date record with nothing in it is a date record
    assert Event(parse_date("()")).filled()


def test_the_people_and_families_have_the_neutral_fields_and_nothing_of_gedcom():
    person_fields = {f.name for f in dataclasses.fields(Person)}
    assert person_fields == {
        "id",
        "given",
        "surname",
        "prefix",
        "suffix",
        "birth",
        "death",
        "christenings",
        "burials",
        "cremations",
        "parents",
        "families",
        "living",
    }
    assert {f.name for f in dataclasses.fields(Family)} == {
        "id",
        "father",
        "mother",
        "marriage",
        "children",
    }
    p = Person("I1")
    assert (
        p.birth is None
        and p.death is None
        and p.living is None
        and p.parents == []
        and p.families == []
    )


# ----------------------------------------------------------------
# reading events and links from GEDCOM


def test_a_missing_birth_is_none_and_an_empty_death_record_means_died():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 DEAT",
            "0 @I2@ INDI",
            "1 NAME C /D/",
            "1 BIRT Y",
        )
    )
    a, c = tree.people["I1"], tree.people["I2"]
    assert a.birth is None and a.death == Event()  # died, nothing more known
    # "1 BIRT Y": a record with no date or place
    assert c.birth == Event() and c.death is None


def test_christenings_burials_and_cremations_are_kept_in_order():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 BAPM",
            "2 DATE 1801",
            "1 CHR",
            "2 DATE 1800",
            "1 BURI",
            "2 DATE 1850",
            "1 BURI",
            "2 PLAC Dayton",
            "1 CREM",
            "2 DATE 1851",
        )
    )
    p = tree.people["I1"]
    # CHR, then BAPM
    assert [e.date for e in p.christenings] == [
        Date("exact", Day(1800)),
        Date("exact", Day(1801)),
    ]
    assert p.burials == [Event(Date("exact", Day(1850))), Event(None, "Dayton")]
    assert p.cremations == [Event(Date("exact", Day(1851)))]


def test_families_have_a_father_and_a_mother_and_people_the_families_they_head():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 FAMS @F1@",
            "1 FAMS @F2@",
            "0 @F1@ FAM",
            "1 HUSB @I1@",
            "1 MARR",
            "2 DATE 1900",
            "0 @F2@ FAM",
            "1 WIFE @I1@",
        )
    )
    assert tree.people["I1"].families == ["F1", "F2"]
    assert (tree.families["F1"].father, tree.families["F1"].mother) == ("I1", "")
    assert tree.families["F1"].marriage == Event(Date("exact", Day(1900)))
    assert tree.families["F2"].marriage is None and tree.families["F2"].mother == "I1"


def test_parent_links_keep_the_source_order_and_a_family_twice_has_one_relationship():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 FAMC @F2@",
            "1 FAMC @F1@",
            "2 PEDI adopted",
            "1 FAMC @F2@",
            "2 PEDI foster",
            "0 @F1@ FAM",
            "1 CHIL @I1@",
            "0 @F2@ FAM",
            "1 CHIL @I1@",
        )
    )
    assert tree.people["I1"].parents == [
        ParentLink("F2", "foster", "foster"),
        ParentLink("F1", "adopted", "adopted"),
        ParentLink("F2", "foster", "foster"),
    ]


# ---------------------------------------------------------------- a tree built in code


def hand_built_tree():
    """Three generations with no GEDCOM: Ann (born 1990, living), her father Bob
    (1960-2010) and grandfather Cy.
    """
    return Tree(
        people={
            "ann": Person(
                "ann",
                given="Ann",
                surname="Pell",
                parents=[ParentLink("f1", "birth")],
                birth=Event(Date("exact", Day(1990, 4, 2)), "Dayton, Ohio"),
            ),
            "bob": Person(
                "bob",
                given="Bob",
                surname="Pell",
                birth=Event(Date("exact", Day(1960))),
                death=Event(Date("exact", Day(2010))),
                parents=[ParentLink("f2", "adopted", "adopted")],
                families=["f1"],
            ),
            "cy": Person(
                "cy",
                given="Cy",
                surname="Pell",
                birth=Event(Date("about", Day(1930))),
                death=Event(),
                families=["f2"],
            ),
        },
        families={
            "f1": Family(
                "f1",
                father="bob",
                marriage=Event(Date("exact", Day(1988)), "Reno"),
                children=["ann"],
            ),
            "f2": Family("f2", father="cy", children=["bob"]),
        },
    )


def test_a_tree_built_in_code_plans_and_renders_without_gedcom():
    tree = hand_built_tree()
    charts = plan_charts(tree, "ann")
    assert [charts[0].slots[pos] for pos in (1, 2, 3, 4)] == ["ann", "bob", None, "cy"]
    pdf = render_pdf(charts, tree, Options(today=TODAY, fonts="base14", compress=False))
    assert (
        pdf.startswith(b"%PDF") and b"(Ann PELL)" in pdf and b"(b. 2 Apr 1990)" in pdf
    )
    assert b"(bp. Dayton, Ohio)" in pdf and b"(m. 1988)" in pdf and b"(mp. Reno)" in pdf
    assert b"(b. abt 1930)" in pdf  # Cy's date as the structure prints it


def test_the_relationship_note_follows_the_parent_link_of_a_tree_built_in_code():
    tree = hand_built_tree()  # Bob belongs to his family f2 as an adopted child
    pdf = render_pdf(
        plan_charts(tree, "ann"),
        tree,
        Options(today=TODAY, fonts="base14", compress=False),
    )
    assert b"(Bob PELL \\(adopted\\))" in pdf and b"(Ann PELL)" in pdf


def test_the_estimate_of_who_is_living_works_on_a_tree_built_in_code():
    tree = hand_built_tree()
    is_living = living_checker(tree, plan_charts(tree, "ann"), 2026)
    assert is_living("ann") is True  # born 1990, no death record
    assert is_living("bob") is False  # died
    assert is_living("cy") is False  # a death record with nothing in it means died


def test_a_persons_living_overrides_the_estimate_for_that_person_only():
    tree = hand_built_tree()
    tree.people["ann"].living = False  # the caller knows better: she is not living
    tree.people["bob"].living = True  # ... and Bob is (whatever his death record says)
    charts = plan_charts(tree, "ann")
    is_living = living_checker(tree, charts, 2026)
    assert (is_living("ann"), is_living("bob"), is_living("cy")) == (False, True, False)
    tree.people["ann"].living = None  # None keeps the estimate
    assert living_checker(tree, charts, 2026)("ann") is True


# ----------------------------------------------------------------
# the link: one relationship per parent


def test_a_parent_link_has_a_relationship_to_the_father_and_one_to_the_mother_both_birth_by_default():
    link = ParentLink("f1")
    assert (link.family, link.father, link.mother) == ("f1", "birth", "birth")
    assert ParentLink("f1", "step", "birth") == ParentLink(
        "f1", father="step", mother="birth"
    )
    assert ParentLink("f1", mother="foster") == ParentLink("f1", "birth", "foster")


@pytest.mark.parametrize("word", ["birth", "adopted", "foster", "step", "other"])
def test_each_parent_takes_one_of_the_five_words(word):
    assert (
        ParentLink("f1", word, "birth").father == word
        and ParentLink("f1", "birth", word).mother == word
    )


@pytest.mark.parametrize("bad", ["", "sealing", "Birth", "stepchild", "natural"])
def test_a_word_outside_the_five_fails_where_it_is_made_and_names_the_field(bad):
    with pytest.raises(ValueError, match=r"ParentLink\.father"):
        ParentLink("f1", bad)
    with pytest.raises(ValueError, match=r"ParentLink\.mother"):
        ParentLink("f1", "birth", bad)

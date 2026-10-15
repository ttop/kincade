"""Privacy: who counts as possibly living, and what is hidden for them."""

import pytest

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options, render_pdf

from conftest import (
    FIX,
    TODAY,
    ged,
    render,
    render_charts,
)
from pdfread import drawn

# ---------------------------------------------------------------- privacy


def test_living_estimation_uses_descendants():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /K/",
            "1 BIRT",
            "2 DATE 2000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /K/",
            "1 FAMC @F2@",  # est 1975
            "0 @I3@ INDI",
            "1 NAME Mum /K/",
            "1 BIRT",
            "2 DATE 1976",
            "1 DEAT Y",  # dead
            "0 @I4@ INDI",
            "1 NAME Gramps /K/",
            "1 FAMC @F4@",  # est 1950
            "0 @I5@ INDI",
            "1 NAME Gran /K/",
            "0 @I6@ INDI",
            "1 NAME Great /K/",
            "1 BURI",
            "2 PLAC Churchyard",  # buried
            "0 @I8@ INDI",
            "1 NAME Old /K/",
            "1 FAMC @F8@",  # est 1925
            "0 @I9@ INDI",
            "1 NAME Unknown /K/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "1 WIFE @I5@",
            "0 @F4@ FAM",
            "1 HUSB @I8@",
            "1 WIFE @I9@",
            "0 @F8@ FAM",
            "1 HUSB @I6@",
        )
    )
    charts = plan_charts(tree, "I1")
    living = kincade.charts.living_checker(tree, charts, 2026)
    assert [living(f"I{n}") for n in (1, 2, 3, 4, 5, 6, 8, 9)] == [
        True,  # born 2000
        True,  # no data: 2000 - 25 = 1975
        False,  # DEAT present
        True,  # 1975 - 25 = 1950
        True,  # as the mother of I2: 1950
        False,  # BURI present
        False,  # 1925: one year past the 100-year line
        False,
    ]


def test_private_redacts_living_names_and_details_but_keeps_labels(pedigree):
    pdf = render(pedigree, exclude_private=True)
    assert b"Jane ASHFORD" not in pdf and b"Mary McCLURE" not in pdf
    assert b"(Living)" in pdf
    for hidden in (
        b"14 Feb 1980",
        b"Springfield",
        b"12 Jun 1975",
        b"9 Sep 1952",
        b"5 Jun 2005",
        b"Peoria",
    ):
        # living people, and marriages with a living spouse
        assert hidden not in pdf, hidden
    # only William's (dead) birth and death places remain
    assert pdf.count(b"Akron, Ohio") == 2
    assert b"(b.)" in pdf and b"(m.)" in pdf and b"(mp.)" in pdf  # labels stay
    assert b"(b. 3 Mar 1950)" in pdf  # John is dead: shown
    assert b"(b. 1 Jun 1900)" in pdf
    assert b"ASHFORD, Jane" not in pdf  # living people are omitted from the index
    # en dash: cp1252 0x96, octal-escaped
    assert b"ASHFORD, John \\(b. 1950 \\226 d. 2020\\), 1-2" in pdf


def test_not_private_shows_everything(pedigree):
    pdf = render(pedigree)
    assert b"(b. 14 Feb 1980)" in pdf and b"(m. 12 Jun 1975)" in pdf


# ---------------------------------------------------------------- privacy estimator


def test_estimate_does_not_add_a_generation_at_a_continuation_boundary():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME R /X/",
            "1 BIRT",
            "2 DATE 2000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME F2 /X/",
            "1 FAMC @F2@",
            "0 @I4@ INDI",
            "1 NAME F4 /X/",
            "1 FAMC @F4@",
            "0 @I8@ INDI",
            "1 NAME F8 /X/",
            "1 FAMC @F8@",  # chart 1 position 8: roots chart 2
            "0 @I16@ INDI",
            "1 NAME F16 /X/",
            "1 FAMC @F16@",  # chart 2 position 2
            "0 @I32@ INDI",
            "1 NAME F32 /X/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "0 @F4@ FAM",
            "1 HUSB @I8@",
            "0 @F8@ FAM",
            "1 HUSB @I16@",
            "0 @F16@ FAM",
            "1 HUSB @I32@",
        )
    )
    charts = plan_charts(tree, "I1")
    assert charts[1].slots[1] == "I8" and charts[1].slots[2] == "I16"
    est = kincade.charts._birth_estimates(tree, charts, 2026)
    assert est["I8"] == 2000 - 3 * 25
    # the continuation root IS the person at chart 1 position 8
    assert est["I16"] == 2000 - 4 * 25
    assert est["I32"] == 2000 - 5 * 25


def test_estimate_considers_every_descendant_path_in_a_collapsed_pedigree():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Cora /D/",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Ed /D/",
            "1 BIRT",
            "2 DATE 1960",
            "1 FAMC @F2@",
            "0 @I3@ INDI",
            "1 NAME Fay /D/",
            "1 BIRT",
            "2 DATE 1990",
            "1 FAMC @F3@",
            "0 @I4@ INDI",
            "1 NAME Lou /D/",  # undated, sits at positions 4 and 6
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
            "0 @F3@ FAM",
            "1 HUSB @I4@",
        )
    )
    charts = plan_charts(tree, "I1")
    assert charts[0].slots[4] == charts[0].slots[6] == "I4"
    est = kincade.charts._birth_estimates(tree, charts, 2026)
    # the youngest dated child path wins: the most conservative estimate
    assert est["I4"] == 1990 - 25


def test_estimate_is_the_most_conservative_over_all_dated_descendants():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME B /Z/",
            "1 BIRT",
            "2 DATE 1990",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME A /Z/",
            "1 BIRT",
            "2 DATE 1900",
            "1 FAMC @F2@",  # a dated parent, old
            "0 @I4@ INDI",
            "1 NAME X /Z/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
        )
    )
    est = kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)
    assert est["I2"] == 1900  # own birth year wins
    # 1940, not the nearest descendant's 1875
    assert est["I4"] == max(1900 - 25, 1990 - 2 * 25)


def test_estimate_survives_a_data_loop():
    tree = read_gedcom(FIX / "cycle.ged")
    est = kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)
    assert est == {"I1": 1900, "I2": 1870}


# ----------------------------------------------------------------
# generations and privacy


@pytest.mark.parametrize("generations", [2, 3, 4, 5, 6, None])
def test_a_drawn_persons_privacy_does_not_depend_on_generations(generations):
    """Father is drawn at position 2 and again at generation 6 (father of Young, born
    1990). Young is drawn from N=5 and Father's generation-6 box from N=6, so for N=2 to
    5 a limited run that estimated from the drawn boxes alone would take Father's
    estimate from Root (born 1950): 1925, not living. The unlimited run gives 1965
    (Young), which is living, so his birthplace must stay hidden at every limit.
    """
    tree = read_gedcom(FIX / "deep_collapse.ged")
    pdf = render(tree, generations=generations, exclude_private=True)
    assert b"Father DEEP" not in pdf
    assert b"(Living)" in pdf  # the occupied boxes remain
    assert b"Akron, Ohio" not in pdf


# ---------------------------------------------------------------- people with no dates


def test_a_person_with_no_dates_at_all_counts_as_living_unless_dead_or_buried():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Nobody /Known/",
            "0 @I2@ INDI",
            "1 NAME Dead /Known/",
            "1 DEAT",
            "0 @I3@ INDI",
            "1 NAME Buried /Known/",
            "1 BURI",
            "0 @I4@ INDI",
            "1 NAME Old /Known/",
            "1 BIRT",
            "2 DATE 1800",
        )
    )
    chart = dict.fromkeys(range(1, 16))
    charts = [kincade.charts.Chart(1, {**chart, 1: "I1", 2: "I2", 3: "I3", 4: "I4"})]
    living = kincade.charts.living_checker(tree, charts, 2026)
    assert [living(f"I{n}") for n in (1, 2, 3, 4)] == [True, False, False, False]
    assert living("I99") is False  # not in the file at all: nothing to hide


def test_undated_ancestors_of_a_dated_descendant_get_an_estimate():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME C /Z/",
            "1 BIRT",
            "2 DATE 1900",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME P /Z/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
        )
    )
    living = kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)
    # 1900 - 25: a dated descendant gives an answer, so the default does not apply
    assert living("I2") is False


def test_private_blanks_a_person_with_no_dates():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Nobody /Known/", "1 BIRT", "2 PLAC Somewhere, Ohio")
    )
    pdf = render_pdf(
        plan_charts(tree, "I1", 4),
        tree,
        Options(
            fonts="base14",
            compress=False,
            index=False,
            exclude_private=True,
            today=TODAY,
        ),
    )
    assert b"Somewhere" not in pdf and b"Nobody" not in pdf
    assert b"(Living)" in pdf


# ---- the caller's verdict on who is living (Person.living), library use only

PREDICATE_GED = ged(
    "0 @I1@ INDI",
    "1 NAME Ann /Pell/",
    "1 BIRT",
    "2 DATE 1990",
    "1 FAMC @F1@",  # young: the heuristic says living
    "0 @I2@ INDI",
    "1 NAME Bob /Pell/",
    "1 BIRT",
    "2 DATE 1800",
    "1 DEAT",
    "2 DATE 1870",
    "1 FAMS @F1@",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 MARR",
    "2 DATE 1820",
    "2 PLAC Dayton",
)


def with_living(tree, **verdicts):
    """The tree with Person.living set: with_living(tree, I1=True, I2=None) for I1 and
    I2.
    """
    for name, verdict in verdicts.items():
        tree.people[name].living = verdict
    return tree


def test_living_replaces_the_built_in_heuristic_in_boxes_and_marriage_lines():
    # the caller marks the deceased-looking Bob as living and the young Ann as not
    # living: the opposite of what the built-in heuristic would say
    tree = with_living(read_gedcom(PREDICATE_GED), I1=False, I2=True)
    pdf = render_pdf(
        plan_charts(tree, "I1"),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=True),
    )
    text = drawn(pdf)
    # Bob's birth, death, and marriage (a living spouse) must not be drawn.
    # A year can also occur incidentally in PDF metadata or object offsets.
    for hidden in ("1800", "1870", "1820", "Dayton"):
        assert all(hidden not in line for line in text), hidden
    # Ann shows: predicate says not living
    assert "b. 1990" in text and "PELL, Ann (b. 1990), 1-1" in text
    assert "Ann PELL" in text and "Bob PELL" not in text
    assert "Living" in text
    # Bob is omitted from the index.
    assert not any("PELL, Bob" in line for line in text)
    assert "b." in text and "m." in text  # labels stay


def test_living_also_decides_the_index_order_and_index_years():
    tree = with_living(
        read_gedcom(
            ged(
                "0 @I1@ INDI",
                "1 NAME Root /Zed/",
                "1 FAMC @F1@",
                "0 @I2@ INDI",
                "1 NAME Al /Smith/",
                "1 BIRT",
                "2 DATE 1800",  # heuristic: not living, sorts first
                "0 @I3@ INDI",
                "1 NAME Al /Smith/",
                "1 BIRT",
                "2 DATE 1990",  # heuristic: living, years hidden
                "0 @F1@ FAM",
                "1 HUSB @I2@",
                "1 WIFE @I3@",
            )
        ),
        I1=False,
        I2=True,
        I3=False,
    )
    pdf = render_pdf(
        plan_charts(tree, "I1"),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=True),
    )
    # The caller's verdict omits the 1800 man and includes the 1990 man.
    assert b"(SMITH, Al \\(b. 1990\\), 1-3)" in pdf
    assert b"SMITH, Al, 1-2" not in pdf


def test_living_is_ignored_when_not_private():
    tree = with_living(read_gedcom(PREDICATE_GED), I1=True, I2=True)
    pdf = render_pdf(
        plan_charts(tree, "I1"),
        tree,
        Options(today=TODAY, fonts="base14", compress=False, exclude_private=False),
    )
    assert b"(b. 1800)" in pdf and b"(m. 1820)" in pdf and b"(b. 1990)" in pdf


# ----------------------------------------------------------------
# the living estimate follows birth links only

SECRET = "Secret living birthplace"


def adoption(pedi="adopted", status=None, birth_family=True):
    """Kid (I1, born 1950) belongs to an adopted family F2: Adam I4 and Ada I5, who have
    no dates and no death record, only a birthplace. `pedi` is the PEDI under the kid's
    FAMC of F2 (none if empty); `status` is a CSTA child status on the kid's CHIL line
    in F2, which Kincade ignores. With `birth_family` the kid belongs to a birth family
    F1 first (Bob I2 and Beth I3, both dated), so that `--adoptive-parents` has a
    choice; without it F2 is the kid's only family.
    """
    csta = [] if status is None else ["2 CSTA @C1@"]
    lines = ["0 @I1@ INDI", "1 NAME Kid /KID/", "1 BIRT", "2 DATE 1950"] + (
        ["1 FAMC @F1@"] if birth_family else []
    )
    lines += ["1 FAMC @F2@"] + ([f"2 PEDI {pedi}"] if pedi else [])
    lines += [
        "0 @I2@ INDI",
        "1 NAME Bob /BIRTH/",
        "1 BIRT",
        "2 DATE 1920",
        "1 DEAT",
        "0 @I3@ INDI",
        "1 NAME Beth /BIRTH/",
        "1 BIRT",
        "2 DATE 1922",
        "1 DEAT",
        "0 @I4@ INDI",
        "1 NAME Adam /ADOPT/",
        "1 BIRT",
        f"2 PLAC {SECRET}",
        "0 @I5@ INDI",
        "1 NAME Ada /ADOPT/",
        "1 BIRT",
        "2 PLAC Secret wife birthplace",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
        "1 WIFE @I3@",
        "1 CHIL @I1@",
        "0 @F2@ FAM",
        "1 HUSB @I4@",
        "1 WIFE @I5@",
        "1 CHIL @I1@",
    ] + csta
    if status is not None:
        lines += ["0 @C1@ CSTA", f"1 TEXT {status}"]
    return read_gedcom(ged(*lines))


def estimates(tree, root="I1", parents="birth"):
    """The privacy estimates of the whole pedigree, as render_pdf makes them (every
    generation, same parents).
    """
    return kincade.charts._birth_estimates(
        tree, plan_charts(tree, root, None, parents), 2026
    )


def secrets(tree, **opts):
    """The drawn places that are not for the public: every PLAC of the fixtures in this
    section holds 'ecret'.
    """
    return [
        t
        for t in drawn(render_charts(tree, exclude_private=True, **opts))
        if "ecret" in t
    ]


def test_an_adoptive_parent_is_not_aged_from_the_childs_birth_under_parents_adoptive():
    tree = adoption()  # --adoptive-parents --exclude-private
    charts = plan_charts(tree, "I1", None, "adoptive")
    assert charts[0].slots[2] == "I4"  # the adoptive parents are the ones drawn
    assert secrets(tree, parents="adoptive") == []
    assert "I4" not in estimates(tree, parents="adoptive") and "I5" not in estimates(
        tree, parents="adoptive"
    )
    assert kincade.charts.living_checker(tree, charts, 2026)("I4") is True
    # without --exclude-private the place is drawn, so the test above is about privacy,
    # not about a missing line
    assert f"bp. {SECRET}" in drawn(render_charts(tree, parents="adoptive"))


@pytest.mark.parametrize("pedi", ["adopted", "ADOPTED", "foster", "sealing", "other"])
@pytest.mark.parametrize("parents", ["birth", "adoptive"])
def test_no_non_birth_pedi_lets_a_parent_be_aged_from_the_child(pedi, parents):
    # the only family, so it is drawn in either mode
    tree = adoption(pedi, birth_family=False)
    assert plan_charts(tree, "I1", None, parents)[0].slots[2] == "I4"
    assert "I4" not in estimates(tree, parents=parents)
    assert secrets(tree, parents=parents) == []


@pytest.mark.parametrize("pedi", ["adopted", "foster"])
def test_an_adopted_or_foster_family_drawn_after_a_birth_family_gives_no_age(pedi):
    tree = adoption(pedi)
    assert plan_charts(tree, "I1", None, "adoptive")[0].slots[2] == "I4"
    assert "I4" not in estimates(tree, parents="adoptive")
    assert secrets(tree, parents="adoptive") == []


@pytest.mark.parametrize("parents", ["birth", "adoptive"])
def test_a_child_with_only_an_adopted_family_draws_it_and_gives_no_age(parents):
    # no birth family: the first family is drawn, in either mode
    tree = adoption(birth_family=False)
    assert plan_charts(tree, "I1", None, parents)[0].slots[2] == "I4"
    assert "I4" not in estimates(tree, parents=parents)
    assert secrets(tree, parents=parents) == []


@pytest.mark.parametrize(
    "pedi,status",
    [
        ("", None),
        ("birth", None),
        ("BIRTH", None),
        ("not a relationship", None),
        ("", "Twin"),
        ("", "Died as Infant"),
        ("", "Adopted"),
    ],
)
@pytest.mark.parametrize("parents", ["birth", "adoptive"])
def test_a_birth_link_gives_the_age(pedi, status, parents):
    tree = adoption(pedi, status, birth_family=False)
    assert [(link.father, link.mother) for link in tree.people["I1"].parents] == [
        ("birth", "birth")
    ]
    # the child's 1950 less 25 years
    assert estimates(tree, parents=parents)["I4"] == 1925
    assert estimates(tree, parents=parents)["I5"] == 1925
    # 1925 is over 100 years ago
    assert f"bp. {SECRET}" in drawn(
        render_charts(tree, parents=parents, exclude_private=True)
    )


def chain(upper, lower):
    """Kid (I1, born 1950) - lower - Pat (I2, no dates) - upper - Gus (I3, no dates):
    `lower` is the PEDI of the kid's FAMC under F1 (Pat's family), `upper` that of Pat's
    FAMC under F2 (Gus's family); "" for none. Pat and Gus each have a birthplace.
    """

    def famc(fam, pedi):
        return [f"1 FAMC {fam}"] + ([f"2 PEDI {pedi}"] if pedi else [])

    return read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /KID/",
            "1 BIRT",
            "2 DATE 1950",
            *famc("F1", lower),
            "0 @I2@ INDI",
            "1 NAME Pat /PARENT/",
            "1 BIRT",
            "2 PLAC Pat secret place",
            *famc("F2", upper),
            "0 @I3@ INDI",
            "1 NAME Gus /GRAND/",
            "1 BIRT",
            f"2 PLAC {SECRET}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
            "0 @F2@ FAM",
            "1 HUSB @I3@",
            "1 CHIL @I2@",
        )
    )


@pytest.mark.parametrize("generations", [None, 3, 2, 1])
@pytest.mark.parametrize("parents", ["birth", "adoptive"])
def test_nothing_above_a_non_birth_link_is_aged_from_below_it(parents, generations):
    # Kid was adopted by Pat; Pat is Gus's birth child
    tree = chain(upper="", lower="adopted")
    assert not {"I2", "I3"} & set(estimates(tree, parents=parents))
    # Pat and Gus, as far as they are drawn
    assert secrets(tree, generations=generations, parents=parents) == []


@pytest.mark.parametrize("generations", [None, 3, 2, 1])
@pytest.mark.parametrize("parents", ["birth", "adoptive"])
def test_a_birth_link_below_a_non_birth_link_ages_the_parent_but_not_the_one_above(
    parents, generations
):
    # Kid is Pat's birth child; Pat was fostered by Gus
    tree = chain(upper="foster", lower="")
    est = estimates(tree, parents=parents)
    assert est["I2"] == 1925 and "I3" not in est
    text = drawn(
        render_charts(
            tree, generations=generations, parents=parents, exclude_private=True
        )
    )
    assert f"bp. {SECRET}" not in text  # Gus, hidden as far as he is drawn
    # Pat is 1925: old enough to show, if drawn
    assert ("bp. Pat secret place" in text) == (generations != 1)

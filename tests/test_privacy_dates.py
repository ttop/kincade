"""Privacy and a person's own birth date: the latest year that a range, an open-ended
date or a date with no readable year allows, and what the estimate makes of it."""

import pytest

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import parse_date, read_gedcom

from conftest import (
    HUGE,
    SECRETVILLE,
    dad_and_kid,
    ged,
    secret_shown,
    short,
)

# ----------------------------------------------------------------
# the latest possible birth year


def living_for(birth, *, death=False, this_year=2026, extra=()):
    lines = (
        ["0 @I1@ INDI", "1 NAME P /Q/", "1 BIRT", f"2 DATE {birth}"]
        + (["1 DEAT Y"] if death else [])
        + list(extra)
    )
    tree = read_gedcom(ged(*lines))
    return kincade.charts.living_checker(tree, plan_charts(tree, "I1"), this_year)("I1")


@pytest.mark.parametrize(
    "birth,living",
    [
        ("BET 1900 AND 2000", True),
        ("AFT 1900", True),
        ("FROM 1900", True),
        ("ABT 1920", True),
        ("(sometime in 1990)", True),
        ("BEF 1900", False),
        ("ABT 1900", False),
        ("1900", False),
        ("1765-1767", False),
        ("BET 1900 AND 1910", False),
        ("", True),
        ("unknown", True),  # nothing obtainable and no death record: treated as living
    ],
)
def test_living_uses_the_latest_possible_birth_year(birth, living):
    assert living_for(birth) is living
    assert living_for(birth, death=True) is False  # a death record always wins


def test_descendant_estimates_use_the_latest_possible_year_too():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME C /Z/",
            "1 BIRT",
            "2 DATE BET 1990 AND 2000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME P /Z/",
            "1 FAMC @F2@",
            "0 @I4@ INDI",
            "1 NAME G /Z/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "0 @F2@ FAM",
            "1 HUSB @I4@",
        )
    )
    est = kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)
    assert est == {"I1": 2000, "I2": 2000 - 25, "I4": 2000 - 50}


# ---- AFT / FROM-open births: the descendant estimate, floored at the stated year


@pytest.mark.parametrize(
    "own,kid,living",
    [
        (
            "AFT 1735",
            1800,
            False,
        ),  # the child's 1800 gives 1775, later than the 1735 floor
        ("FROM 1735", 1800, False),  # an open FROM is handled the same way
        (
            "AFT 1900",
            2000,
            True,
        ),  # 2000 gives 1975: later than 1900, and within the last 100 years
        (
            "AFT 1735",
            1740,
            False,
        ),  # 1715 from the child is earlier than the floor, so 1735 stands
        (
            "FROM 1735 TO 1740",
            1800,
            False,
        ),  # not open-ended: the dated 1740 wins
    ],
)
def test_an_open_ended_birth_takes_the_later_of_its_year_and_the_descendant_estimate(
    own, kid, living
):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            f"2 DATE {kid}",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            f"2 DATE {own}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
        )
    )
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2")
        is living
    )


@pytest.mark.parametrize("own", ["AFT 1735", "FROM 1735"])
def test_an_open_ended_birth_with_no_dated_descendant_stays_possibly_living(own):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 FAMC @F1@",  # an undated child
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            f"2 DATE {own}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
        )
    )
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2") is True
    )


@pytest.mark.parametrize(
    "birth,living",
    [
        (
            "INT 2000 (from census 1900)",
            True,
        ),  # 2000 is within the last 100 years: must be hidden
        ("INT 1900 (about 1905)", False),
    ],
)
def test_int_dates_decide_living_by_their_latest_possible_year(birth, living):
    assert living_for(birth) is living


@pytest.mark.parametrize(
    "own,kid,living",
    [
        (
            "AFT 1926",
            1950,
            True,
        ),  # strictly after 1926: born 1927 at the earliest, 99 years old in 2026
        ("AFTER 1926", 1950, True),
        ("AFT 1925", 1950, False),  # born 1926 at the earliest: 100 years old
        (
            "FROM 1926",
            1950,
            False,
        ),  # an open FROM keeps its year as the floor (born 1926 at the earliest)
    ],
)
def test_aft_is_strictly_after_its_year_when_it_floors_the_privacy_estimate(
    own, kid, living
):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            f"2 DATE {kid}",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            f"2 DATE {own}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
        )
    )
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2")
        is living
    )


# ----------------------------------------------------------------
# a date with no readable year stays private


UNREADABLE = [
    "INT @#DHEBREW@ 10 TSH 5695 (autumn)",  # the phrase prints; the date is unreadable
    # a year in the phrase does not make the date readable
    "INT @#DHEBREW@ 10 TSH 5695 (born in 1850?)",
    "INT @#DFRENCH R@ 1 VEND 3 (autumn)",
    "INT @#DFRENCH R@ 3 (year three)",
    "INT @#DROMAN@ 100 (x)",
    "INT @#DUNKNOWN@ 1900 (the year the war ended 1945)",
    "INT @#D@ 1900 (x)",
    "INT HEBREW 5695 (x)",
    "INT FRENCH_R 1 VEND 3 (x)",
    "@#DHEBREW@ 10 TSH 5695",
    "HEBREW 10 TSH 5695",
    "@#DFRENCH R@ 1 VEND 3",
    "@#DFRENCH R@ 3",
    "FRENCH_R 3",
    "@#DHEBREW@ 5695",
    "HEBREW 5695",
    "@#DROMAN@ 100",
    "@#DROMAN@ 5 MAR 100",
    "@#D@ 1900",
    "@#DUNKNOWN@ 1900",
    "ABT @#DROMAN@ 1900",
    "EST @#DROMAN@ 1900",
    "BEF @#DROMAN@ 1900",
    "TO @#DROMAN@ 1900",
    "AFT @#DROMAN@ 1900",
    "FROM @#DROMAN@ 1900",
    "AFT @#DHEBREW@ 10 TSH 5695",
    "INT AFT @#DROMAN@ 1900 (x)",
    "BET @#DHEBREW@ 5690 AND @#DHEBREW@ 5695",
    "BET @#DROMAN@ 100 AND @#DROMAN@ 200",
    "FROM @#DROMAN@ 100 TO @#DROMAN@ 200",
    "FROM @#DFRENCH R@ 1 TO @#DFRENCH R@ 3",
    # one end unreadable: the other cannot make it readable
    "BET @#DJULIAN@ 1700 AND @#DHEBREW@ 5695",
    # an interpreted date this reader cannot read at all
    "INT 12 Foo 1900 (about then)",
]


NO_YEAR = [  # recorded, and no year in them: the same rule
    "(autumn)",
    "autumn",
    "unknown",
    "(unknown)",
    "12 MAY",
    "MAY",
    "INT autumn (x)",
    "AFT the war",
    "FROM sometime",
    "(born in 1700)",
    "INT spring 1700 ()",
]


# a year can be read: Dad is old enough, so the descendant estimate is not even needed
READABLE = [
    "1700",
    "INT @#DJULIAN@ 5 MAR 1700 (x)",
    "@#DJULIAN@ 5 MAR 1700",
    "JULIAN 1700",
    "@#DGREGORIAN@ 1700",
    "BET @#DJULIAN@ 1 JAN 1700 AND @#DJULIAN@ 1 JAN 1701",
    "ABT @#DJULIAN@ 1700",
    "INT 12 JAN 1700 (x)",
    "INT 1731/32 (x)",
    "BEF 1900",
]


@pytest.mark.parametrize("date", UNREADABLE)
def test_a_birth_date_with_a_year_kincade_cannot_read_stays_private_whatever_a_dated_child_says(
    date,
):
    tree = dad_and_kid(date)
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2") is True
    )
    assert not secret_shown(tree)


@pytest.mark.parametrize("date", NO_YEAR)
def test_a_recorded_birth_date_that_names_no_year_is_not_overridden_by_the_estimate_either(
    date,
):
    tree = dad_and_kid(date)
    assert not secret_shown(tree)
    # possibly born today
    assert (
        kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)["I2"]
        == 2026
    )


@pytest.mark.parametrize("date", READABLE)
def test_a_birth_date_with_a_readable_year_is_read_for_that_year(date):
    tree = dad_and_kid(date)
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2")
        is False
    )
    assert secret_shown(tree)


def test_julian_dates_use_their_year_directly():
    assert (
        kincade.charts.latest_birth_year(parse_date("@#DJULIAN@ 5 MAR 1700"), 2026)
        == 1700
    )
    assert (
        kincade.charts.latest_birth_year(
            parse_date("INT @#DJULIAN@ 5 MAR 1700 (x)"), 2026
        )
        == 1700
    )
    assert kincade.lang.year_of(parse_date("JULIAN 1700")) == 1700


@pytest.mark.parametrize(
    "raw",
    [
        "INT @#DHEBREW@ 10 TSH 5695 (autumn)",
        "@#DROMAN@ 100",
        "@#DFRENCH R@ 3",
        "BET @#DROMAN@ 100 AND @#DROMAN@ 200",
        "ABT @#DROMAN@ 1900",
        "BEF @#DROMAN@ 1900",
    ],
)
def test_an_unreadable_year_allows_any_year_up_to_today(raw):
    date = parse_date(raw)
    assert date.year_unknown
    assert kincade.charts.latest_birth_year(date, 2026) == 2026
    # not open-ended: it is a date, of an unreadable year
    assert kincade.charts.open_birth(date) == (False, None)


@pytest.mark.parametrize(
    "raw", ["AFT @#DROMAN@ 1900", "FROM @#DROMAN@ 1900", "INT AFT @#DROMAN@ 1900 (x)"]
)
def test_an_unreadable_open_ended_date_is_not_treated_as_open_ended_either(raw):
    date = parse_date(raw)
    assert date.year_unknown and kincade.charts.open_birth(date) == (False, None)


def test_how_such_dates_print():
    de = kincade.lang.load_strings("de")
    for raw, english, german in [
        ("INT @#DHEBREW@ 10 TSH 5695 (autumn)", "autumn", "autumn"),
        ("@#DHEBREW@ 10 TSH 5695", "@#DHEBREW@ 10 TSH 5695", "@#DHEBREW@ 10 TSH 5695"),
        ("@#DHEBREW@ 5695", "@#DHEBREW@ 5695", "@#DHEBREW@ 5695"),
        ("(autumn)", "autumn", "autumn"),
        ("ABT @#DROMAN@ 1900", "ABT @#DROMAN@ 1900", "ABT @#DROMAN@ 1900"),
        (
            "BET @#DHEBREW@ 5690 AND @#DHEBREW@ 5695",
            "BET @#DHEBREW@ 5690 AND @#DHEBREW@ 5695",
            "BET @#DHEBREW@ 5690 AND @#DHEBREW@ 5695",
        ),
    ]:
        date = parse_date(raw)
        assert (kincade.lang.format_date(date), kincade.lang.format_date(date, de)) == (
            english,
            german,
        ), raw


@pytest.mark.parametrize("date", [*NO_YEAR, "@#DHEBREW@ 10 TSH 5695"])
@pytest.mark.parametrize("christening", ["1700", "unknown"])
def test_a_christening_does_not_bound_a_recorded_birth_date_with_no_year(
    date, christening
):
    tree = dad_and_kid(date, christening=christening)
    assert (
        kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)["I2"]
        == 2026
    )
    assert not secret_shown(tree)


@pytest.mark.parametrize("date", [*NO_YEAR, "@#DHEBREW@ 10 TSH 5695"])
@pytest.mark.parametrize("christening", [None, "1880"])
def test_a_recorded_birth_date_with_no_year_counts_as_this_year_for_the_ancestors_too(
    date, christening
):
    # Root (born 1900) is the child of Kid, whose birth names no year; Kid is the child
    # of Dad, who has no birth date. Kid may be born this year, so Dad may be born 25
    # years before it, whatever Root's birth or Kid's christening says.
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Root /Z/",
            "1 BIRT",
            "2 DATE 1900",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            f"2 DATE {date}",
            *(["1 CHR", f"2 DATE {christening}"] if christening else []),
            "1 FAMC @F2@",
            "0 @I3@ INDI",
            "1 NAME Dad /Z/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
            "0 @F2@ FAM",
            "1 HUSB @I3@",
            "1 CHIL @I2@",
        )
    )
    charts = plan_charts(tree, "I1")
    assert kincade.charts._birth_estimates(tree, charts, 2026)["I3"] == 2026 - 25
    assert kincade.charts.living_checker(tree, charts, 2026)("I3") is True


def test_an_unreadable_date_of_a_child_makes_the_parent_possibly_living():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            "2 DATE INT @#DHEBREW@ 10 TSH 5695 (autumn)",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            f"2 PLAC {SECRETVILLE}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    assert kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026) == {
        "I1": 2026,
        "I2": 2026 - 25,
    }
    assert not secret_shown(tree)


def test_a_death_record_makes_a_person_not_living():
    assert secret_shown(dad_and_kid("INT @#DHEBREW@ 10 TSH 5695 (autumn)", "1 DEAT Y"))


def test_the_candidate_lists_hide_the_years_of_such_a_person(tmp_path, capsys):
    path = tmp_path / "a.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Heb /REW/",
            "1 BIRT",
            "2 DATE @#DHEBREW@ 5695",
            "0 @I2@ INDI",
            "1 NAME Jul /IAN/",
            "1 BIRT",
            "2 DATE @#DJULIAN@ 1700",
            "0 @I3@ INDI",
            "1 NAME Rom /AN/",
            "1 BIRT",
            "2 DATE @#DROMAN@ 100",
        )
    )
    assert kincade.cli.main([str(path), "--find", "", "--exclude-private"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "I1\tLiving\t",
        "I2\tJul IAN\t1700-",
        "I3\tLiving\t",
    ]


@pytest.mark.parametrize(
    "raw",
    [
        HUGE,
        f"BET {HUGE} AND 1900",
        f"INT {HUGE} (x)",
        "99999",
        "0000",
        "5 JAN 12345",
        f"FROM {HUGE}",
        "9999/00",
    ],
    ids=short,
)
def test_a_person_with_such_a_date_stays_private(raw):
    tree = dad_and_kid(raw)
    assert (
        kincade.charts.living_checker(tree, plan_charts(tree, "I1"), 2026)("I2") is True
    )
    assert not secret_shown(tree)

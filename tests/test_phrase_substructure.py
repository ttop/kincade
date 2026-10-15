"""GEDCOM 7 DATE with a PHRASE: the payload and the phrase as the reader takes them,
and a date that is only a phrase as a recorded event."""

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade import Date, Day, Event, read_gedcom
from kincade.charts import plan_charts

from conftest import (
    SECRETVILLE,
    dad_and_kid,
    render_charts,
    secret_shown,
    seven,
)
from pdfread import drawn


def birth_of(*lines):
    return (
        read_gedcom(seven("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", *lines))
        .people["I1"]
        .birth
    )


def test_an_empty_date_with_a_phrase_is_a_date_whose_text_is_the_phrase():
    assert birth_of("2 DATE", "3 PHRASE 5 January (year unknown)") == Event(
        Date("text", text="5 January (year unknown)")
    )
    assert birth_of("2 DATE", "3 PHRASE autumn", "2 PLAC Reno") == Event(
        Date("text", text="autumn"), "Reno"
    )
    assert birth_of(
        "2 DATE", "3 PHRASE a long", "4 CONC  phrase", "3 TIME 12:00"
    ) == Event(Date("text", text="a long phrase"))
    assert kincade.lang.format_date(
        birth_of("2 DATE", "3 PHRASE 5 January (year unknown)").date
    ) == ("5 January (year unknown)")


def test_an_empty_date_with_an_empty_phrase_is_no_date():
    assert birth_of("2 DATE", "3 PHRASE", "2 PLAC Reno") == Event(None, "Reno")
    assert birth_of("2 DATE", "2 PLAC Reno") == Event(None, "Reno")


def test_a_structured_payload_keeps_its_structure_and_the_phrase_does_not_replace_it():
    assert birth_of("2 DATE 5 JAN 1990", "3 PHRASE the fifth of January").date == Date(
        "exact", Day(1990, 1, 5)
    )
    assert birth_of(
        "2 DATE BET 1900 AND 1905", "3 PHRASE around the turn of the century"
    ).date == Date("between", Day(1900), Day(1905))
    assert birth_of("2 DATE ABT 1900", "3 PHRASE maybe 1990").date == Date(
        "about", Day(1900)
    )
    # the structure is what privacy reads, too: the phrase's year does not count
    tree = dad_and_kid("1700")
    assert (
        kincade.charts.latest_birth_year(
            birth_of("2 DATE 1700", "3 PHRASE maybe 1990").date, 2026
        )
        == 1700
    )
    assert secret_shown(tree)


def test_a_payload_that_is_only_text_gives_way_to_the_phrase_and_stays_unread():
    date = birth_of("2 DATE 5 Sept 1990", "3 PHRASE the fifth of September").date
    assert (
        kincade.lang.format_date(date) == "the fifth of September" and date.year_unknown
    )
    assert birth_of("2 DATE unknown", "3 PHRASE nobody remembers").date == Date(
        "text", text="nobody remembers", year_unknown=True
    )


def test_a_payload_in_a_calendar_that_cannot_be_read_keeps_that_mark():
    # text only: the phrase is shown
    date = birth_of("2 DATE HEBREW 10 TSH 5695", "3 PHRASE Rosh Hashanah").date
    assert date.year_unknown and kincade.lang.format_date(date) == "Rosh Hashanah"
    # a structure: the payload is shown, as written
    date = birth_of("2 DATE HEBREW 5695", "3 PHRASE Rosh Hashanah").date
    assert date.year_unknown and kincade.lang.format_date(date) == "HEBREW 5695"


def test_a_phrase_only_birth_counts_as_a_record_so_no_christening_stands_in_for_it():
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 BIRT",
            "2 DATE",
            "3 PHRASE 5 January (year unknown)",
            "1 CHR",
            "2 DATE 1 JAN 1900",
        )
    )
    person = tree.people["I1"]
    assert kincade.charts.birth_source(person) == (person.birth, "birth")
    assert person.birth.filled()
    text = drawn(render_charts(tree, "I1", index=False))
    assert "b. 5 January (year unknown)" in text and not any(
        t.startswith("chr.") for t in text
    )


def test_a_phrase_only_death_counts_as_a_record_so_no_burial_stands_in_for_it():
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 DEAT",
            "2 DATE",
            "3 PHRASE in the war",
            "1 BURI",
            "2 DATE 1 JAN 1945",
        )
    )
    person = tree.people["I1"]
    assert kincade.charts.death_source(person) == (person.death, "death")
    assert "d. in the war" in drawn(render_charts(tree, "I1", index=False))


def test_a_phrase_only_christening_stands_in_for_a_missing_birth():
    tree = read_gedcom(
        seven("0 @I1@ INDI", "1 NAME A /B/", "1 CHR", "2 DATE", "3 PHRASE Easter")
    )
    person = tree.people["I1"]
    assert kincade.charts.birth_source(person) == (
        person.christenings[0],
        "christening",
    )
    assert "chr. Easter" in drawn(render_charts(tree, "I1", index=False))


def test_a_phrase_only_birth_date_keeps_its_person_private_as_a_recorded_date_with_no_year():
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME Kid /Z/",
            "1 BIRT",
            "2 DATE 1950",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /Z/",
            "1 BIRT",
            "2 DATE",
            "3 PHRASE 5 January (year unknown)",
            f"2 PLAC {SECRETVILLE}",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    assert not secret_shown(tree)
    assert (
        kincade.charts._birth_estimates(tree, plan_charts(tree, "I1"), 2026)["I2"]
        == 2026
    )
    # unrecognized prose supplies no year, even when it contains digits
    tree.people["I2"].birth.date = Date("text", text="before the 1900 census")
    assert not secret_shown(tree)


def test_a_phrase_only_marriage_is_a_marriage_with_a_date():
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME C /D/",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
            "1 MARR",
            "2 DATE",
            "3 PHRASE spring",
        )
    )
    assert tree.families["F1"].marriage == Event(Date("text", text="spring"))
    assert "m. spring" in drawn(render_charts(tree, "I1", index=False))

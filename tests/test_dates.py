"""Dates: reading GEDCOM date text, printing dates, and the years a date allows."""

import random

import pytest

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade.charts import latest_birth_year, open_birth, plan_charts
from kincade.gedcom import parse_date, read_gedcom
from kincade.lang import format_date, year_of
from kincade.model import Date, Day, Event

from conftest import (
    HUGE,
    SECRETVILLE,
    dad_and_kid,
    ged,
    render_charts,
    secret_shown,
    short,
)
from pdfread import drawn

# ---------------------------------------------------------------- reading dates once


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1917", Date("exact", Day(1917))),
        ("JAN 1917", Date("exact", Day(1917, 1))),
        ("13 JAN 1917", Date("exact", Day(1917, 1, 13))),
        ("13 jan 1917", Date("exact", Day(1917, 1, 13))),  # the month in any case
        ("19 JAN", Date("exact", Day(month=1, day=19))),
        ("ABT 1826", Date("about", Day(1826))),
        ("ABT. 1917", Date("about", Day(1917))),
        ("CIRCA 1800", Date("about", Day(1800))),
        ("ca. 1800", Date("about", Day(1800))),
        ("~1863", Date("about", Day(1863))),
        ("EST 1800", Date("exact", Day(1800), quality="estimated")),
        ("CAL 1 FEB 1801", Date("exact", Day(1801, 2, 1), quality="calculated")),
        ("BEF. 6 SEP 1730", Date("before", Day(1730, 9, 6))),
        ("AFT 1735", Date("after", Day(1735))),
        ("AFTER 1735", Date("after", Day(1735))),
        (
            "BET 1 JAN 1900 AND 1 FEB 1900",
            Date("between", Day(1900, 1, 1), Day(1900, 2, 1)),
        ),
        ("BET. 1622 - 1632", Date("between", Day(1622), Day(1632))),
        ("FROM 1900 TO 1910", Date("from_to", Day(1900), Day(1910))),
        ("FROM 1900", Date("from", Day(1900))),
        ("TO 1910", Date("to", Day(1910))),
        (
            "28 FEB 1734/35",
            Date("exact", Day(1734, 2, 28, dual_year=1735)),
        ),  # the Old Style and the New Style year
        ("1699/00", Date("exact", Day(1699, dual_year=1700))),
        (
            "@#DJULIAN@ 5 MAR 1700",
            Date("exact", Day(1700, 3, 5)),
        ),  # a calendar escape or keyword is dropped
        ("JULIAN 5 MAR 1700", Date("exact", Day(1700, 3, 5))),
        (
            "BET JULIAN 1 JAN 1700 AND JULIAN 1 JAN 1701",
            Date("between", Day(1700, 1, 1), Day(1701, 1, 1)),
        ),
        ("  13   JAN\t1917 ", Date("exact", Day(1917, 1, 13))),
    ],
)
def test_gedcom_dates_become_structure(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "(Hebrew New Year)",
            Date("text", text="Hebrew New Year"),
        ),  # the word, not the HEBREW calendar keyword
        ("(unknown)", Date("text", text="unknown")),
        (
            "INT 12 JAN 1900 (about then)",
            Date("exact", Day(1900, 1, 12), text="about then"),
        ),  # the phrase is the text; the date is read
        ("INT ABT 1900 (about 1800)", Date("about", Day(1900), text="about 1800")),
    ],
)
def test_a_phrase_is_the_dates_text_and_the_interpreted_date_is_kept(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,form,quality",
    [
        ("by Dec 1879", "before", ""),
        ("1765-1767", "text", ""),
        ("1821-1824 or 1829", "text", ""),
        ("after 30 July 1941 before 1950", "text", ""),
        ("FROM 1900 or so", "text", ""),
        ("FROM 1900 to 1910 or so", "text", ""),
        ("Abt. 1900 or so", "text", ""),
        ("EST. 1800?", "text", ""),
        ("Sept. 1999", "text", ""),  # not one of the three-letter months
        ("BET 1900 AND", "text", ""),
    ],
)
def test_text_that_is_not_a_date_is_kept_as_written(raw, form, quality):
    date = parse_date(raw)
    assert (
        date.text == " ".join(raw.split())
        and date.form == form
        and date.quality == quality
    )
    assert date.start is None and date.end is None


def test_no_date_text_is_no_date():
    assert (
        parse_date("") is None
        and parse_date("   ") is None
        and parse_date(None) is None
    )
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", "2 DATE", "2 PLAC Here")
    )
    assert tree.people["I1"].birth == Event(None, "Here")


# ---------------------------------------------------------------- printing a Date


@pytest.mark.parametrize(
    "date,expected",
    [
        (Date("exact", Day(1917)), "1917"),
        (Date("exact", Day(1917, 1, 13)), "13 Jan 1917"),
        (Date("exact", Day(1917, 1)), "Jan 1917"),
        (Date("exact", Day(month=1, day=19)), "19 Jan"),
        (Date("about", Day(1826)), "abt 1826"),
        (Date("exact", Day(1800), quality="estimated"), "est 1800"),
        (Date("exact", Day(1800), quality="calculated"), "cal 1800"),
        (
            Date("about", Day(1800), quality="estimated"),
            "est abt 1800",
        ),  # quality first, then the form
        (Date("before", Day(1730, 9, 6)), "bef 6 Sep 1730"),
        (Date("after", Day(1735)), "aft 1735"),
        (Date("from", Day(1900)), "from 1900"),
        (Date("to", Day(1910)), "to 1910"),
        (Date("between", Day(1900, 1, 1), Day(1900, 2, 1)), "1 Jan 1900-1 Feb 1900"),
        (Date("from_to", Day(1900), Day(1910)), "1900-1910"),
        (Date("exact", Day(1734, 2, 28, dual_year=1735)), "28 Feb 1734/35"),
        (Date("exact", Day(1699, dual_year=1700)), "1699/00"),
        (Date("text", text="Hebrew New Year"), "Hebrew New Year"),
        (
            Date("exact", Day(1900, 1, 12), text="about then"),
            "about then",
        ),  # the text is what is printed
        (Date("exact"), ""),  # a form with nothing to print
        (None, ""),
    ],
)
def test_dates_print_from_their_structure(date, expected):
    assert format_date(date) == expected


def test_dates_print_in_the_language_of_the_strings():
    de = kincade.lang.load_strings("de")
    assert format_date(Date("about", Day(1755)), de) == "um 1755"
    assert format_date(Date("between", Day(1622), Day(1632)), de) == "1622–1632"
    assert format_date(Date("exact", Day(1917, 1, 13)), de) == "13. Jan. 1917"


def test_year_of_is_the_year_of_the_first_date_as_written():
    assert year_of(Date("between", Day(1765), Day(1767))) == 1765
    # the year as written
    assert year_of(Date("exact", Day(1734, 2, 28, dual_year=1735))) == 1734
    assert year_of(Date("exact", Day(month=1, day=19))) is None
    assert year_of(Date("text", text="born in 1850, perhaps")) is None
    # the interpreted date, not the phrase
    assert year_of(Date("exact", Day(1900, 1, 12), text="about 1950")) == 1900
    assert year_of(None) is None


# ----------------------------------------------------------------
# the years free text names


@pytest.mark.parametrize(
    "raw,shown,latest",
    [
        ("c1900", 1900, 1910),  # an approximation allows ten years later
        ("1900s", 1900, 1909),  # a decade allows its ninth year
        ("1920's", 1920, 1929),
        ("1900/05/12", 1900, 1900),
        ("12/05/1900", 1900, 1900),
        ("12.5.1900", 1900, 1900),
        ("12-05-1900", 1900, 1900),
        ("1900.05.12", 1900, 1900),
        ("1900-05-12", 1900, 1900),
        ("born 1900/05", None, None),
        ("born 1731/32", None, None),
        ("born 1731/2", None, None),
        ("born 1699/00", None, None),
        ("born 1900/1910", None, None),
        ("between 1890 and 1900", 1890, 1900),
        ("born in 1850, perhaps", None, None),
        ("born abt 1900", None, None),
        ("in the spring", None, None),
    ],
)
def test_the_index_and_the_estimate_read_the_same_years_from_text(raw, shown, latest):
    date = parse_date(raw)
    assert date.start is None and date.text == raw
    assert year_of(date) == shown
    assert latest_birth_year(date, 2026) == latest


def test_the_index_shows_and_sorts_by_a_year_that_touches_a_letter():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /DOE/",
            "1 BIRT",
            "2 DATE c1950",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Ann /DOE/",
            "1 BIRT",
            "2 DATE 1900s",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    index = kincade.pdf.build_index(
        tree, plan_charts(tree, "I1"), lambda pid: False, False
    )
    assert index == ["DOE, Ann (b. 1900), 1-2", "DOE, Ann (b. 1950), 1-1"]


# ----------------------------------------------------------------
# the estimates read the structure


@pytest.mark.parametrize(
    "date,expected",
    [
        (Date("exact", Day(1900)), 1900),
        (
            Date("exact", Day(1734, 2, 28, dual_year=1735)),
            1735,
        ),  # a double date: the New Style year
        (Date("about", Day(1900)), 1910),
        (Date("exact", Day(1850), quality="estimated"), 1860),
        (Date("exact", Day(1850), quality="calculated"), 1860),
        (Date("before", Day(1900)), 1900),
        (Date("to", Day(1900)), 1900),
        (Date("after", Day(1900)), 2026),
        (Date("from", Day(1900)), 2026),
        (Date("from_to", Day(1900), Day(1910)), 1910),
        (Date("between", Day(1900), Day(2000)), 2000),
        (Date("text", text="by Dec 1879"), 1879),
        (Date("text", text="1821-1824 or 1829"), None),
        (
            Date("about", text="Abt. 1900 or so"),
            None,
        ),
        (Date("after", text="after 30 July 1941 before 1950"), 2026),
        (
            Date("exact", Day(2000), text="from census 1900"),
            2000,
        ),  # the reading counts, not just the year in the phrase
        (
            Date("about", Day(1900), text="about 1800"),
            1910,
        ),  # about applies to the reading, not the phrase
        (
            Date("exact", Day(1900), text="about 1905 or 1950"),
            1900,
        ),  # unrecognized prose leaves the structured reading
        (Date("text", text="census 1900; born 1950"), None),
        (Date("text", text="unknown"), None),
        (Date("exact", Day(month=1, day=19)), None),
        (Date("exact"), None),
        (None, None),
    ],
)
def test_latest_birth_year_of_a_date(date, expected):
    assert latest_birth_year(date, 2026) == expected


@pytest.mark.parametrize(
    "date,expected",
    [
        (Date("after", Day(1735)), (True, 1736)),  # strictly after
        (Date("from", Day(1735)), (True, 1735)),
        (Date("after"), (True, None)),
        (Date("after", text="after 1941 before 1950"), (True, None)),
        (
            Date("from_to", Day(1735), Day(1740)),
            (False, None),
        ),  # a period with an end is not open
        (Date("between", Day(1735), Day(1740)), (False, None)),
        (Date("exact", Day(1735)), (False, None)),
        (Date("text", text="after the war"), (False, None)),
        (None, (False, None)),
    ],
)
def test_open_birth_of_a_date(date, expected):
    assert open_birth(date) == expected


# ---------------------------------------------------------------- dates


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("13 JAN 1917", "13 Jan 1917"),
        ("JAN 1917", "Jan 1917"),
        ("1917", "1917"),
        ("19 JAN", "19 Jan"),
        ("ABT 1826", "abt 1826"),
        ("ABT. 1917", "abt 1917"),
        ("BEF. 6 SEP 1730", "bef 6 Sep 1730"),
        ("AFT 1735", "aft 1735"),
        ("EST 1800", "est 1800"),
        ("CAL 1800", "cal 1800"),
        ("BET 1 JAN 1900 AND 1 FEB 1900", "1 Jan 1900-1 Feb 1900"),
        ("BET. 1622 - 1632", "1622-1632"),
        ("BET. 12 - 13 SEP 1987", "12-13 Sep 1987"),
        ("FROM 1900 TO 1910", "1900-1910"),
        ("FROM 1900", "from 1900"),
        ("TO 1910", "to 1910"),
        ("INT 12 JAN 1900 (about then)", "about then"),
        ("(unknown)", "unknown"),
        ("@#DJULIAN@ 5 MAR 1700", "5 Mar 1700"),
        ("JULIAN 5 MAR 1700", "5 Mar 1700"),
        ("28 FEB 1734/35", "28 Feb 1734/35"),
        ("~1863", "abt 1863"),
        ("1765-1767", "1765-1767"),  # raw passthrough
        ("by Dec 1879", "by Dec 1879"),
        ("after 30 July 1941 before 1950", "after 30 July 1941 before 1950"),
        ("1821-1824 or 1829", "1821-1824 or 1829"),
        ("", ""),
    ],
)
def test_format_date(raw, expected):
    assert format_date(parse_date(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "HEBREW 5650",
        "@#DHEBREW@ 5650",
        "@#DHEBREW@ 1 TSH 5650",
        "ABT @#DROMAN@ 1900",
        "BET @#DHEBREW@ 5690 AND @#DHEBREW@ 5695",
        "FRENCH_R 3",
        "@#DUNKNOWN@ 1900",
    ],
)
def test_a_date_in_a_calendar_kincade_cannot_convert_prints_as_written_with_no_year(
    raw,
):
    date = parse_date(raw)
    assert date.year_unknown
    assert (
        format_date(date) == format_date(date, kincade.lang.load_strings("de")) == raw
    )
    assert year_of(date) is None


def test_the_box_prints_such_a_date_as_written_and_the_index_shows_and_sorts_no_year():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /DOE/",
            "1 BIRT",
            "2 DATE HEBREW 1000",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Ann /DOE/",
            "1 BIRT",
            "2 DATE 1900",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
        )
    )
    index = kincade.pdf.build_index(
        tree, plan_charts(tree, "I1"), lambda pid: False, False
    )
    assert index == ["DOE, Ann (b. 1900), 1-2", "DOE, Ann, 1-1"]
    assert "b. HEBREW 1000" in drawn(render_charts(tree))


# ----------------------------------------------------------------
# dates, malformed lines, errors


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(Hebrew New Year)", "Hebrew New Year"),
        ("INT 1 JAN 1900 (Hebrew New Year)", "Hebrew New Year"),
        ("Hebrew New Year", "Hebrew New Year"),
        ("ABT @#DJULIAN@ 1700", "abt 1700"),
        ("BEF JULIAN 5 MAR 1700", "bef 5 Mar 1700"),
        ("BET JULIAN 1 JAN 1700 AND JULIAN 1 JAN 1701", "1 Jan 1700-1 Jan 1701"),
        ("FROM @#DJULIAN@ 1700 TO @#DJULIAN@ 1701", "1700-1701"),
        ("GREGORIAN 5 MAR 1700", "5 Mar 1700"),
    ],
)
def test_calendar_keywords_are_only_stripped_in_calendar_position(raw, expected):
    assert format_date(parse_date(raw)) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1900", 1900),
        ("13 JAN 1917", 1917),
        ("JAN 1917", 1917),
        ("BET 1900 AND 2000", 2000),
        ("BET. 1622 - 1632", 1632),
        ("FROM 1900 TO 1910", 1910),
        ("1765-1767", 1767),
        ("AFT 1900", 2026),
        ("AFT. 1735", 2026),
        ("after 30 July 1941 before 1950", None),
        ("FROM 1900", 2026),
        ("BEF 1900", 1900),
        ("TO 1900", 1900),
        ("by Dec 1879", 1879),
        ("ABT 1900", 1910),
        ("EST 1850", 1860),
        ("CAL 1850", 1860),
        ("~1863", 1873),
        ("ca 1755", 1765),
        ("(sometime in 1990)", None),
        ("INT 1 JAN 1900 (about 1905)", 1915),
        ("1731/32", 1732),
        ("unknown", None),
        ("", None),
        ("(unknown)", None),
    ],
)
def test_latest_possible_birth_year(raw, expected):
    assert kincade.charts.latest_birth_year(parse_date(raw), 2026) == expected


# ----------------------------------------------------------------
# a structured year below 100 is a year


def test_date_0099_is_the_year_99():
    assert parse_date("0099") == Date("exact", Day(99))
    assert parse_date("099") == Date("exact", Day(99))
    assert parse_date("BET 0099 AND 1900") == Date("between", Day(99), Day(1900))


@pytest.mark.parametrize(
    "date,latest,shown",
    [
        (Date("exact", Day(99)), 99, 99),
        (Date("exact", Day(1, 3, 5)), 1, 1),
        (Date("between", Day(99), Day(1900)), 1900, 99),
        (Date("between", Day(99), Day(150)), 150, 99),
        (Date("about", Day(99)), 109, 99),
        (Date("exact", Day(50, dual_year=51)), 51, 50),
        (Date("from_to", Day(1900), Day(99)), 1900, 1900),
        (Date("exact", Day(99), text="a phrase"), 99, 99),
    ],
)
def test_the_helpers_read_a_structured_year_below_100_directly(date, latest, shown):
    assert kincade.charts.latest_birth_year(date, 2026) == latest
    assert kincade.lang.year_of(date) == shown


def test_open_ended_floors_use_a_year_below_100():
    assert kincade.charts.open_birth(Date("after", Day(99))) == (True, 100)
    assert kincade.charts.open_birth(Date("from", Day(99))) == (True, 99)


def test_a_person_born_in_the_year_99_is_old_and_in_the_index():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Old /ROMAN/",
            "1 BIRT",
            "2 DATE 0099",
            f"2 PLAC {SECRETVILLE}",
        )
    )
    # born in the year 99: not living, so privacy hides nothing
    assert secret_shown(tree)
    entries = kincade.pdf.build_index(
        tree, plan_charts(tree, "I1"), lambda pid: False, False
    )
    assert entries == ["ROMAN, Old (b. 99), 1-1"]
    pdf = render_charts(tree, "I1", index=True, exclude_private=True)
    assert "ROMAN, Old (b. 99), 1-1" in drawn(pdf) and "b. 99" in drawn(pdf)


def test_a_range_starting_in_the_year_99_is_bounded_by_its_end():
    tree = dad_and_kid("BET 0099 AND 1900")
    assert kincade.charts.latest_birth_year(tree.people["I2"].birth.date, 2026) == 1900
    assert secret_shown(tree)  # 1900 is over 100 years ago
    assert not secret_shown(dad_and_kid("BET 0099 AND 2000"))


def test_the_candidate_lists_show_the_year_99(tmp_path, capsys):
    path = tmp_path / "a.ged"
    path.write_bytes(
        ged(
            "0 @I1@ INDI",
            "1 NAME Old /ROMAN/",
            "1 BIRT",
            "2 DATE 0099",
            "1 DEAT",
            "2 DATE 0150",
        )
    )
    assert kincade.cli.main([str(path), "--find", "roman", "--exclude-private"]) == 0
    assert capsys.readouterr().out == "I1\tOld ROMAN\t99-150\n"


@pytest.mark.parametrize(
    "raw", ["99", "5 MAR 85", "JAN 99", "85/86", "5 MAR 99", "5 MAR 5"]
)
def test_a_number_of_one_or_two_digits_is_not_a_year_and_a_date_with_one_is_text(raw):
    # 5 MAR 85 may well be 1985: it is not the year 85,
    # so it is not read as one and stays private
    date = parse_date(raw)
    assert date.form == "text" and date.text == raw and date.start is None
    assert kincade.charts.latest_birth_year(date, 2026) is None
    assert not secret_shown(dad_and_kid(raw))


def test_a_number_of_one_or_two_digits_alone_is_a_day_as_it_prints():
    assert parse_date("12") == Date("exact", Day(day=12))
    assert parse_date("BET. 12 - 13 SEP 1987") == Date(
        "between", Day(day=12), Day(1987, 9, 13)
    )
    assert (
        kincade.lang.format_date(parse_date("BET. 12 - 13 SEP 1987"))
        == "12-13 Sep 1987"
    )
    assert kincade.lang.year_of(parse_date("BET. 12 - 13 SEP 1987")) == 1987
    assert (
        kincade.charts.latest_birth_year(parse_date("BET. 12 - 13 SEP 1900"), 2026)
        == 1900
    )
    # a day with no year: recorded, so possibly living
    assert not secret_shown(dad_and_kid("12"))


def test_a_day_has_a_year_from_1_to_9999():
    assert Day(1).year == 1 and Day(9999).year == 9999
    for bad in (0, -5, 10000, 10**6):
        with pytest.raises(ValueError, match=r"Day\.year"):
            Day(bad)
    with pytest.raises(ValueError, match=r"Day\.dual_year"):
        Day(1731, dual_year=0)
    with pytest.raises(ValueError, match=r"Day\.dual_year"):
        Day(9999, dual_year=10000)


def test_a_double_dates_new_style_year_is_the_year_after_its_old_style_year():
    assert Day(1731, dual_year=1732).dual_year == 1732
    for year, dual in ((1900, 2001), (1900, 1900), (1900, 1899), (None, 1901)):
        with pytest.raises(ValueError, match=r"Day\.dual_year"):
            Day(year, dual_year=dual)


def test_a_day_is_1_to_31():
    assert Day(day=1).day == 1 and Day(1900, 1, 31).day == 31
    for bad in (0, 32, 45, -1):
        with pytest.raises(ValueError, match=r"Day\.day"):
            Day(1900, 1, bad)


@pytest.mark.parametrize(
    "raw",
    [
        "45 JAN 1900",
        "0 JAN 1900",
        "00 MAR 1900",
        "32 JAN",
        "ABT 32 DEC 1900",
        "BET 45 JAN 1900 AND 1910",
    ],
)
def test_a_day_number_outside_1_to_31_is_not_a_date_and_is_kept_as_text(raw):
    date = parse_date(raw)
    assert date.start is None and date.end is None and date.text == raw
    assert format_date(date) == raw


@pytest.mark.parametrize(
    "raw,text",
    [
        (HUGE, HUGE),
        (f"BET {HUGE} AND 1900", f"BET {HUGE} AND 1900"),
        ("99999", "99999"),
        ("0000", "0000"),
        ("000", "000"),
        ("10000", "10000"),
        ("5 JAN 12345", "5 JAN 12345"),
        ("00000099", "00000099"),
    ],
    ids=short,
)
def test_a_year_outside_1_to_9999_is_unreadable_and_kept_as_text(raw, text):
    date = parse_date(raw)
    assert date.start is None and date.text == text and date.year_unknown
    assert kincade.lang.format_date(date) == text


def test_a_year_0_in_text_is_no_year():
    assert (
        kincade.lang.year_of(Date("text", text="0000")) is None
        and kincade.lang.year_of(parse_date("0000")) is None
    )
    assert kincade.lang.year_of(Date("text", text="0000 or 1900")) is None
    assert kincade.charts.latest_birth_year(Date("text", text="0000"), 2026) is None


def test_the_largest_and_smallest_years_are_read():
    assert parse_date("9999") == Date("exact", Day(9999))
    assert parse_date("0001") == Date("exact", Day(1))
    assert parse_date("001") == Date("exact", Day(1))
    assert parse_date("9998/99") == Date("exact", Day(9998, dual_year=9999))
    assert parse_date("9999/00").text == "9999/00"  # the New Style year would be 10000


# ----------------------------------------------------------------
# a Date that contradicts itself is refused


@pytest.mark.parametrize(
    "args,message",
    [
        (("between", Day(1900)), "needs both start and end"),
        (("between",), "needs both start and end"),
        (("between", None, Day(1900)), "needs both start and end"),
        (("from_to", Day(1900)), "needs both start and end"),
        (("from_to", None, Day(1900)), "needs both start and end"),
        (
            ("from", Day(1900), Day(2000)),
            "Date.end",
        ),  # printed as "from 1900", yet bounded by 2000 for privacy
        (("to", Day(1900), Day(2000)), "Date.end"),
        (("exact", Day(1900), Day(2000)), "Date.end"),
        (("about", Day(1900), Day(2000)), "Date.end"),
        (("before", Day(1900), Day(2000)), "Date.end"),
        (("after", Day(1900), Day(2000)), "Date.end"),
        (("text", None, Day(2000)), "Date.end"),
        (("text",), "needs text"),
    ],
)
def test_a_date_that_contradicts_itself_is_refused_where_it_is_made(args, message):
    with pytest.raises(ValueError, match=message):
        Date(*args)


def test_the_error_names_the_form_and_what_is_missing():
    with pytest.raises(
        ValueError, match=r"Date.form 'between' needs both start and end"
    ):
        Date("between", Day(1900))
    with pytest.raises(
        ValueError,
        match=r"Date.end belongs to the forms 'between' and 'from_to', not 'from'",
    ):
        Date("from", Day(1900), Day(2000))
    with pytest.raises(ValueError, match=r"Date.form 'text' needs text"):
        Date("text")


@pytest.mark.parametrize(
    "fields",
    [
        {"form": "exact", "start": Day(1900)},
        {"form": "about", "start": Day(1900)},
        {"form": "before", "start": Day(1900)},
        {"form": "after", "start": Day(1900)},
        {"form": "from", "start": Day(1900)},
        {"form": "to", "start": Day(1900)},
        {"form": "between", "start": Day(1900), "end": Day(1905)},
        {"form": "from_to", "start": Day(1900), "end": Day(1905)},
        {"form": "text", "text": "spring"},
        {"form": "exact", "start": Day(1900), "text": "about then"},
        {
            "form": "between",
            "start": Day(1900),
            "end": Day(1905),
            "text": "the early years",
        },
        {"form": "after", "text": "after the war"},
        {"form": "from", "text": "FROM the census"},
        {"form": "about", "text": "Abt. 1900 or so"},
        {"form": "exact", "quality": "estimated"},
        {"form": "after"},  # no structure, no text: a form with nothing to say stands
    ],
)
def test_a_consistent_date_is_accepted(fields):
    date = Date(**fields)  # a refused date raises ValueError here
    assert {name: getattr(date, name) for name in fields} == fields


RAW_DATES = [
    "",
    "()",
    "( )",
    "INT ()",
    "INT 1900 ()",
    "INT (x)",
    "(x)",
    "INT 5 JAN 1900 (x)",
    "INT @#DHEBREW@ 10 TSH 5695 (autumn)",
    "BET 1900 AND",
    "BET AND 1900",
    "BET 1900 AND x",
    "BET x AND 1900",
    "FROM 1900 TO",
    "FROM TO 1900",
    "FROM x TO y",
    "FROM 1900",
    "TO 1900",
    "FROM",
    "TO",
    "AFT",
    "BEF",
    "ABT",
    "EST",
    "CAL",
    "~",
    "~ ",
    "BET",
    "BET 1900",
    "unknown",
    "1900",
    "1900/01",
    "1731/32",
    "BET 1731/32 AND 1735",
    "BET 1900 - 1905",
    "1900-1905",
    "ABT 1900-1905",
    "BET @#DJULIAN@ 1 JAN 1700 AND @#DJULIAN@ 1 JAN 1701",
    "FROM @#DHEBREW@ 5690 TO @#DHEBREW@ 5695",
    "@#DFRENCH R@ 1 VEND 3",
    "@#D@ 1900",
    "JULIAN",
    "HEBREW 5695",
    "12 MAY",
    "MAY",
    "12",
    "0",
]


@pytest.mark.parametrize(
    "raw", RAW_DATES, ids=[f"{n}-{raw[:24]}" for n, raw in enumerate(RAW_DATES)]
)
def test_the_reader_only_builds_valid_dates(raw):
    date = parse_date(raw)
    # a Date validates itself, so one that came back is valid
    assert date is None or isinstance(date, Date)
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", f"2 DATE {raw}"))
    assert tree.people["I1"].birth is not None


def test_the_reader_survives_every_shape_of_date_text():
    vocabulary = [
        "JAN",
        "feb",
        "MAR",
        "1",
        "05",
        "12",
        "31",
        "900",
        "1900",
        "1731/32",
        "99",
        "0099",
        "ABT",
        "EST",
        "CAL",
        "BEF",
        "AFT",
        "FROM",
        "TO",
        "BET",
        "AND",
        "INT",
        "-",
        "~",
        "(x)",
        "(",
        ")",
        "@#DJULIAN@",
        "@#DHEBREW@",
        "JULIAN",
        "or",
        "about",
        "ca",
        ".",
    ]
    rnd = random.Random(20261011)
    for _ in range(3000):
        text = " ".join(rnd.choice(vocabulary) for _ in range(rnd.randint(1, 7)))
        parse_date(text)  # must not raise


def test_an_empty_phrase_alone_is_kept_as_written():
    assert parse_date("()") == Date("text", text="()")
    # the date stands; there is no phrase to print
    assert parse_date("INT 1900 ()") == Date("exact", Day(1900))
    assert kincade.lang.format_date(parse_date("INT 1900 ()")) == "1900"
    # a date the reader cannot read, with no phrase to print instead: it prints as
    # written, with no year for the estimate
    assert parse_date("INT spring 1940 ()") == Date("text", text="spring 1940")
    assert (
        kincade.charts.latest_birth_year(parse_date("INT spring 1940 ()"), 2026) is None
    )

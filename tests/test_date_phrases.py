"""Date phrases and calendar words: which of them give a readable year."""

import datetime

import pytest

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade import Date, Day, read_gedcom
from kincade.charts import latest_birth_year, living_checker, open_birth
from kincade.gedcom import parse_date
from kincade.lang import format_date, year_of
from kincade.model import Event, Person, Tree, text_date

from conftest import (
    SECRETVILLE,
    five,
    render_charts,
    seven,
)
from pdfread import drawn


def alone(*date_lines):
    """A person with no death record and no descendants, born at `date_lines` (the lines
    under `1 BIRT`) in a place that is not for the public.
    """
    return read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME Pat /Doe/",
            "1 BIRT",
            *date_lines,
            f"2 PLAC {SECRETVILLE}",
        )
    )


def phrased(phrase):
    return alone("2 DATE", f"3 PHRASE {phrase}")


def plain(date):
    return alone(f"2 DATE {date}")


def birth_date(tree):
    return tree.people["I1"].birth.date


def place_shown(tree, **opts):
    """Whether the birth place is drawn when details of people who may be living are
    hidden.
    """
    return f"bp. {SECRETVILLE}" in drawn(
        render_charts(tree, exclude_private=True, **opts)
    )


def reading(tree):
    """Everything that reads a birth date for privacy or for --find, in one tuple."""
    date = birth_date(tree)
    return (
        kincade.charts.latest_birth_year(date, 2026),
        open_birth(date),
        year_of(date),
        living_checker(tree, [], 2026)("I1"),
        place_shown(tree),
    )


def find_output(tree_text, capsys, tmp_path, *args):
    path = tmp_path / "phrase.ged"
    path.write_bytes(tree_text)
    assert kincade.cli.main([str(path), "--find", "@I1@", *args]) == 0
    return capsys.readouterr().out


# (the phrase, the plain DATE that reads the same way)
PAIRS = [
    ("AFTER 1900", "AFT 1900"),
    ("after 1900", "AFT 1900"),
    ("Aft 1900", "AFT 1900"),
    ("aft. 1900", "AFT 1900"),
    ("about 1920", "ABT 1920"),
    ("ABOUT 1920", "ABT 1920"),
    ("Abt 1920", "ABT 1920"),
    ("circa 1920", "CIRCA 1920"),
    ("ca. 1920", "CA 1920"),
    ("~1920", "~1920"),
    ("est 1920", "EST 1920"),
    ("cal 1920", "CAL 1920"),
    ("CAL 1920", "CAL 1920"),
    ("Cal 1920", "CAL 1920"),
    ("before 1850", "BEF 1850"),
    ("BEFORE 1850", "BEF 1850"),
    ("bef 1850", "BEF 1850"),
    ("Bef. 1850", "BEF 1850"),
    ("from 1900", "FROM 1900"),
    ("from 1900 to 1910", "FROM 1900 TO 1910"),
    ("to 1910", "TO 1910"),
    ("bet 1890 and 1900", "BET 1890 AND 1900"),
    ("between 1890 and 1900", "BET 1890 AND 1900"),
]


# ---------------------------------------------------------------- AFTER a year


def test_a_phrase_after_a_year_stays_private():
    tree = phrased("AFTER 1900")
    assert living_checker(tree, [], 2026)("I1") is True
    assert not place_shown(tree)
    # not private: the place is drawn, so the above means it
    assert f"bp. {SECRETVILLE}" in drawn(render_charts(tree))


def test_a_phrase_after_a_year_is_open_ended_like_aft():
    date = birth_date(phrased("AFTER 1900"))
    assert date == Date("after", text="AFTER 1900")
    assert kincade.charts.latest_birth_year(date, 2026) == 2026
    assert open_birth(date) == (True, 1901)


def test_find_hides_the_years_of_a_phrase_after_a_year(capsys, tmp_path):
    source = seven(
        "0 @I1@ INDI",
        "1 NAME Pat /Doe/",
        "1 BIRT",
        "2 DATE",
        "3 PHRASE AFTER 1900",
        f"2 PLAC {SECRETVILLE}",
    )
    hidden = find_output(source, capsys, tmp_path, "--exclude-private")
    assert hidden == "I1\tLiving\t\n" and "1900" not in hidden
    # without --exclude-private it is a year like any other
    shown = find_output(source, capsys, tmp_path)
    assert shown == "I1\tPat DOE\t1900-\n"


# ----------------------------------------------------------------
# about, est, cal: ten years either way


@pytest.mark.parametrize(
    "phrase,quality", [("est 1920", "estimated"), ("Cal 1920", "calculated")]
)
def test_only_recognized_estimation_phrases_supply_a_year_and_quality(phrase, quality):
    tree = phrased(phrase)
    assert birth_date(tree) == Date("text", quality=quality, text=phrase)
    assert kincade.charts.latest_birth_year(birth_date(tree), 2026) == 1930
    assert not place_shown(tree)


# ----------------------------------------------------------------
# before: the year it names


def test_a_phrase_before_a_year_behaves_like_bef():
    tree = phrased("before 1850")
    assert kincade.charts.latest_birth_year(birth_date(tree), 2026) == 1850
    assert open_birth(birth_date(tree)) == (False, None)
    assert living_checker(tree, [], 2026)("I1") is False
    assert place_shown(tree)  # 1850 is old enough to show, as it is for BEF 1850
    assert reading(tree) == reading(plain("BEF 1850"))


# ----------------------------------------------------------------
# the same words as a plain DATE, in any case


@pytest.mark.parametrize("phrase,written", PAIRS)
def test_recognized_phrases_are_read_as_the_plain_date_of_the_same_words(
    phrase, written
):
    if phrase == "~1920":
        assert reading(phrased(phrase)) == (None, (False, None), None, True, False)
    else:
        assert reading(phrased(phrase)) == reading(plain(written))


@pytest.mark.parametrize("phrase", [pair[0] for pair in PAIRS])
def test_the_display_of_a_phrase_is_the_phrase_verbatim(phrase):
    tree = phrased(phrase)
    assert format_date(birth_date(tree)) == phrase
    assert f"b. {phrase}" in drawn(render_charts(tree))


def test_a_phrase_with_a_qualifier_is_read_the_same_way_in_the_other_events():
    source = seven(
        "0 @I1@ INDI",
        "1 NAME Pat /Doe/",
        "1 DEAT",
        "2 DATE",
        "3 PHRASE about 1920",
        "1 CHR",
        "2 DATE",
        "3 PHRASE AFTER 1900",
    )
    person = read_gedcom(source).people["I1"]
    assert person.death.date == Date("about", text="about 1920")
    assert person.christenings[0].date == Date("after", text="AFTER 1900")


# ----------------------------------------------------------------
# what the phrase does not change


@pytest.mark.parametrize(
    "phrase",
    ["autumn", "5 January (year unknown)", "the war", "in the year of the flood"],
)
def test_a_phrase_that_does_not_begin_with_a_qualifier_is_only_text(phrase):
    assert birth_date(phrased(phrase)) == Date("text", text=phrase)


def test_a_phrase_under_a_payload_that_reads_as_a_date_is_not_used():
    assert birth_date(alone("2 DATE BEF 1850", "3 PHRASE AFTER 1900")) == Date(
        "before", Day(1850)
    )


def test_the_same_phrase_in_parentheses_in_a_gedcom_5_date_is_read_the_same_way():
    assert parse_date("(AFTER 1900)") == Date("after", text="AFTER 1900")
    assert parse_date("(about 1920)") == Date("about", text="about 1920")
    assert parse_date("(autumn)") == Date("text", text="autumn")
    assert parse_date("()") == Date("text", text="()")


def born(source, *date_lines):
    """A person with no death record and no descendants, born at `date_lines` (the lines
    under `1 BIRT`) in a place that is not for the public, in a file made by `source`
    (`seven` or `five`).
    """
    return read_gedcom(
        source(
            "0 @I1@ INDI",
            "1 NAME Pat /Doe/",
            "1 BIRT",
            *date_lines,
            f"2 PLAC {SECRETVILLE}",
        )
    )


def parenthesized(phrase):
    return born(five, f"2 DATE ({phrase})")


def assert_private(tree):
    """The person is treated as possibly living: by the checker, and so by the PDF,
    which hides the birthplace."""
    # drawn without the option, so its absence below means it was hidden
    assert f"bp. {SECRETVILLE}" in drawn(render_charts(tree))
    assert living_checker(tree, [], 2026)("I1") is True
    assert not place_shown(tree)


def public(tree):
    return living_checker(tree, [], 2026)("I1") is False and place_shown(tree)


# ----------------------------------------------------------------
# a phrase with no readable year

UNREADABLE = [
    "@#DFRENCH R@ 100",
    "@#DHEBREW@ 5695",
    "@#DROMAN@ 1900",
    "FRENCH_R 100",
    "HEBREW 5695",
    "BET 10000 AND 1900",
    "12345",
    "5 JAN 0000",
]


@pytest.mark.parametrize("phrase", UNREADABLE)
def test_a_phrase_with_no_readable_year_keeps_its_person_private(phrase):
    tree = phrased(phrase)
    assert birth_date(tree).year_unknown
    assert kincade.charts.latest_birth_year(birth_date(tree), 2026) == 2026
    assert_private(tree)


@pytest.mark.parametrize("phrase", UNREADABLE)
def test_a_parenthesized_date_with_no_readable_year_keeps_its_person_private(phrase):
    tree = parenthesized(phrase)
    assert birth_date(tree).year_unknown
    assert kincade.charts.latest_birth_year(birth_date(tree), 2026) == 2026
    assert_private(tree)


@pytest.mark.parametrize("phrase", UNREADABLE)
def test_a_phrase_is_as_private_as_the_same_text_in_the_date_itself(phrase):
    direct = plain(phrase)
    assert birth_date(direct).year_unknown
    for tree in (phrased(phrase), parenthesized(phrase)):
        assert_private(tree)
        assert_private(direct)
        assert kincade.charts.latest_birth_year(
            birth_date(tree), 2026
        ) == kincade.charts.latest_birth_year(birth_date(direct), 2026)
        assert (
            open_birth(birth_date(tree))
            == open_birth(birth_date(direct))
            == (False, None)
        )


@pytest.mark.parametrize(
    "raw",
    [
        "(@#DFRENCH R@ 100)",
        "(BET 10000 AND 1900)",
        "(@#DHEBREW@ 5695)",
        "(HEBREW 10 TSH 5695)",
    ],
)
def test_parse_date_marks_a_parenthesized_phrase_with_no_readable_year(raw):
    date = parse_date(raw)
    assert date.year_unknown and date.start is None and date.text == raw[1:-1]


@pytest.mark.parametrize(
    "raw",
    [
        "(autumn)",
        "(about 1920)",
        "(AFTER 1900)",
        "(BET 1900 AND 1905)",
        "(Julian 5 MAR 1700)",
        "(@#DJULIAN@ 1700)",
        "(1700)",
        "()",
        "(Hebrew New Year)",
        "(Hebrew New Year 1890)",  # the word, not the calendar
    ],
)
def test_a_parenthesized_phrase_without_unreadable_calendar_or_number_is_unmarked(raw):
    assert not parse_date(raw).year_unknown


@pytest.mark.parametrize("phrase", UNREADABLE)
def test_the_display_of_a_phrase_with_no_readable_year_is_the_phrase_verbatim(phrase):
    for tree in (phrased(phrase), parenthesized(phrase)):
        assert format_date(birth_date(tree)) == phrase
        assert f"b. {phrase}" in drawn(render_charts(tree))


def test_find_hides_the_years_of_a_phrase_in_a_calendar_it_cannot_convert(
    capsys, tmp_path
):
    for source in (
        seven(
            "0 @I1@ INDI",
            "1 NAME Pat /Doe/",
            "1 BIRT",
            "2 DATE",
            "3 PHRASE @#DFRENCH R@ 100",
        ),
        five("0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", "2 DATE (@#DFRENCH R@ 100)"),
    ):
        assert (
            find_output(source, capsys, tmp_path, "--exclude-private")
            == "I1\tLiving\t\n"
        )


@pytest.mark.parametrize(
    "raw", ["INT 5 JAN 1990 (@#DFRENCH R@ 100)", "INT 1990 (about 10000)"]
)
def test_an_interpreted_date_with_a_reading_of_its_own_keeps_it(raw):
    """The phrase here is not the date's only reading, so the date's own reading rules
    apply."""
    date = parse_date(raw)
    assert not date.year_unknown and date.start is not None


# ----------------------------------------------------------------
# open-ended shapes and prose

OPEN = [
    "sometime after 1900",
    "born after 1900",
    "SOMETIME AFTER 1900",
    "sometime Aft. 1900",
    "born aft 1900",
    "born since 1900",
    "Since 1900",
    "no later than 1900 is known",
    "later than 1900",
    "1900 or later than that",
    "some time in 1900, or after",
]


@pytest.mark.parametrize("phrase", OPEN)
def test_only_recognized_open_ended_shapes_have_an_open_form(phrase):
    for date in (
        birth_date(phrased(phrase)),
        birth_date(plain(phrase)),
        parse_date(f"({phrase})"),
        parse_date(f"INT ({phrase})"),
    ):
        assert date.form == ("from" if phrase == "Since 1900" else "text")
        assert date.text == phrase and not date.year_unknown
        assert kincade.charts.latest_birth_year(date, 2026) == (
            2026 if phrase == "Since 1900" else None
        )


@pytest.mark.parametrize("phrase", OPEN[:8])
def test_a_phrase_or_text_after_a_year_keeps_its_person_private(phrase):
    for tree in (phrased(phrase), plain(phrase), parenthesized(phrase)):
        assert_private(tree)
        assert open_birth(birth_date(tree)) == (
            (True, 1900) if phrase == "Since 1900" else (False, None)
        )


@pytest.mark.parametrize("phrase", ["sometime after 1900", "born after 1900"])
def test_an_after_word_in_prose_does_not_supply_a_year(phrase):
    for tree in (phrased(phrase), plain(phrase)):
        assert (
            living_checker(tree, [], 2026)("I1")
            is living_checker(plain("AFT 1900"), [], 2026)("I1")
            is True
        )
        assert open_birth(birth_date(tree)) == (False, None)
        assert year_of(birth_date(tree)) is None


@pytest.mark.parametrize("phrase", ["sometime after 1900", "born after 1900"])
def test_find_hides_the_years_of_text_after_a_year(phrase, capsys, tmp_path):
    for source in (
        seven(
            "0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", "2 DATE", f"3 PHRASE {phrase}"
        ),
        seven("0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", f"2 DATE {phrase}"),
    ):
        assert (
            find_output(source, capsys, tmp_path, "--exclude-private")
            == "I1\tLiving\t\n"
        )
        assert find_output(source, capsys, tmp_path) == "I1\tPat DOE\t\n"


@pytest.mark.parametrize(
    "date_lines",
    [
        ("2 DATE", "3 PHRASE sometime after 1900"),
        ("2 DATE sometime after 1900",),
        ("2 DATE AFT 1900",),
    ],
)
def test_birth_readings_control_the_estimate_under_a_dated_child(date_lines):
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME Pat /Doe/",
            "1 BIRT",
            *date_lines,
            "1 FAMS @F1@",
            "0 @F1@ FAM",
            "1 HUSB @I1@",
            "1 CHIL @I2@",
            "0 @I2@ INDI",
            "1 NAME Kid /Doe/",
            "1 FAMC @F1@",
            "1 BIRT",
            "2 DATE 1910",
        )
    )
    estimates = kincade.charts._birth_estimates(
        tree, kincade.charts.plan_charts(tree, "I2"), 2026
    )
    assert estimates["I1"] == (1901 if date_lines == ("2 DATE AFT 1900",) else 2026)


@pytest.mark.parametrize(
    "phrase",
    [
        "Rafter 1900",
        "Afterton 1900",
        "laterally than 1900",
        "latter 1900",
        "sometime in 1900",
    ],
)
def test_a_word_that_only_contains_an_open_ended_word_is_not_one(phrase):
    for tree in (phrased(phrase), plain(phrase)):
        assert birth_date(tree) == Date("text", text=phrase)
        assert kincade.charts.latest_birth_year(birth_date(tree), 2026) is None
        assert_private(tree)


@pytest.mark.parametrize("phrase", OPEN)
def test_the_display_of_open_ended_text_is_the_text_verbatim(phrase):
    for tree in (phrased(phrase), plain(phrase), parenthesized(phrase)):
        assert format_date(birth_date(tree)) == phrase
    assert f"b. {phrase}" in drawn(render_charts(phrased(phrase)))


# ----------------------------------------------------------------
# approximation shapes and prose

ABOUT = [
    "born circa 1920",
    "born about 1920",
    "sometime abt 1920",
    "he was ca. 1920",
    "somewhere CIRCA 1920",
    "Born ABOUT 1920",
    "born ca 1920",
    "thought to be about 1920",
]


# a plain DATE of these is a structure (abt 1920)
LEADING = ["circa 1920", "about 1920", "Abt 1920", "ca. 1920"]


def about_trees(phrase):
    """The same text as a PHRASE, as a GEDCOM 5 (phrase) and, where it is no date this
    reader knows, as a plain DATE.
    """
    trees = [phrased(phrase), parenthesized(phrase)]
    return trees if phrase in LEADING else [*trees, plain(phrase)]


@pytest.mark.parametrize("phrase", ABOUT + LEADING)
def test_only_recognized_approximation_shapes_allow_ten_years_later(phrase):
    for tree in about_trees(phrase):
        date = birth_date(tree)
        assert date.form == ("about" if phrase in LEADING else "text")
        assert not date.year_unknown
        assert kincade.charts.latest_birth_year(date, 2026) == (
            1930 if phrase in LEADING else None
        )
        assert open_birth(date) == (False, None)
    for tree in about_trees(phrase)[:2]:
        assert birth_date(tree).text == phrase


@pytest.mark.parametrize("phrase", ABOUT + LEADING)
def test_approximation_shapes_and_yearless_prose_keep_a_birth_private(phrase):
    this_year = datetime.date.today().year
    older = phrase.replace("1920", str(this_year - 105))
    for tree in about_trees(older):
        assert kincade.charts.latest_birth_year(birth_date(tree), this_year) == (
            this_year - 95 if phrase in LEADING else None
        )
        assert living_checker(tree, [], this_year)("I1") is True
    # the year alone is old enough
    assert living_checker(plain(str(this_year - 105)), [], this_year)("I1") is False


@pytest.mark.parametrize(
    "phrase", ["born circa 1920", "sometime about 1920", "circa 1920", "about 1920"]
)
def test_only_recognized_approximation_shapes_supply_an_index_year(phrase):
    for tree in about_trees(phrase):
        assert (
            living_checker(tree, [], 2026)("I1")
            is living_checker(plain("ABT 1920"), [], 2026)("I1")
            is True
        )
        assert not place_shown(tree) and not place_shown(plain("ABT 1920"))
        assert year_of(birth_date(tree)) == (1920 if phrase in LEADING else None)


@pytest.mark.parametrize(
    "phrase", ["born circa 1920", "sometime about 1920", "circa 1920", "about 1920"]
)
def test_find_hides_the_years_of_text_about_a_year_that_reaches_into_the_last_100(
    phrase, capsys, tmp_path
):
    # --find counts from today: 10 years on is within the last 100, the year is not
    year = datetime.date.today().year - 105
    text = phrase.replace("1920", str(year))
    for source in (
        seven(
            "0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", "2 DATE", f"3 PHRASE {text}"
        ),
        seven("0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", f"2 DATE {text}"),
    ):
        assert (
            find_output(source, capsys, tmp_path, "--exclude-private")
            == "I1\tLiving\t\n"
        )
        expected = f"{year}-" if phrase in LEADING else ""
        assert find_output(source, capsys, tmp_path) == f"I1\tPat DOE\t{expected}\n"


@pytest.mark.parametrize(
    "phrase",
    ["Cabot 1920", "Abouts 1920", "circadian 1920", "sometime in 1920", "ABTX 1920"],
)
def test_a_word_that_only_contains_an_about_word_is_not_one(phrase):
    for tree in (phrased(phrase), plain(phrase)):
        assert birth_date(tree) == Date("text", text=phrase)
        assert kincade.charts.latest_birth_year(birth_date(tree), 2026) is None


@pytest.mark.parametrize("phrase", ABOUT + LEADING)
def test_the_display_of_about_text_is_the_text_verbatim(phrase):
    for tree in about_trees(phrase):
        # a plain "circa 1920" is a structure, and prints as one (abt 1920)
        if birth_date(tree).text:
            assert format_date(birth_date(tree)) == phrase
    assert f"b. {phrase}" in drawn(render_charts(phrased(phrase)))
    assert format_date(birth_date(plain("circa 1920"))) == "abt 1920"


# ----------------------------------------------------------------
# both words, the leading word, and structured dates


def test_prose_with_open_ended_and_about_words_has_no_date_reading():
    for phrase in (
        "about 1920, or after",
        "sometime after circa 1920",
        "circa 1920 or later than that",
    ):
        for tree in (phrased(phrase), plain(phrase)):
            assert birth_date(tree).form == "text"
            assert kincade.charts.latest_birth_year(birth_date(tree), 2026) is None
            assert_private(tree)


def test_an_unreadable_year_wins_over_an_open_ended_word():
    for tree in (
        phrased("@#DFRENCH R@ after 100"),
        parenthesized("@#DFRENCH R@ after 100"),
        plain("@#DFRENCH R@ after 100"),
    ):
        assert birth_date(tree).year_unknown and open_birth(birth_date(tree)) == (
            False,
            None,
        )
        assert_private(tree)


def test_the_whole_shape_of_a_phrase_decides_its_form():
    assert birth_date(phrased("AFTER 1900")) == Date("after", text="AFTER 1900")
    assert birth_date(phrased("~1920")) == Date("text", text="~1920")
    assert birth_date(phrased("est 1920")) == Date(
        "text", quality="estimated", text="est 1920"
    )
    assert birth_date(phrased("from 1900")) == Date("from", text="from 1900")
    assert birth_date(phrased("from 1900 to 1950")) == Date(
        "text", text="from 1900 to 1950"
    )
    assert birth_date(phrased("before 1850")) == Date("before", text="before 1850")
    assert birth_date(phrased("in the spring of 1850")) == Date(
        "text", text="in the spring of 1850"
    )


def test_a_structured_date_is_not_free_text():
    """The words are read in free text, not in a date with a structure: ABT and AFT
    before a date are the structure.
    """
    assert parse_date("ABT 1920") == Date("about", kincade.Day(1920))
    assert parse_date("AFT 1900") == Date("after", kincade.Day(1900))
    assert parse_date("BEF 1850") == Date("before", kincade.Day(1850))
    assert parse_date("BET 1900 AND 1950").form == "between"


THIS_YEAR = 2026


HEBREW_MONTHS = [
    "TSH",
    "CSH",
    "KSL",
    "TVT",
    "SHV",
    "ADR",
    "ADS",
    "NSN",
    "IYR",
    "SVN",
    "TMZ",
    "AAV",
    "ELL",
]


FRENCH_MONTHS = [
    "VEND",
    "BRUM",
    "FRIM",
    "NIVO",
    "PLUV",
    "VENT",
    "GERM",
    "FLOR",
    "PRAI",
    "MESS",
    "THER",
    "FRUC",
    "COMP",
]


def place_drawn(tree, **opts):
    return f"bp. {SECRETVILLE}" in drawn(render_charts(tree, **opts))


def unreadable(raw):
    date = parse_date(raw)
    return date.year_unknown and latest_birth_year(date, THIS_YEAR) == THIS_YEAR


# ----------------------------------------------------------------
# the word Hebrew in a phrase


def test_a_phrase_that_mentions_hebrew_is_prose_without_a_date_reading():
    date = parse_date("(Hebrew New Year 1890)")
    assert date.text == "Hebrew New Year 1890" and not date.year_unknown
    assert (
        latest_birth_year(date, THIS_YEAR)
        is latest_birth_year(parse_date("(New Year 1890)"), THIS_YEAR)
        is None
    )


def test_free_text_that_mentions_hebrew_is_prose_without_a_date_reading():
    date = parse_date("born in the Hebrew month of Nisan, 1890")
    assert (
        date.text == "born in the Hebrew month of Nisan, 1890" and not date.year_unknown
    )
    assert latest_birth_year(date, THIS_YEAR) is None


def test_an_interpreted_date_with_hebrew_in_its_phrase_is_read_for_its_year():
    date = parse_date("INT 1890 (Hebrew New Year)")
    assert not date.year_unknown and latest_birth_year(date, THIS_YEAR) == 1890


@pytest.mark.parametrize("raw", ["HEBREW 1 TSH 5650", "@#DHEBREW@ 1 TSH 5650"])
def test_a_hebrew_date_has_no_readable_year(raw):
    assert unreadable(raw)


# ----------------------------------------------------------------
# the word where it is prose


@pytest.mark.parametrize(
    "raw",
    [
        "(Hebrew New Year 1890)",
        "(hebrew new year 1890)",
        "(HEBREW NEW YEAR 1890)",
        "Hebrew New Year 1890",
        "born in the Hebrew month of Nisan, 1890",
        "(1890, by the Hebrew calendar)",
        "(Hebrew: Rosh Hashanah 1890)",
        "(Hebrew school record 1890)",
        "(Hebrew tshirt 1890)",
        "(Hebrew Ellis Island record 1890)",  # a month code counts only as a whole word
    ],
)
def test_the_word_hebrew_in_prose_does_not_mark_a_calendar(raw):
    date = parse_date(raw)
    assert not date.year_unknown
    assert latest_birth_year(date, THIS_YEAR) is None


def test_a_phrase_that_mentions_hebrew_and_names_no_year_is_like_any_other():
    assert (
        parse_date("(Hebrew New Year)").year_unknown
        is parse_date("(New Year)").year_unknown
        is False
    )
    assert latest_birth_year(parse_date("(Hebrew New Year)"), THIS_YEAR) is None


# ----------------------------------------------------------------
# the GEDCOM 7 calendar keywords: no readable year


@pytest.mark.parametrize(
    "raw",
    [
        "HEBREW 1 TSH 5650",
        "HEBREW TSH 5650",
        "HEBREW 5650",
        "HEBREW 10 TSH 5695",
        "hebrew 1 tsh 5650",
        "Hebrew 1 Tsh 5650",
        "hebrew 5650",
        "BET HEBREW 1 TSH 5650 AND HEBREW 2 TSH 5650",
        "BET HEBREW 5650 AND HEBREW 5651",
        "FROM HEBREW 1 TSH 5650 TO HEBREW 1 NSN 5651",
        "FROM HEBREW 5650",
        "TO HEBREW 5650",
        "ABT HEBREW 5650",
        "AFT HEBREW 1 TSH 5650",
        "BEF HEBREW TSH 5650",
        "EST HEBREW 5650",
        "INT HEBREW 1 TSH 5650 (Rosh Hashanah)",
        "(HEBREW 1 TSH 5650)",
        "(hebrew 5650)",
        # the keyword with a date after it counts wherever it stands, as an escape does
        "(born HEBREW 1 TSH 5650)",
        *[f"HEBREW 1 {month} 5650" for month in HEBREW_MONTHS],
        *[f"HEBREW {month} 5650" for month in HEBREW_MONTHS],
        *[f"HEBREW {month.lower()} 5650" for month in HEBREW_MONTHS],
    ],
)
def test_a_gedcom_7_hebrew_date_has_no_readable_year(raw):
    assert unreadable(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "FRENCH_R 1 VEND 1",
        "FRENCH_R VEND 1",
        "FRENCH_R 1",
        "FRENCH_R 3",
        "french_r 1 vend 1",
        "French_R 1 Vend 1",
        "FROM FRENCH_R 1 VEND 1 TO FRENCH_R 5 COMP 1",
        "BET FRENCH_R 1 VEND 1 AND FRENCH_R 1 BRUM 2",
        "ABT FRENCH_R 1 VEND 12",
        "INT FRENCH_R 1 VEND 3 (x)",
        "(FRENCH_R 1 VEND 1)",
        "@#DFRENCH R@ 1 VEND 1",
        "(@#DFRENCH R@ 1 VEND 1)",
        "FRENCH_R AN XII",
        # never an English word: it counts wherever it stands
        "(FRENCH_R calendar, year XII)",
        *[f"FRENCH_R 1 {month} 1" for month in FRENCH_MONTHS],
        *[f"FRENCH_R {month} 1" for month in FRENCH_MONTHS],
    ],
)
def test_a_french_republican_date_has_no_readable_year(raw):
    assert unreadable(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "@#DHEBREW@ 5650",
        "(@#DHEBREW@ New Year)",
        "(born @#DHEBREW@ sometime 1890)",
        "@#DROMAN@ 1900",
        "@#D@ 1900",
        "(12345)",
        "(Hebrew New Year 0000)",
        "(Hebrew year 56500)",
    ],
)
def test_escapes_and_numbers_that_are_no_year_count_anywhere(raw):
    assert unreadable(raw)


# ---------------------------------------------------------------- read from a file


def test_a_gedcom_7_phrase_that_mentions_hebrew_is_prose_without_a_date_reading():
    date = birth_date(born(seven, "2 DATE", "3 PHRASE Hebrew New Year 1890"))
    assert date.text == "Hebrew New Year 1890" and date.start is None
    assert not date.year_unknown and latest_birth_year(date, THIS_YEAR) is None


def test_a_gedcom_7_phrase_that_is_a_hebrew_date_has_no_readable_year():
    date = birth_date(born(seven, "2 DATE", "3 PHRASE HEBREW 1 TSH 5650"))
    assert date.year_unknown and latest_birth_year(date, THIS_YEAR) == THIS_YEAR


def test_a_gedcom_7_hebrew_date_with_a_phrase_has_no_readable_year():
    date = birth_date(
        born(seven, "2 DATE HEBREW 1 TSH 5650", "3 PHRASE Hebrew New Year 1890")
    )
    assert date.year_unknown and latest_birth_year(date, THIS_YEAR) == THIS_YEAR


# ---------------------------------------------------------------- privacy


def test_a_person_born_on_yearless_prose_that_mentions_hebrew_stays_private():
    tree = born(five, "2 DATE (Hebrew New Year 1890)")
    assert living_checker(tree, [], THIS_YEAR)("I1") is True
    assert not place_drawn(tree, exclude_private=True)


@pytest.mark.parametrize(
    "source,lines",
    [
        (five, ["2 DATE HEBREW 1 TSH 5650"]),
        (five, ["2 DATE @#DHEBREW@ 1 TSH 5650"]),
        (five, ["2 DATE (HEBREW 1 TSH 5650)"]),
        (seven, ["2 DATE", "3 PHRASE HEBREW 1 TSH 5650"]),
        (five, ["2 DATE FRENCH_R 1 VEND 1"]),
        (five, ["2 DATE (Hebrew New Year)"]),
    ],
)
def test_a_person_born_on_a_date_with_no_readable_year_stays_private(source, lines):
    tree = born(source, *lines)
    # drawn without the option, so its absence below means it was hidden
    assert place_drawn(tree)
    assert living_checker(tree, [], THIS_YEAR)("I1") is True
    assert not place_drawn(tree, exclude_private=True)


# ----------------------------------------------------------------
# recognized whole-text shapes


@pytest.mark.parametrize("case", ["lower", "upper", "title"])
@pytest.mark.parametrize(
    "text,structured",
    [
        ("cal 1920", "CAL 1920"),
        ("from 1900", "FROM 1900"),
        ("from 1900 to 1910", "FROM 1900 TO 1910"),
        ("to 1910", "TO 1910"),
        ("bet 1890 and 1900", "BET 1890 AND 1900"),
        ("between 1890 and 1900", "BET 1890 AND 1900"),
        ("abt 1920", "ABT 1920"),
        ("est 1920", "EST 1920"),
        ("bef 1900", "BEF 1900"),
        ("aft 1900", "AFT 1900"),
    ],
)
def test_gedcom_words_have_their_structured_form_and_quality_in_text(
    text, structured, case
):
    assert text_date(f"  {getattr(text, case)()}  ") == parse_date(structured)


def test_a_tilde_phrase_has_no_text_date_shape():
    assert text_date("~1920") is None
    assert year_of(Date("text", text="~1920")) is None
    assert latest_birth_year(Date("text", text="~1920"), 2026) is None


@pytest.mark.parametrize(
    "text",
    [
        "12/05/1900",
        "12.5.1900",
        "12-05-1900",
        "1900/05/12",
        "1900.05.12",
        "1900-05-12",
        "31/12/1900",
        "12/31/1900",
    ],
)
def test_numeric_date_shapes_supply_only_the_year(text):
    assert text_date(f"  {text}  ") == Date("exact", Day(1900))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1765-1767", Date("between", Day(1765), Day(1767))),
        ("1731/32", Date("exact", Day(1731, dual_year=1732))),
    ],
)
def test_ranges_and_double_years_have_distinct_numeric_shapes(text, expected):
    assert text_date(text) == expected
    assert year_of(Date("text", text=text)) == expected.start.year
    assert latest_birth_year(Date("text", text=text), 2026) == latest_birth_year(
        expected, 2026
    )


@pytest.mark.parametrize(
    "text,shown,latest,opened",
    [
        ("c1900", 1900, 1910, (False, None)),
        ("c. 1900", 1900, 1910, (False, None)),
        ("ca 1900", 1900, 1910, (False, None)),
        ("ca. 1900", 1900, 1910, (False, None)),
        ("circa 1900", 1900, 1910, (False, None)),
        ("abt. 1900", 1900, 1910, (False, None)),
        ("about 1900", 1900, 1910, (False, None)),
        ("approx. 1900", 1900, 1910, (False, None)),
        ("est. 1900", 1900, 1910, (False, None)),
        ("  APPROX.1900  ", 1900, 1910, (False, None)),
        ("abt 850", 850, 860, (False, None)),
        ("cal 1920", 1920, 1930, (False, None)),
        ("from 1900", 1900, 2026, (True, 1900)),
        ("from 1900 to 1910", 1900, 1910, (False, None)),
        ("to 1910", 1910, 1910, (False, None)),
        ("bet 1890 and 1900", 1890, 1900, (False, None)),
        ("between 1890 and 1900", 1890, 1900, (False, None)),
        ("12/05/1900", 1900, 1900, (False, None)),
        ("12.5.1900", 1900, 1900, (False, None)),
        ("12-05-1900", 1900, 1900, (False, None)),
        ("1900/05/12", 1900, 1900, (False, None)),
        ("1900.05.12", 1900, 1900, (False, None)),
        ("1900-05-12", 1900, 1900, (False, None)),
        ("12/05/1926", 1926, 1926, (False, None)),
        ("1927-05-12", 1927, 1927, (False, None)),
        ("1920s", 1920, 1929, (False, None)),
        ("1920S", 1920, 1929, (False, None)),
        ("1920's", 1920, 1929, (False, None)),
        ("1920’s", 1920, 1929, (False, None)),
        ("850s", 850, 859, (False, None)),
        ("1765-1767", 1765, 1767, (False, None)),
        ("1765–1767", 1765, 1767, (False, None)),
        ("1765 to 1767", 1765, 1767, (False, None)),
        ("  850 TO 852  ", 850, 852, (False, None)),
        ("by Dec 1879", 1879, 1879, (False, None)),
        ("BY 12 DEC. 1879", 1879, 1879, (False, None)),
        ("bef. 1879", 1879, 1879, (False, None)),
        ("before 1879", 1879, 1879, (False, None)),
        ("by 850", 850, 850, (False, None)),
        ("aft. 1879", 1879, 2026, (True, 1880)),
        ("after 1879", 1879, 2026, (True, 1880)),
        ("since 1879", 1879, 2026, (True, 1879)),
        ("after 12 DEC 850", 850, 2026, (True, 851)),
        ("1731/32", 1731, 1732, (False, None)),
        ("1731/2", 1731, 1732, (False, None)),
        ("1699/00", 1699, 1700, (False, None)),
        ("899/0", 899, 900, (False, None)),
    ],
)
def test_whole_text_date_shapes_supply_the_index_and_privacy_readings(
    text, shown, latest, opened
):
    dates = [
        parse_date(text),
        parse_date(f"({text.strip()})"),
        birth_date(phrased(text)),
        Date("text", text=text),
    ]
    for date in dates:
        assert year_of(date) == shown
        assert latest_birth_year(date, 2026) == latest
        assert open_birth(date) == opened
        person = Person("I12", birth=Event(date))
        assert living_checker(Tree(people={"I12": person}), [], 2026)("I12") is (
            latest > 1926
        )
        if date.text:
            assert format_date(date) == date.text


@pytest.mark.parametrize(
    "text",
    [
        "born at 123 Main Street",
        "house 1234 Elm",
        "born in 1850, perhaps",
        "sometime after 1900",
        "born circa 1920",
        "about 1900 or so",
        "before the 1900 census",
        "born cal 1900",
        "from 1900 to 1910 or so",
        "between 1890 and 1900 perhaps",
        "born 12/05/1900",
        "12/1900/05",
        "12/05/900",
        "1731/33",
        "1921s",
        "AD 900",
        "approximately 1900",
        "by 45 DEC 1879",
        "after 1900, before 1920",
        "foo 1765-1767",
        "1765-1767 bar",
    ],
)
def test_unrecognized_date_text_is_undated_and_keeps_a_recorded_birth_private(text):
    for tree in (plain(text), phrased(text), parenthesized(text)):
        date = birth_date(tree)
        assert year_of(date) is None
        assert latest_birth_year(date, 2026) is None
        assert open_birth(date) == (False, None)
        assert_private(tree)
        assert format_date(date) == text


@pytest.mark.parametrize("decade", ["1920s", "1920S", "1920's", "1920’s"])
def test_a_decade_birth_allows_its_last_year_at_the_privacy_boundary(decade):
    for tree in (plain(decade), phrased(decade)):
        assert latest_birth_year(birth_date(tree), 2026) == 1929
        assert_private(tree)


def test_unrecognized_date_text_sorts_as_undated_in_the_index():
    people = {
        "I1": Person("I1", "Jane", "Doe", birth=Event(Date("text", text="c1950"))),
        "I2": Person("I2", "Jane", "Doe", birth=Event(Date("text", text="born 1850"))),
        "I3": Person("I3", "Jane", "Doe", birth=Event(Date("text", text="1765–1767"))),
    }
    index = kincade.pdf.build_index(
        Tree(people=people),
        [
            kincade.charts.Chart(
                1, {**dict.fromkeys(range(1, 16)), 1: "I1", 2: "I2", 3: "I3"}
            )
        ],
        lambda pid: False,
        exclude_private=False,
    )
    assert index == [
        "DOE, Jane (b. 1765), 1-3",
        "DOE, Jane (b. 1950), 1-1",
        "DOE, Jane, 1-2",
    ]


def test_find_uses_whole_text_shapes_for_years(capsys, tmp_path):
    path = tmp_path / "shapes.ged"
    path.write_bytes(
        seven(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            "1 BIRT",
            "2 DATE",
            "3 PHRASE born at 123 Main Street",
            "0 @I2@ INDI",
            "1 NAME John /Doe/",
            "1 CHR",
            "2 DATE",
            "3 PHRASE approx. 850",
            "1 BURI",
            "2 DATE 900–920",
            "0 @I3@ INDI",
            "1 NAME Jane /Doe/",
            "1 BIRT",
            "2 DATE c1900",
        )
    )
    for args in ([], ["--exclude-private"]):
        assert kincade.cli.main([str(path), "--find", "doe", *args]) == 0
        assert capsys.readouterr().out.splitlines() == [
            "I1\tLiving\t" if args else "I1\tJane DOE\t",
            "I2\tJohn DOE\t850-900",
            "I3\tJane DOE\t1900-",
        ]


@pytest.mark.parametrize("quality", ["estimated", "calculated"])
@pytest.mark.parametrize("text", ["by 1920", "1910-1920", "about 1920", "c1920"])
@pytest.mark.parametrize("start", [None, Day(month=5)])
def test_date_quality_applies_when_a_text_shape_supplies_the_birth_year(
    quality, text, start
):
    date = Date("exact" if start else "text", start, quality=quality, text=text)
    assert latest_birth_year(date, 2026) == 1930
    person = Person("I1", "Jane", "Doe", birth=Event(date, SECRETVILLE))
    tree = Tree(people={"I1": person})
    assert living_checker(tree, [], 2026)("I1") is True
    assert not place_shown(tree)


@pytest.mark.parametrize("text", ["by 1920", "1910-1920"])
def test_an_explicit_about_form_allows_ten_years_beyond_a_text_shape(text):
    assert latest_birth_year(Date("about", text=text), 2026) == 1930


@pytest.mark.parametrize("form,floor", [("after", 1921), ("from", 1920)])
@pytest.mark.parametrize("text", ["by 1920", "1910-1920"])
def test_an_explicit_open_form_keeps_its_floor_when_text_supplies_the_year(
    form, floor, text
):
    date = Date(form, text=text)
    assert latest_birth_year(date, 2026) == 2026
    assert open_birth(date) == (True, floor)


@pytest.mark.parametrize("case", ["lower", "upper", "title"])
@pytest.mark.parametrize("text", ["1900", "MAY 1900", "12 MAY 1900"])
def test_plain_whole_text_dates_have_their_structured_reading(text, case):
    text = getattr(text, case)()
    expected = parse_date(text.upper())
    assert text_date(f"  {text}  ") == expected
    for date in (Date("text", text=text), birth_date(phrased(text))):
        assert year_of(date) == 1900
        assert latest_birth_year(date, 2026) == 1900
        assert format_date(date) == text


@pytest.mark.parametrize("case", ["lower", "upper", "title"])
@pytest.mark.parametrize(
    "month",
    [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
)
@pytest.mark.parametrize(
    "shape", ["{month} 1900", "12 {month} 1900", "by {month} 1900"]
)
def test_full_english_months_supply_the_date_reading(month, shape, case):
    text = getattr(shape.format(month=month), case)()
    abbreviated = shape.format(month=month[:3]).upper()
    structured = parse_date(abbreviated.replace("BY ", "BEF "))
    assert text_date(f"  {text}  ") == structured
    for date in (birth_date(plain(text)), birth_date(phrased(text))):
        assert year_of(date) == 1900
        assert latest_birth_year(date, 2026) == 1900
        assert (
            living_checker(
                Tree(people={"I12": Person("I12", birth=Event(date))}), [], 2026
            )("I12")
            is False
        )


def test_a_full_month_after_date_keeps_its_open_birth_bound():
    date = Date("text", text="after 12 December 1900")
    assert text_date(date.text) == Date("after", Day(1900, 12, 12))
    assert open_birth(date) == (True, 1901)
    assert latest_birth_year(date, 2026) == 2026

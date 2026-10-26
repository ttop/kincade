"""How one GEDCOM DATE value comes out: the box text, the index year, and whether the
person counts as possibly living."""

import random

import pytest

from kincade.gedcom import parse_date, read_gedcom

from conftest import HUGE, SECRETVILLE, ged, render, seven, short
from pdfread import drawn

# Each row is a person born on the date in SECRETVILLE, with no death and no family.
# "lines" are the BIRT substructure's lines after "1 BIRT"; "seven_file" selects the
# GEDCOM 7 builder. "printed" is the box text after "b. "; "year" is the index year, or
# None; "private" is whether Secretville is hidden under exclude_private.
ROWS = [
    ("13 JAN 1917", ("2 DATE 13 JAN 1917",), "13 Jan 1917", 1917, False, False),
    ("ABT 1930", ("2 DATE ABT 1930",), "abt 1930", 1930, True, False),
    (
        "BEF. 6 SEP 1730",
        ("2 DATE BEF. 6 SEP 1730",),
        "bef 6 Sep 1730",
        1730,
        False,
        False,
    ),
    ("AFT 1900", ("2 DATE AFT 1900",), "aft 1900", 1900, True, False),
    (
        "BET 1900 AND 2000",
        ("2 DATE BET 1900 AND 2000",),
        "1900-2000",
        1900,
        True,
        False,
    ),
    (
        "28 FEB 1734/35",
        ("2 DATE 28 FEB 1734/35",),
        "28 Feb 1734/35",
        1734,
        False,
        False,
    ),
    (
        "@#DJULIAN@ 5 MAR 1700",
        ("2 DATE @#DJULIAN@ 5 MAR 1700",),
        "5 Mar 1700",
        1700,
        False,
        False,
    ),
    (
        "@#DHEBREW@ 1 TSH 5650",
        ("2 DATE @#DHEBREW@ 1 TSH 5650",),
        "@#DHEBREW@ 1 TSH 5650",
        None,
        True,
        False,
    ),
    (
        "INT 12 JAN 1900 (about then)",
        ("2 DATE INT 12 JAN 1900 (about then)",),
        "about then",
        1900,
        False,
        False,
    ),
    ("1920s", ("2 DATE 1920s",), "1920s", 1920, True, False),
    ("12/05/1900", ("2 DATE 12/05/1900",), "12/05/1900", 1900, False, False),
    (
        "sometime after 1900",
        ("2 DATE sometime after 1900",),
        "sometime after 1900",
        None,
        True,
        False,
    ),
    ("5 MAR 85", ("2 DATE 5 MAR 85",), "5 MAR 85", None, True, False),
    (
        HUGE,
        (f"2 DATE {HUGE}",),
        "999999999999999999999999999999999999999999999…",  # the box truncates it
        None,
        True,
        False,
    ),
    (
        "GEDCOM 7 PHRASE about 1920",
        ("2 DATE", "3 PHRASE about 1920"),
        "about 1920",
        1920,
        True,
        True,
    ),
    # the four rows below guard against a misreading that would change the year or the
    # privacy verdict
    (
        "5 March 1900",  # a full English month name, not the GEDCOM abbreviation
        ("2 DATE 5 March 1900",),
        "5 March 1900",
        1900,
        False,
        False,
    ),
    (
        "abt. 1900",  # an abbreviation with a dot
        ("2 DATE abt. 1900",),
        "abt 1900",
        1900,
        False,
        False,
    ),
    (
        "Since 1900",  # an open-ended phrase: never too old to be living
        ("2 DATE Since 1900",),
        "Since 1900",
        1900,
        True,
        False,
    ),
    (
        "circadian 1920",  # "circa" is inside the word, but this is not an about-date
        ("2 DATE circadian 1920",),
        "circadian 1920",
        None,
        True,
        False,
    ),
    (
        "between 1990 and 2000",  # a range in prose: its years still count
        ("2 DATE between 1990 and 2000",),
        "between 1990 and 2000",
        1990,
        True,
        False,
    ),
    (
        "1731/32",  # a double year written as text
        ("2 DATE 1731/32",),
        "1731/32",
        1731,
        False,
        False,
    ),
]


@pytest.mark.parametrize(
    "raw,lines,printed,year,private,seven_file",
    ROWS,
    ids=[short(row[0]) for row in ROWS],
)
def test_a_birth_date_prints_indexes_and_hides_as_written(
    raw, lines, printed, year, private, seven_file
):
    builder = seven if seven_file else ged
    tree = read_gedcom(
        builder(
            "0 @I1@ INDI",
            "1 NAME Pat /Doe/",
            "1 BIRT",
            *lines,
            f"2 PLAC {SECRETVILLE}",
        )
    )
    public = drawn(render(tree, "I1"))
    hidden = drawn(render(tree, "I1", exclude_private=True))
    assert f"b. {printed}" in public, raw
    index_entry = f"DOE, Pat (b. {year}), 1-1" if year is not None else "DOE, Pat, 1-1"
    assert index_entry in public, raw
    assert (f"bp. {SECRETVILLE}" not in hidden) == private, raw


# Every shape of date text the reader must make sense of, valid or not.
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

# A vocabulary of date words, shuffled into 3,000 texts.
VOCABULARY = [
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


def test_the_reader_survives_every_shape_of_date_text():
    rnd = random.Random(20261011)
    texts = RAW_DATES + [
        " ".join(rnd.choice(VOCABULARY) for _ in range(rnd.randint(1, 7)))
        for _ in range(3000)
    ]
    for text in texts:
        date = parse_date(text)  # must not raise
        assert date is None or date.form, text
        tree = read_gedcom(
            ged("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", f"2 DATE {text}")
        )
        assert tree.people["I1"].birth is not None, text

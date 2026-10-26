"""GEDCOM reading, read_gedcom: records, encodings, escapes, odd input and the tags
that give a child's relationship to each parent.

Synthetic fixtures only.
"""

import codecs
import unicodedata

import pytest

import kincade.cli
from kincade.gedcom import parse_date, read_gedcom
from kincade.lang import display_name
from kincade.model import Date, Day, ParentLink

from conftest import HUGE, KID, ged, kid_tree, render, render_charts, seven
from pdfread import drawn

# ---------------------------------------------------------------- the Tom family example

TOM, MARY, JOHN, BOB = "I1", "I2", "I3", "I4"
# John and Mary (married 1950, Reno), Bob and Mary (married 1940, Dayton)
F1, F2 = "F1", "F2"


def family(
    *extra, fam=F1, husb=JOHN, wife=MARY, year=1950, place="Reno", kid=(TOM, ())
):
    """A FAM record with the child `kid` = (record ID, lines under its CHIL), and any
    extra lines (more children...)."""
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
    with a death date."""

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
    family F2 is in the file, with Tom as a child of it."""
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


# ---------------------------------------------------------------- 5.5.1 and its quirks


def test_a_gedcom_5_5_1_file_with_quirks(quirks):
    # the first BIRT record wins over the second
    assert quirks.people["I1"].birth.date == Date("about", Day(1764))
    # DEAT BET. 1622 - 1632 prints as a range
    text = drawn(render_charts(quirks, "I1", generations=1))
    assert "d. 1622-1632" in text
    # an individual-level MARR is ignored, as are custom tags and SUBM
    assert not [t for t in text if t.startswith("m. 1 Jan 1800")]
    assert len(quirks.people) == 11 and len(quirks.families) == 3
    # PEDI adopted is listed before PEDI birth, but birth mode still prefers F1
    assert [pl.family for pl in quirks.people["I1"].parents] == ["F2", "F1"]
    assert quirks.parent_family("I1", "birth").id == "F1"
    assert quirks.parent_family("I1", "adoptive").id == "F2"
    # DEAT Y with no date still counts as died: the name is drawn under exclude_private
    assert "Emily MILLARD\\MILLERS" in drawn(render(quirks, "I2", exclude_private=True))
    # NPFX and NSFX
    assert display_name(quirks.people["I3"]) == "Major Daniel McNALLY, Jr."
    # /Jr/, /{Capt}/ and /FAIRWOOD/ are read as written, not reformatted as surnames
    assert display_name(quirks.people["I4"]) == "Alan REED Jr"
    assert display_name(quirks.people["I5"]) == "Capt Evan DALE"
    assert display_name(quirks.people["I6"]) == "FAIRWOOD"
    # a NAME value split across CONC lines
    assert display_name(quirks.people["I9"]) == "Ann DELAWARE"
    # a place joined by CONC; the CONT line starts a second line that is not drawn
    assert quirks.people["I10"].birth.place == "First part second part"
    i10_text = drawn(render_charts(quirks, "I10", generations=1))
    assert not [t for t in i10_text if "hidden second line" in t]
    # GIVN and SURN alone
    assert display_name(quirks.people["I11"]) == "Only SUBSTRUCTURE"


# ---------------------------------------------------------------- GEDCOM 7


def test_a_gedcom_7_file():
    # the "@@" rule: an escape only at the start of a value
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME @@Ann /O@@Brien/",
            "1 BIRT",
            "2 PLAC @@home@@here",
        )
    )
    p = tree.people["I1"]
    assert (p.given, p.surname, p.birth.place) == ("@Ann", "O@@Brien", "@home@@here")

    # an empty DATE with a PHRASE that reads as an about-form date
    tree = read_gedcom(
        seven("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", "2 DATE", "3 PHRASE about 1920")
    )
    date = tree.people["I1"].birth.date
    assert date.form == "about" and date.text == "about 1920"

    # a structured payload keeps its structure; the phrase does not replace it
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 BIRT",
            "2 DATE BEF 1850",
            "3 PHRASE AFTER 1900",
        )
    )
    assert tree.people["I1"].birth.date == Date("before", Day(1850))

    # PHRASE-only events still count as records
    tree = read_gedcom(
        seven(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 BIRT",
            "2 DATE",
            "3 PHRASE 5 January (year unknown)",
            "1 CHR",
            "2 DATE 1 JAN 1900",
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
    text = drawn(render_charts(tree, "I1", generations=2, index=False))
    assert "b. 5 January (year unknown)" in text and not any(
        t.startswith("chr.") for t in text
    )
    assert "m. spring" in text

    # an empty DATE with an empty PHRASE is no date
    tree = read_gedcom(
        seven("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", "2 DATE", "3 PHRASE")
    )
    assert tree.people["I1"].birth.date is None

    # a calendar escape this reader cannot convert has no readable year
    assert (
        read_gedcom(
            seven("0 @I1@ INDI", "1 NAME A /B/", "1 BIRT", "2 DATE HEBREW 1 TSH 5650")
        )
        .people["I1"]
        .birth.date.year_unknown
    )

    # record IDs are stored without "@"
    tree = read_gedcom(
        seven(
            "0 @F9@ FAM",
            "1 HUSB @I9@",
            "1 CHIL @I8@",
            "0 @I8@ INDI",
            "1 NAME Kid /Z/",
            "1 FAMC @F9@",
            "0 @I9@ INDI",
            "1 NAME Dad /Z/",
        )
    )
    assert "F9" in tree.families and "@" not in "".join(tree.people) + "".join(
        tree.families
    )
    # a FAM record before its people still links; a one-parent family links too
    assert tree.families["F9"].father == "I9" and tree.families["F9"].children == ["I8"]


# ---------------------------------------------------------------- 5.5.x and ANSEL


def test_a_gedcom_5_5_file_in_ansel():
    raw = (
        "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n1 CHAR ANSEL\n"
        "0 @I1@ INDI\n1 NAME Zo\xe8e /M\xe8uller/\n1 BIRT\n2 PLAC Bra\xf7sov\n"
        "3 CONC , Romania\n"
        "0 @I2@ INDI\n1 NAME An@@n /O@@Brien/\n"
        "0 TRLR\n"
    ).encode("latin-1")
    tree = read_gedcom(raw)
    # combining marks precede the base letter; NFC composes them (ë and ü)
    assert display_name(tree.people["I1"]) == "Zoë MÜLLER"
    # the comma-below mark gives the Romanian letter, and CONC is joined
    assert tree.people["I1"].birth.place == "Brașov, Romania"
    # "@@" is undone everywhere in 5.5.x, unlike GEDCOM 7's start-of-value-only rule
    p2 = tree.people["I2"]
    assert (p2.given, p2.surname) == ("An@n", "O@Brien")


# Every combining mark of ANSEL (ANSI/NISO Z39.47) and the Unicode mark it is.
ANSEL_MARKS = {
    0xE0: "̉",
    0xE1: "̀",
    0xE2: "́",
    0xE3: "̂",
    0xE4: "̃",
    0xE5: "̄",
    0xE6: "̆",
    0xE7: "̇",
    0xE8: "̈",
    0xE9: "̌",
    0xEA: "̊",
    0xEB: "︠",
    0xEC: "︡",
    0xED: "̕",
    0xEE: "̋",
    0xEF: "̐",
    0xF0: "̧",
    0xF1: "̨",
    0xF2: "̣",
    0xF3: "̤",
    0xF4: "̥",
    0xF5: "̳",
    0xF6: "̲",
    0xF7: "̦",
    0xF8: "̜",
    0xF9: "̮",
    0xFA: "︢",
    0xFB: "︣",
    0xFE: "̓",
}


def test_every_ansel_combining_mark():
    for code, mark in ANSEL_MARKS.items():
        raw = ged("0 HEAD", "1 CHAR ANSEL", "0 @I1@ INDI", "1 NAME Xs /Doe/").replace(
            b"Xs", bytes([code]) + b"s"
        )
        given = read_gedcom(raw).people["I1"].given
        assert given == unicodedata.normalize("NFC", "s" + mark), f"{code:02X}"


# ---------------------------------------------------------------- encodings


HEADER = "0 HEAD\n1 CHAR {}\n0 @I1@ INDI\n1 NAME {} /X/\n0 TRLR\n"


def decoded_name(data):
    return display_name(read_gedcom(data).people["I1"])


BASE_TEXT = "0 HEAD\n0 @I1@ INDI\n1 NAME Zoë /Müller/\n0 TRLR\n"
FALLBACK_TEXT = "0 HEAD\n0 @I1@ INDI\n1 NAME Zo\xeb /C\x9cur/\n0 TRLR\n"

ENCODING_CASES = [
    (
        "UTF-8 with BOM and CRLF",
        codecs.BOM_UTF8 + BASE_TEXT.encode("utf-8").replace(b"\n", b"\r\n"),
        "Zoë MÜLLER",
    ),
    (
        "UTF-16 LE with BOM",
        codecs.BOM_UTF16_LE + BASE_TEXT.encode("utf-16-le"),
        "Zoë MÜLLER",
    ),
    (
        "UTF-16 BE without a BOM",
        HEADER.format("UNICODE", "ZoŁë").encode("utf-16-be"),
        "ZoŁë X",
    ),
    (
        "CHAR ANSI is cp1252, even when the bytes are valid UTF-8",
        HEADER.format("ANSI", "JosÃ©").encode("cp1252"),
        "JosÃ© X",
    ),
    ("CHAR IBMPC is cp437", HEADER.format("IBMPC", "José").encode("cp437"), "José X"),
    (
        "undeclared non-UTF-8 bytes fall back to cp1252",
        FALLBACK_TEXT.encode("latin-1"),
        "Zoë CŒUR",
    ),
]


@pytest.mark.parametrize(
    "raw,expected",
    [case[1:] for case in ENCODING_CASES],
    ids=[case[0] for case in ENCODING_CASES],
)
def test_encodings_give_the_same_tree(raw, expected):
    assert decoded_name(raw) == expected


# ---------------------------------------------------------------- malformed input


def test_malformed_input_never_stops_an_import(tmp_path, capsys):
    # a HUGE date, and an open-ended one, are read as text rather than raising
    assert parse_date(HUGE).form == "text"
    assert parse_date(f"BET {HUGE} AND 1900").form == "text"

    # absurd level numbers do not crash the parser
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ok /Person/",
            f"{'9' * 5000} NAME Bad /Line/",
            "99 TAG x",
            "1 SEX M",
        )
    )
    assert display_name(tree.people["I1"]) == "Ok PERSON"

    # a skipped level keeps the sibling events and the lower-level links below it
    person = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "2 NAME Jane /Doe/",
            "2 BIRT",
            "3 DATE 1900",
            "2 DEAT",
            "3 DATE 1980",
            "1 FAMC @F1@",
        )
    ).people["I1"]
    assert display_name(person) == "Jane DOE"
    assert person.birth.date == Date("exact", Day(1900))
    assert person.parents == [ParentLink("F1")]

    # non-whitespace control characters are dropped from names and places
    person = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ja\x05ne /Doe/",
            "1 BIRT",
            "2 PLAC Plain\x05ville",
        )
    ).people["I1"]
    assert display_name(person) == "Jane DOE" and person.birth.place == "Plainville"

    # U+2028 stays inside its value; it must not split the line
    person = read_gedcom(ged("0 @I1@ INDI", "1 NAME Jane Ann /Doe/")).people["I1"]
    assert display_name(person) == "Jane Ann DOE"

    # a CHAR line outside the header is ignored: no declaration means UTF-8
    text = "0 HEAD\n0 @I1@ INDI\n1 NAME José /X/\n1 CHAR IBMPC\n0 TRLR\n"
    assert decoded_name(text.encode("utf-8")) == "José X"

    # the CLI makes a PDF from a file with an oversized date
    path = tmp_path / "big.ged"
    path.write_bytes(
        ged("0 @I1@ INDI", "1 NAME Big /DATE/", "1 BIRT", f"2 DATE {HUGE}")
    )
    out = tmp_path / "big.pdf"
    assert (
        kincade.cli.main(
            [str(path), "--root", "I1", "-o", str(out), "--exclude-private"]
        )
        == 0
    )
    assert out.read_bytes().startswith(b"%PDF")


# ---------------------------------------------------------------- relationship sources


def _check_gramps():
    # _FREL / _MREL under FAMC: one parent each
    assert pair(tom_file(["2 _FREL Natural", "2 _MREL Adopted"])) == (
        "birth",
        "adopted",
    )
    tree = tom_file(["2 _FREL Stepchild", "2 _MREL Birth"])
    assert link(tree) == ParentLink(F1, "step", "birth")


def _check_ftm():
    # _FREL / _MREL under the CHIL line
    assert pair(tom_file(chil1=["2 _FREL Natural", "2 _MREL Step"])) == (
        "birth",
        "step",
    )
    # the lines under a different child's CHIL line belong to that child only
    ann = ["0 @I9@ INDI", "1 NAME Ann /TURNER/", f"1 FAMC @{F1}@"]
    fam = family(
        "1 CHIL @I9@", "2 _FREL Step", "2 _MREL Step", kid=(TOM, ["2 _MREL Adopted"])
    )
    tree = read_gedcom(ged("0 HEAD", *people(tom_famc=[f"1 FAMC @{F1}@"]), *ann, *fam))
    assert pair(tree, child=TOM) == ("birth", "adopted")
    assert pair(tree, child="I9") == ("step", "step")
    # the FAMC-level value beats the CHIL-level one
    tree = tom_file(["2 _FREL Step"], chil1=["2 _FREL Adopted", "2 _MREL Foster"])
    assert pair(tree) == ("step", "foster")


def _check_pedi():
    for pedi, expected in [
        ("step", "step"),
        ("stepchild", "step"),
        ("  StepChild  ", "step"),
        ("birth", "birth"),
        ("adopted", "adopted"),
        ("foster", "foster"),
        ("sealing", "other"),
    ]:
        assert link(tom_file([f"2 PEDI {pedi}"])) == ParentLink(
            F1, expected, expected
        ), pedi
    for pedi in ("", "unknown"):
        assert link(tom_file([f"2 PEDI {pedi}"])) == ParentLink(F1, "birth", "birth"), (
            pedi
        )


def _check_adoption_event():
    for which, expected in [
        ("HUSB", ("adopted", "birth")),
        ("WIFE", ("birth", "adopted")),
        ("BOTH", ("adopted", "adopted")),
    ]:
        tree = tom_file(tom_lines=["1 ADOP", f"2 FAMC @{F1}@", f"3 ADOP {which}"])
        assert pair(tree) == expected, which
    # an event naming no family changes nothing
    tree = tom_file(tom_lines=["1 ADOP", "2 DATE 1950"])
    assert pair(tree) == ("birth", "birth")
    # an event for a family the person has no FAMC for changes nothing
    tree = tom_file(
        bob=True, tom_lines=["1 ADOP", f"2 FAMC @{F2}@", "3 ADOP BOTH"], kid_in_f2=False
    )
    assert tree.people[TOM].parents == [ParentLink(F1)]
    # precedence: _FREL/_MREL, then PEDI, then the adoption event, then birth
    assert pair(tom_file(["2 PEDI adopted", "2 _FREL Birth"])) == ("birth", "adopted")
    both = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP BOTH"]
    assert pair(tom_file(["2 PEDI birth"], tom_lines=both)) == ("birth", "birth")
    husb = ["1 ADOP", f"2 FAMC @{F1}@", "3 ADOP HUSB"]
    assert pair(tom_file(tom_lines=husb)) == ("adopted", "birth")
    assert pair(tom_file()) == ("birth", "birth")
    # CSTA, inline or as a pointer, is ignored
    for inline in (False, True):
        tree = kid_tree([("F1", "")], status={"F1": "Adopted"}, inline=inline)
        assert pair(tree, "F1", KID) == ("birth", "birth")


RELATIONSHIP_SOURCES = {
    "gramps": _check_gramps,
    "ftm": _check_ftm,
    "pedi": _check_pedi,
    "adoption event": _check_adoption_event,
}


@pytest.mark.parametrize("style", RELATIONSHIP_SOURCES)
def test_relationship_sources(style):
    RELATIONSHIP_SOURCES[style]()

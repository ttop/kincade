"""Reading GEDCOM files: encodings, line endings, escapes, record IDs and odd input."""

import unicodedata

import pytest

import kincade
import kincade.cli
import kincade.gedcom
import kincade.pdf
from kincade.gedcom import parse_date, read_gedcom
from kincade.lang import display_name
from kincade.model import Date, Day, ParentLink

from conftest import FIX, HUGE, ged, short


def snapshot(tree):
    return {
        pid: (display_name(p), p.birth and p.birth.date, p.birth and p.birth.place)
        for pid, p in tree.people.items()
    }


@pytest.mark.parametrize(
    "name,transform",
    [
        ("LF", lambda b: b),
        ("CRLF", lambda b: b.replace(b"\n", b"\r\n")),
        ("CR", lambda b: b.replace(b"\n", b"\r")),
        ("UTF-8 BOM", lambda b: b"\xef\xbb\xbf" + b),
        ("blank lines and indentation", lambda b: b.replace(b"\n0 ", b"\n\n  0 ")),
        ("no trailing newline", lambda b: b.rstrip(b"\n")),
        ("UTF-16 BOM", lambda b: b.decode("utf-8").encode("utf-16")),
    ],
)
def test_line_endings_and_encodings_give_the_same_tree(name, transform):
    raw = (FIX / "quirks.ged").read_bytes()
    assert snapshot(read_gedcom(transform(raw))) == snapshot(read_gedcom(raw)), name


@pytest.mark.parametrize(
    "name,place",
    [
        ("Zo\u00eb /M\u00fcller/", "K\u00f6ln"),  # composed: one character per letter
        ("Zoe\u0308 /Mu\u0308ller/", "Ko\u0308ln"),  # decomposed, as macOS may write it
    ],
    ids=["composed", "decomposed"],
)
def test_accents_in_either_unicode_form_are_read_as_composed_text(name, place):
    tree = read_gedcom(
        ged("0 @I1@ INDI", f"1 NAME {name}", "1 BIRT", f"2 PLAC {place}")
    )
    person = tree.people["I1"]
    assert (person.given, person.surname, person.birth.place) == (
        "Zo\u00eb",
        "M\u00fcller",
        "K\u00f6ln",
    )


def test_ansi_header_means_cp1252():
    raw = (
        (FIX / "quirks.ged")
        .read_text(encoding="utf-8")
        .replace("CHAR UTF-8", "CHAR ANSI")
    )
    tree = read_gedcom(raw.encode("cp1252", errors="replace"))
    assert display_name(tree.people["I10"]) == "Zoë MÜLLER"


def test_ansel_diacritics_precede_the_base_letter():
    raw = b"0 HEAD\n1 CHAR ANSEL\n0 @I1@ INDI\n1 NAME Zo\xe8e /M\xe8uller/\n0 TRLR\n"
    assert display_name(read_gedcom(raw).people["I1"]) == "Zoë MÜLLER"


# Every combining mark of ANSEL (ANSI/NISO Z39.47) and the Unicode mark it is
ANSEL_MARKS = {
    0xE0: "\u0309",  # hook above
    0xE1: "\u0300",  # grave
    0xE2: "\u0301",  # acute
    0xE3: "\u0302",  # circumflex
    0xE4: "\u0303",  # tilde
    0xE5: "\u0304",  # macron
    0xE6: "\u0306",  # breve
    0xE7: "\u0307",  # dot above
    0xE8: "\u0308",  # umlaut
    0xE9: "\u030c",  # caron
    0xEA: "\u030a",  # ring above
    0xEB: "\ufe20",  # ligature, left half
    0xEC: "\ufe21",  # ligature, right half
    0xED: "\u0315",  # comma above right
    0xEE: "\u030b",  # double acute
    0xEF: "\u0310",  # candrabindu
    0xF0: "\u0327",  # cedilla
    0xF1: "\u0328",  # ogonek
    0xF2: "\u0323",  # dot below
    0xF3: "\u0324",  # double dot below
    0xF4: "\u0325",  # ring below
    0xF5: "\u0333",  # double underline
    0xF6: "\u0332",  # underline
    0xF7: "\u0326",  # comma below (Romanian s and t, Latvian k, l and n)
    0xF8: "\u031c",  # left half ring below
    0xF9: "\u032e",  # breve below
    0xFA: "\ufe22",  # double tilde, left half
    0xFB: "\ufe23",  # double tilde, right half
    0xFE: "\u0313",  # comma above
}


@pytest.mark.parametrize(
    "code,mark", ANSEL_MARKS.items(), ids=[f"{code:02X}" for code in ANSEL_MARKS]
)
def test_every_ansel_combining_mark_goes_on_the_letter_after_it(code, mark):
    raw = ged("0 HEAD", "1 CHAR ANSEL", "0 @I1@ INDI", "1 NAME Xs /Doe/")
    raw = raw.replace(b"Xs", bytes([code]) + b"s")
    assert read_gedcom(raw).people["I1"].given == unicodedata.normalize(
        "NFC", "s" + mark
    )


def test_an_ansel_comma_below_gives_the_romanian_letter():
    raw = ged("0 HEAD", "1 CHAR ANSEL", "0 @I1@ INDI", "1 NAME Brasov /Doe/")
    tree = read_gedcom(raw.replace(b"Brasov", b"Bra\xf7sov"))
    assert tree.people["I1"].given == "Bra\u0219ov"


def test_conc_and_cont(quirks):
    assert quirks.people["I9"].given == "Ann"
    # CONC glued onto the NAME value
    assert display_name(quirks.people["I9"]) == "Ann DELAWARE"
    # CONC appends, CONT starts a new line; only the first line of a place is used
    assert quirks.people["I10"].birth.place == "First part second part"


def test_u2028_stays_inside_its_value_and_control_characters_are_dropped(quirks):
    # U+2028 inside a value must not split the line (str.splitlines would);
    # \x05 is dropped
    assert quirks.people["I1"].death.place == "Oakvale County, Virginia"
    assert quirks.people["I1"].parents  # the lines after the U+2028 value are read
    assert quirks.people["I9"].birth.place == "Plainville"
    assert kincade.pdf.clean("Oakvale County\tVa") == "Oakvale County Va"


@pytest.mark.parametrize("control", ["\x00", "\x05", "\x7f", "\x81", "\x9f"])
def test_non_whitespace_controls_are_removed_from_names_and_places(control):
    person = read_gedcom(
        ged(
            "0 @I1@ INDI",
            f"1 NAME Ja{control}ne /Doe/",
            "1 BIRT",
            f"2 PLAC Plain{control}ville",
        )
    ).people["I1"]
    assert display_name(person) == "Jane DOE"
    assert person.birth is not None and person.birth.place == "Plainville"


@pytest.mark.parametrize("space", ["\t", "\v", "\f", "\u0085", "\u00a0", "\u2028"])
def test_whitespace_inside_a_value_separates_name_words(space):
    person = read_gedcom(ged("0 @I1@ INDI", f"1 NAME Jane{space}Ann /Doe/")).people[
        "I1"
    ]
    assert display_name(person) == "Jane Ann DOE"


def test_skipped_levels_keep_sibling_events_and_lower_level_links():
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
    assert person.birth is not None and person.birth.date == Date("exact", Day(1900))
    assert person.death is not None and person.death.date == Date("exact", Day(1980))
    assert person.parents == [ParentLink("F1")]


def test_continuations_after_a_skipped_level_keep_the_next_sibling():
    person = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "2 NAME Ja",
            "3 CONC ne /Doe/",
            "2 BIRT",
            "4 DATE 1900",
            "3 PLAC First",
            "4 CONC ville",
            "4 CONT Second line",
            "2 DEAT Y",
        )
    ).people["I1"]
    assert display_name(person) == "Jane DOE"
    assert person.birth is not None and person.birth.date == Date("exact", Day(1900))
    assert person.birth.place == "Firstville"
    assert person.death is not None


def test_first_event_wins_and_individual_marr_is_ignored(quirks):
    p = quirks.people["I1"]
    assert p.birth.date == Date("about", Day(1764))
    assert quirks.families["F1"].marriage.date == Date("exact", Day(1790, 7, 4))


def test_unknown_tags_and_records_are_skipped(quirks):
    assert len(quirks.people) == 11 and len(quirks.families) == 3


def test_parent_family_prefers_birth_pedi(quirks):
    p = quirks.people["I1"]
    assert [link.family for link in p.parents] == ["F2", "F1"]  # adopted listed first
    assert quirks.parent_family("I1").id == "F1"
    assert quirks.parent_ids("I1") == ("I1", None)  # F1 has a husband only


def test_family_with_a_single_parent(quirks):
    fam = quirks.families["F2"]
    assert (fam.father, fam.mother) == ("", "I2")


# ---------------------------------------------------------------- encodings


HEADER = "0 HEAD\n1 CHAR {}\n0 @I1@ INDI\n1 NAME {} /X/\n0 TRLR\n"


def decoded_name(data):
    return display_name(read_gedcom(data).people["I1"])


def test_bytes_that_are_not_utf8_are_read_as_cp1252():
    # UTF-8 is tried first, with no CHAR line or with CHAR UTF-8; \xeb and \x9c are not
    # UTF-8 on their own, and \x9c is cp1252's oe ligature
    name = "Zo\xeb /C\x9cur/"
    assert (
        decoded_name(f"0 HEAD\n0 @I1@ INDI\n1 NAME {name}\n0 TRLR\n".encode("latin-1"))
        == "Zoë CŒUR"
    )
    assert decoded_name(HEADER.format("UTF-8", "Zo\xeb").encode("latin-1")) == "Zoë X"


def test_declared_ansi_is_cp1252_even_when_the_bytes_are_also_valid_utf8():
    # bytes C3 A9: valid UTF-8 for 'é'
    data = HEADER.format("ANSI", "JosÃ©").encode("cp1252")
    assert decoded_name(data) == "JosÃ© X"
    assert decoded_name(HEADER.format("UTF-8", "José").encode("utf-8")) == "José X"


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
def test_utf16_without_a_bom(codec):
    # U+0141 has a non-zero high byte
    data = HEADER.format("UNICODE", "Zo\u0141\u00eb").encode(codec)
    assert not data.startswith((b"\xff\xfe", b"\xfe\xff"))
    assert decoded_name(data) == "Zo\u0141\u00eb X"


def test_char_is_found_anywhere_in_the_header_record():
    filler = "".join(f"1 NOTE {'x' * 70}\n" for _ in range(200))  # ~15 kB of header
    text = f"0 HEAD\n{filler}1 CHAR ANSI\n0 @I1@ INDI\n1 NAME JosÃ© /X/\n0 TRLR\n"
    assert decoded_name(text.encode("cp1252")) == "JosÃ© X"


def test_a_char_line_outside_the_header_is_ignored():
    text = "0 HEAD\n0 @I1@ INDI\n1 NAME Jos\u00e9 /X/\n1 CHAR IBMPC\n0 TRLR\n"
    # no declaration in the header: UTF-8
    assert decoded_name(text.encode("utf-8")) == "Jos\u00e9 X"


def test_declared_ibmpc_is_cp437():
    assert decoded_name(HEADER.format("IBMPC", "José").encode("cp437")) == "José X"


# ---------------------------------------------------------------- GEDCOM escapes


def test_at_sign_escapes_in_5_5_files():
    tree = read_gedcom(
        b"0 HEAD\n1 GEDC\n2 VERS 5.5.1\n0 @I1@ INDI\n1 NAME An@@n /O@@Brien/\n1 BIRT\n"
        b"2 PLAC at@@home\n1 FAMC @F1@\n0 @F1@ FAM\n1 HUSB @I1@\n0 TRLR\n"
    )
    p = tree.people["I1"]
    assert (p.given, p.surname, p.birth.place) == ("An@n", "O@Brien", "at@home")
    # pointers untouched
    assert (
        p.parents == [ParentLink("F1", "birth")] and tree.families["F1"].father == "I1"
    )


def test_at_sign_escapes_in_gedcom_7_only_at_the_start_of_a_value():
    tree = read_gedcom(
        b"0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME @@Ann /O@@Brien/\n1 BIRT\n"
        b"2 PLAC @@home@@here\n1 FAMC @F1@\n0 @F1@ FAM\n1 HUSB @I1@\n0 TRLR\n"
    )
    p = tree.people["I1"]
    assert (p.given, p.surname, p.birth.place) == ("@Ann", "O@@Brien", "@home@@here")
    assert p.parents == [ParentLink("F1", "birth")]


def test_absurd_level_numbers_do_not_crash_the_parser():
    data = ged(
        "0 @I1@ INDI",
        "1 NAME Ok /Person/",
        f"{'9' * 5000} NAME Bad /Line/",
        "99 TAG x",
        "1 SEX M",
    )
    tree = read_gedcom(data)
    assert (
        display_name(tree.people["I1"]) == "Ok PERSON"
        and tree.people["I1"].birth is None
    )


# ---- GEDCOM 7 escapes on continuation lines ----------------------------------------


def test_gedcom_7_escapes_are_undone_on_every_physical_line():
    records = kincade.gedcom._parse_records(
        "0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NOTE first\n2 CONT @@second\n2 CONC @@third\n"
        "2 CONT mid@@dle\n0 TRLR"
    )
    (note,) = records[1].children
    assert note.value == "first\n@second@third\nmid@@dle"
    old = kincade.gedcom._parse_records(
        "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n0 @I1@ INDI\n1 NOTE a@@b\n2 CONT @@c\n0 TRLR"
    )
    assert old[1].children[0].value == "a@b\n@c"


@pytest.mark.parametrize(
    "raw",
    [
        HUGE,
        "1" * 4301,
        f"BET {HUGE} AND 1900",
        f"BET 1900 AND {HUGE}",
        f"FROM {HUGE} TO {HUGE}",
        f"INT {HUGE} (x)",
        f"ABT {HUGE}",
        f"JAN {HUGE}",
        f"5 JAN {HUGE}",
        f"{HUGE}/32",
        f"1731/{HUGE}",
        f"@#DJULIAN@ {HUGE}",
        f"({HUGE})",
        f"AFT {HUGE}",
        f"TO {HUGE}",
        f"{HUGE} BC",
        "0" * 5000,
        "0" * 5000 + "99",
    ],
    ids=short,
)
def test_one_oversized_number_in_a_date_never_stops_the_import(raw):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Big /DATE/",
            "1 BIRT",
            f"2 DATE {raw}",
            "2 PLAC Somewhere",
            "0 @I2@ INDI",
            "1 NAME Next /ONE/",
        )
    )
    assert (
        set(tree.people) == {"I1", "I2"}
        and tree.people["I1"].birth.place == "Somewhere"
    )
    assert parse_date(raw) is not None


def test_the_command_line_makes_a_pdf_from_a_file_with_an_oversized_date(
    tmp_path, capsys
):
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
    assert kincade.cli.main([str(path), "--find", "big"]) == 0
    assert "I1\tBig DATE\t" in capsys.readouterr().out


# ----------------------------------------------------------------
# record IDs without the @ delimiters


def test_the_reader_stores_record_ids_without_the_at_signs(pedigree):
    assert "I1" in pedigree.people and "F1" in pedigree.families
    assert not any("@" in key for key in [*pedigree.people, *pedigree.families])
    for pid, person in pedigree.people.items():
        assert person.id == pid
        assert all(link.family in pedigree.families for link in person.parents), pid
        assert all(fid in pedigree.families for fid in person.families), pid
    for fid, family in pedigree.families.items():
        assert family.id == fid
        assert all(
            ref in pedigree.people
            for ref in (family.father, family.mother, *family.children)
            if ref
        ), fid
    assert pedigree.people["I1"].parents[0].family == "F1" and pedigree.people[
        "I1"
    ].families == ["F101"]


def test_ids_of_a_gedcom_file_keep_the_links_between_the_records():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME A /B/",
            "1 FAMC @F1@",
            "2 _FREL Step",
            "1 FAMS @F9@",
            "0 @I2@ INDI",
            "1 NAME C /D/",
            "1 ADOP",
            "2 FAMC @F1@",
            "3 ADOP HUSB",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 CHIL @I1@",
            "2 _MREL Step",
            "0 @F9@ FAM",
            "1 WIFE @I1@",
        )
    )
    # the _FREL, and the _MREL on the CHIL line
    assert tree.people["I1"].parents == [ParentLink("F1", "step", "step")]
    assert tree.families["F1"].father == "I2" and tree.families["F1"].children == ["I1"]
    assert tree.families["F9"].mother == "I1"

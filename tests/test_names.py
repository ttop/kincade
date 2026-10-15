"""Names as drawn: display names, affixes, titles and placeholder surnames."""

import pytest

import kincade.lang
import kincade.model
from kincade.gedcom import read_gedcom
from kincade.lang import display_name

from conftest import ged, render
from pdfread import drawn

# ---------------------------------------------------------------- names


@pytest.mark.parametrize(
    "xref,expected",
    [
        ("I1", 'Robert "Bob" WILKS'),  # nickname quotes kept
        ("I2", "Emily MILLARD\\MILLERS"),  # literal backslash kept
        ("I3", "Major Daniel McNALLY, Jr."),  # Mc keeps its case; prefix; comma suffix
        ("I4", "Alan REED Jr"),  # FTW /Jr/ is a suffix, not a surname
        ("I5", "Capt Evan DALE"),  # FTW /{Capt}/ is a title
        ("I6", "FAIRWOOD"),  # no given name
        ("I7", "Velma"),  # empty surname //
        ("I8", "Jean"),  # no slashes at all
        ("I10", "Zoë MÜLLER"),
        ("I11", "Only SUBSTRUCTURE"),  # NAME value empty: fall back to GIVN/SURN
    ],
)
def test_display_names(quirks, xref, expected):
    assert display_name(quirks.people[xref]) == expected


@pytest.mark.parametrize(
    "name", ["Zo\u00eb /M\u00fcller/", "Zoe\u0308 /Mu\u0308ller/"], ids=["NFC", "NFD"]
)
def test_an_accent_in_either_unicode_form_is_drawn_in_the_base14_fonts(name):
    tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME {name}"))
    assert "Zo\u00eb M\u00dcLLER" in drawn(render(tree))


def test_mc_surname_case_and_empty_person():
    assert kincade.lang.fmt_surname("McClure") == "McCLURE"
    assert kincade.lang.fmt_surname("McCLURE") == "McCLURE"
    assert kincade.lang.fmt_surname("Van Riper") == "VAN RIPER"
    assert display_name(kincade.model.Person("I0")) == ""


# ---------------------------------------------------------------- prefixes and suffixes


def test_affixes_already_in_the_name_value_are_not_repeated():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Dr. Alice /Jones/ Jr.",
            "2 NPFX Dr.",
            "2 NSFX Jr.",
            "0 @I2@ INDI",
            "1 NAME Alice /Jones/",
            "2 NPFX Dr.",
            "2 NSFX , Jr.",
            "0 @I3@ INDI",
            "1 NAME Dr Alice /Jones/",
            "2 NPFX Dr.",
            "0 @I4@ INDI",
            "1 NAME Daniel /McNALLY/",
            "2 NPFX Major",
            "0 @I5@ INDI",
            "1 NAME Timothy /BLAKE/",
            "2 NPFX Captain",
        )
    )
    assert display_name(tree.people["I1"]) == "Dr. Alice JONES Jr."
    # not in the payload: added
    assert display_name(tree.people["I2"]) == "Dr. Alice JONES, Jr."
    assert display_name(tree.people["I3"]) == "Dr. Alice JONES"
    # NPFX goes before the given name
    assert display_name(tree.people["I4"]) == "Major Daniel McNALLY"
    assert display_name(tree.people["I5"]) == "Captain Timothy BLAKE"
    assert tree.people["I1"].given == "Alice" and tree.people["I1"].prefix == "Dr."


# ----------------------------------------------------------------
# titles, suffixes and placeholder surnames


def test_title_and_suffix_dedup_compare_whole_tokens_only():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Nasir /Jones/",
            "2 NPFX Sir",
            "0 @I2@ INDI",
            "1 NAME Sir Arthur /Clarke/",
            "2 NPFX Sir",
            "0 @I3@ INDI",
            "1 NAME Sirius /Black/",
            "2 NPFX Sir.",
            "0 @I4@ INDI",
            "1 NAME Tom /Smith/ Junior",
            "2 NSFX Jr",
            "0 @I5@ INDI",
            "1 NAME Tom /Smith/ III Jr.",
            "2 NSFX Jr.",
            "0 @I6@ INDI",
            "1 NAME Tom /Smith/ Jr.",
            "2 NSFX , Jr.",
            "0 @I7@ INDI",
            "1 NAME Lord Sir Bob /Roy/",
            "2 NPFX Lord Sir",
        )
    )
    names = {pid: display_name(p) for pid, p in tree.people.items()}
    assert names["I1"] == "Sir Nasir JONES"
    assert names["I2"] == "Sir Arthur CLARKE"
    assert names["I3"] == "Sir. Sirius BLACK"
    assert names["I4"] == "Tom SMITH Junior Jr"  # different tokens: both kept
    assert names["I5"] == "Tom SMITH III Jr."
    assert names["I6"] == "Tom SMITH Jr."
    assert names["I7"] == "Lord Sir Bob ROY"


@pytest.mark.parametrize(
    "surname",
    [
        "(UNKNOWN)",
        "UNKNOWN",
        "Unknown",
        "unknown",
        "[Unknown]",
        "?",
        "???",
        "___",
        "UNK",
        "(unk)",
        "NN",
        "N.N.",
        "n.n",
        "(?)",
        "-",
        "",
    ],
)
def test_placeholder_surnames_are_recognized(surname):
    assert kincade.lang.is_placeholder_surname(surname)


@pytest.mark.parametrize(
    "surname", ["Unknowns", "KNOWN", "NUNN", "Nunez", "Unkel", "O'NN", "Smith"]
)
def test_real_surnames_are_not_placeholders(surname):
    assert not kincade.lang.is_placeholder_surname(surname)

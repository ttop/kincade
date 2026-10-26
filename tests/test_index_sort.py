"""Index sort order: the [sort] table of a language (expand, after_z, ignore_particles,
surname_start), and the keep_case_prefixes of printed surnames.

Synthetic names only. The index is built by build_index, so each order checked here is
the order the PDF prints.
"""

import re
import unicodedata

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.gedcom import read_gedcom

from conftest import FIX


def write_lang(tmp_path, body, name="sort.toml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def index_entries(people, strings=None):
    """The index lines for people given as (given, surname) pairs, all on one chart (at
    most 15), each with no dates unless a test builds its own tree. The entries come
    back in the order build_index sorts them.
    """
    lines = []
    for i, (given, surname) in enumerate(people, 1):
        lines += [f"0 @I{i}@ INDI", f"1 NAME {given} /{surname}/"]
    tree = read_gedcom("\n".join(lines + ["0 TRLR"]).encode("utf-8"))
    slots = dict.fromkeys(range(1, 16))
    slots.update({i: f"I{i}" for i in range(1, len(people) + 1)})
    return kincade.pdf.build_index(
        tree,
        [kincade.charts.Chart(1, slots)],
        lambda pid: False,
        exclude_private=False,
        strings=strings or kincade.lang.DEFAULT_STRINGS,
    )


def heads(people, strings=None):
    """'SURNAME, Given' for each entry, in index order: without years or references
    (1-2 in English, 1/2 in German)."""
    return [
        re.sub(r"(, \d+[-/]\d+)+$", "", e.split(" (")[0])
        for e in index_entries(people, strings)
    ]


def givens(people, strings=None):
    return [h.split(", ", 1)[1] for h in heads(people, strings)]


def de():
    return kincade.lang.load_strings("de")


# ---------------------------------------------------------------- the English order


ENGLISH_INDEX = {
    "pedigree": [
        "ASHFORD, Abel (b. 1770), 6-2",
        "ASHFORD, Edmund (b. 1860 – d. 1930), 2-2",
        "ASHFORD, Hugh (b. 1800), 2-8, 6-1",
        "ASHFORD, Ivor (b. 1830 – d. 1900), 2-4",
        "ASHFORD, Jane (b. 1980), 1-1",
        "ASHFORD, John (b. 1950 – d. 2020), 1-2",
        "ASHFORD, Robert (b. 1920 – d. 1990), 1-4",
        "ASHFORD, Thomas (b. 1890 – d. 1960), 1-8, 2-1",
        "BOND, Ann (b. 1927 – d. 2003), 1-7",
        "BOND, Isaac (b. 1902), 1-14, 5-1",
        "BROWN, Alice (b. 1925 – d. 2001), 1-5",
        "BROWN, Ira (b. 1895), 1-10",
        "BRUCE, Jane (b. 1901), 1-13",
        "CROSS, Ruth (b. 1775), 6-3",
        "FOX, Eliza, 4-3",
        "GREEN, Martha (b. 1899), 1-11",
        "JONES, Josiah (b. 1860), 3-2",
        "JONES, Sarah (b. 1892), 1-9, 3-1",
        "LEE, Dora (b. 1805), 2-9",
        "McCLURE, Mary (b. 1952), 1-3",
        "McCLURE, Samuel (b. 1900 – d. 1970), 1-12, 4-1",
        "McCLURE, William (b. 1925 – d. 1999), 1-6",
        "NORTH, Olga (b. 1878), 5-3",
        "NORTH, Peter (b. 1875), 5-2",
        "PRICE, Gwen (b. 1835), 2-5",
        "SMITH, Hetty (b. 1905 – d. 1980), 1-15",
        "WILKS, Mary (b. 1865 – d. 1940), 2-3",
    ],
    "collapse": [
        "DALE, Cora (b. 1990), 1-1",
        "DALE, Ed (b. 1960), 1-2",
        "DALE, Fay (b. 1962), 1-3",
        "DALE, Lou (b. 1930 – d. 2000), 1-4, 1-6",
        "DALE, Old (b. 1900 – d. 1970), 1-8, 1-12, 2-1",
        "DALE, Ward (b. 1870), 2-2",
        "FORD, Ida (b. 1875), 2-3",
        "PARK, Nan (b. 1936), 1-7",
        "ROY, Meg (b. 1935), 1-5",
        "STONE, Eve (b. 1905 – d. 1975), 1-9, 1-13, 3-1",
        "STONE, Jack (b. 1880), 3-2",
    ],
    "quirks": [
        'WILKS, Robert "Bob" (b. 1764 – d. 1622), 1-1, 1-2, 1-4, 1-8',
    ],
    "cycle": [
        "LOOP, Adam (b. 1900), 1-1, 1-4, 2-2, 2-8",
        "LOOP, Bob (b. 1870), 1-2, 1-8, 2-1, 2-4",
    ],
    "deep_collapse": [
        "DEEP, Father, 1-2, 2-4",
        "DEEP, Grand, 1-6",
        "DEEP, Great, 1-12, 2-1",
        "DEEP, Mother, 1-3",
        "DEEP, Root (b. 1950), 1-1",
        "DEEP, Young (b. 1990), 2-2",
    ],
}


@pytest.mark.parametrize("name", sorted(ENGLISH_INDEX))
def test_english_index_order_of_the_fixtures(name):
    tree = read_gedcom(FIX / f"{name}.ged")
    charts = kincade.charts.plan_charts(tree, "I1")
    assert (
        kincade.pdf.build_index(tree, charts, lambda pid: False, exclude_private=False)
        == ENGLISH_INDEX[name]
    )


def test_english_defaults_are_the_empty_sort_rules():
    assert kincade.lang.DEFAULT_STRINGS["sort"] == {
        "expand": {},
        "after_z": [],
        "ignore_particles": [],
        "surname_start": {},
        "keep_case_prefixes": ["Mc"],
    }


def reference_fold(s):
    """A reference fold: casefold, NFKD, then drop the combining marks."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", s.casefold())
        if not unicodedata.combining(ch)
    )


def test_english_fold_folds_letters_and_digits_like_the_reference_fold_and_drops_every_other_character():
    # punctuation, symbols and spaces are not part of the sort key (see
    # test_punctuation_*): only letters and digits fold as the reference fold folds
    # them, and every other BMP character sorts as nothing. Letters are judged after
    # casefold and NFC, as the sort judges them (U+0345 casefolds to a Greek iota, so it
    # is a letter for the sort).
    rules = kincade.lang.SortRules(kincade.lang.DEFAULT_STRINGS["sort"])
    for cp in range(0x20, 0x10000):
        if 0xD800 <= cp < 0xE000:
            continue
        ch = chr(cp)
        kept = "".join(
            c for c in unicodedata.normalize("NFC", ch.casefold()) if c.isalnum()
        )
        expected = reference_fold(kept)
        assert rules.fold(ch) == expected, f"U+{cp:04X}"
        assert rules.fold(ch, surname=True) == expected, f"U+{cp:04X} (surname)"


# ----------------------------------------------------------------
# punctuation is not part of the sort key


def test_punctuation_is_dropped_from_the_sort_key_but_not_from_the_text():
    rules = kincade.lang.SortRules(kincade.lang.DEFAULT_STRINGS["sort"])
    assert rules.fold("O'Brien", surname=True) == "obrien"
    assert rules.fold("St. John", surname=True) == "st john"
    assert rules.fold("[HARTLEY] DAWSON", surname=True) == "hartley dawson"
    # a hyphen or dash parts words, so a name files word by word
    assert rules.fold("Jean-Paul") == "jean paul"
    assert rules.fold("Saint\u2013Exupéry", surname=True) == "saint exupery"
    assert rules.fold("  St.   John  ") == "st john"  # spaces collapse and are trimmed
    people = [("Pat", "O'Brien"), ("Lee", "St. John")]
    assert [e.split(", 1-")[0] for e in index_entries(people)] == [
        "O'BRIEN, Pat",
        "ST. JOHN, Lee",
    ]


def test_a_bracketed_surname_sorts_under_its_letters():
    people = [("Anna", "HALL"), ("Ben", "[HARTLEY] DAWSON"), ("Cy", "HUNT")]
    assert heads(people) == ["HALL, Anna", "[HARTLEY] DAWSON, Ben", "HUNT, Cy"]
    assert heads(people, de()) == ["HALL, Anna", "[HARTLEY] DAWSON, Ben", "HUNT, Cy"]


def test_an_apostrophe_or_a_period_does_not_move_a_name():
    people = [
        ("Ann", "O'Brien"),
        ("Bo", "Obrien"),
        ("Cy", "Oakes"),
        ("Dan", "St. John"),
        ("Eve", "Stjohn"),
        ("Fay", "Strong"),
    ]
    # ties on the key: given name decides
    assert heads(people) == [
        "OAKES, Cy",
        "O'BRIEN, Ann",
        "OBRIEN, Bo",
        "ST. JOHN, Dan",
        "STJOHN, Eve",
        "STRONG, Fay",
    ]


def test_placeholder_surnames_with_punctuation_sort_last():
    people = [("Mary", "[?]"), ("Zed", "ZULU"), ("Bob", "(UNKNOWN)"), ("Ann", "Abel")]
    # the last group: by given name
    assert heads(people) == ["ABEL, Ann", "ZULU, Zed", "(UNKNOWN), Bob", "[?], Mary"]


def test_punctuation_does_not_break_expand_or_after_z(tmp_path):
    spanish = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort.expand]\n"ñ" = "n~"\n')
    )
    rules = kincade.lang.SortRules(spanish["sort"])
    # the apostrophe goes first; the "~" of the expansion stays
    assert rules.fold("Ñ'andú") == "n~andu"
    swedish = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nafter_z = ["å"]\n', name="sv.toml")
    )
    rules = kincade.lang.SortRules(swedish["sort"])
    assert rules.fold("Å. berg") > rules.fold("Zorn")


@pytest.mark.parametrize(
    "text", ["Mu\u0308ller", "A\u030aberg", "Straße", "Ne\u0301ve", "\u212bngström"]
)
def test_english_fold_equals_the_reference_fold_for_combining_sequences(text):
    assert kincade.lang.SortRules(kincade.lang.DEFAULT_STRINGS["sort"]).fold(
        text
    ) == reference_fold(text)


def test_english_umlauts_fold_to_their_base_letters():
    people = [
        ("Ulrich", "Müller"),
        ("Anna", "Mueller"),
        ("Carl", "Muller"),
        ("Dora", "Mutz"),
    ]
    assert heads(people) == [
        "MUELLER, Anna",
        "MULLER, Carl",
        "MÜLLER, Ulrich",
        "MUTZ, Dora",
    ]


def test_a_strings_dict_without_a_sort_table_builds_the_english_index():
    people = [("Ulrich", "Müller"), ("Anna", "Mueller"), ("Carl", "Muller")]
    entries = index_entries(people, {"index": kincade.lang.DEFAULT_STRINGS["index"]})
    assert [e.split(", 1-")[0] for e in entries] == [
        "MUELLER, Anna",
        "MULLER, Carl",
        "MÜLLER, Ulrich",
    ]


# ----------------------------------------------------------------
# the fold: order of operations


def test_the_fold_applies_each_setting_to_the_part_it_belongs_to():
    rules = kincade.lang.SortRules(de()["sort"])
    assert rules.fold("Müller") == "mueller"  # expand runs before accent folding
    assert rules.fold("Straße") == "strasse"  # sharp s casefolds to ss
    # particles only in a surname
    assert rules.fold("von der Heide", surname=True) == "heide"
    # ...and never in a given name
    assert rules.fold("von der Heide") == "von der heide"
    assert rules.fold("Van", surname=True) == "van"  # the only word is never stripped
    assert rules.fold("Ñandú") == "nandu"  # no spanish rule: the ñ folds to n


def test_the_fold_of_a_spanish_enye_is_n_tilde():
    spanish = kincade.lang.SortRules(
        {
            "expand": {"ñ": "n~"},
            "after_z": [],
            "ignore_particles": [],
        }
    )
    assert spanish.fold("Ñandú") == "n~andu"


def test_a_decomposed_umlaut_from_a_mac_sorts_as_the_precomposed_one():
    rules = kincade.lang.SortRules(de()["sort"])
    assert rules.fold("Mu\u0308ller") == rules.fold("Müller") == "mueller"


# ----------------------------------------------------------------
# German (DIN 5007-2 Namensliste)


def test_german_umlauts_sort_as_their_vowel_plus_e():
    people = [
        ("Ulrich", "Müller"),
        ("Anna", "Mueller"),
        ("Carl", "Muller"),
        ("Dora", "Mutz"),
    ]
    assert heads(people, de()) == [
        "MUELLER, Anna",
        "MÜLLER, Ulrich",
        "MULLER, Carl",
        "MUTZ, Dora",
    ]


def test_a_decomposed_umlaut_in_a_gedcom_name_sorts_with_its_precomposed_twin():
    people = [("Ulrich", "Mu\u0308ller"), ("Anna", "Mueller"), ("Carl", "Muller")]
    assert givens(people, de()) == ["Anna", "Ulrich", "Carl"]


def test_sharp_s_is_ss_in_german_and_in_english_and_stays_in_capitals():
    people = [("Anna", "Weiß"), ("Ben", "Weiss"), ("Carl", "Weis"), ("Dora", "Weisz")]
    # Weiß and Weiss are different names, so the capitals keep ß
    expected = ["WEIS, Carl", "WEIß, Anna", "WEISS, Ben", "WEISZ, Dora"]
    assert heads(people, de()) == expected
    assert heads(people) == expected  # the English fold already casefolds ß to ss


def test_expand_applies_to_given_names_too():
    people = [("Jörg", "Lang"), ("Jürgen", "Lang"), ("Joerg", "Lang"), ("Jorg", "Lang")]
    assert givens(people, de()) == ["Jörg", "Joerg", "Jorg", "Jürgen"]


def test_von_der_heide_files_under_h():
    people = [
        ("Anna", "von der Heide"),
        ("Ida", "Haas"),
        ("Bert", "Heine"),
        ("Karl", "Hahn"),
        ("Eva", "Vogel"),
    ]
    # the skipped particles print after the given name, so the entry reads as it files
    assert heads(people, de()) == [
        "HAAS, Ida",
        "HAHN, Karl",
        "HEIDE, Anna von der",
        "HEINE, Bert",
        "VOGEL, Eva",
    ]
    # English keeps the particle: under V
    assert heads(people)[-1] == "VON DER HEIDE, Anna"


def test_german_skips_zur_and_von_und_zu():
    people = [
        ("Ida", "Lang"),
        ("Anna", "zur Lippe"),
        ("Karl", "von und zu Guttenberg"),
        ("Bert", "Gut"),
        ("Jan", "ten Brink"),
        ("Eva", "Braun"),
    ]
    assert heads(people, de()) == [
        "BRAUN, Eva",
        "BRINK, Jan ten",
        "GUT, Bert",
        "GUTTENBERG, Karl von und zu",
        "LANG, Ida",
        "LIPPE, Anna zur",
    ]


def test_van_gogh_files_between_goethe_and_gogol():
    people = [("Anna", "Goethe"), ("Vincent", "van Gogh"), ("Nikolai", "Gogol")]
    assert heads(people, de()) == [
        "GOETHE, Anna",
        "GOGH, Vincent van",
        "GOGOL, Nikolai",
    ]
    assert heads(people) == ["GOETHE, Anna", "GOGOL, Nikolai", "VAN GOGH, Vincent"]


def test_a_surname_that_is_only_a_particle_is_not_stripped():
    people = [("Anna", "Vogel"), ("Bert", "Van"), ("Carl", "Uhl")]
    assert heads(people, de()) == ["UHL, Carl", "VAN, Bert", "VOGEL, Anna"]


def test_particles_match_whole_words_only():
    # stripping "van" from the front would give "derhoff"
    people = [("Ida", "Ruhe"), ("Bert", "Vanderhoff")]
    assert heads(people, de()) == ["RUHE, Ida", "VANDERHOFF, Bert"]


def test_the_sort_changes_the_order_but_not_the_spelling():
    people = [
        ("Ulrich", "Müller"),
        ("Anna", "Mueller"),
        ("Carl", "Muller"),
        ("Dora", "Mutz"),
        ("Ida", "Haas"),
    ]
    english, german = heads(people), heads(people, de())
    assert sorted(german) == sorted(english)
    assert german != english


def test_placeholder_surnames_sort_last_under_a_language():
    people = [("Mary", "(UNKNOWN)"), ("Anna", "Zeller"), ("Ben", "Abel")]
    assert heads(people, de()) == ["ABEL, Ben", "ZELLER, Anna", "(UNKNOWN), Mary"]


def test_german_sort_settings_follow_din_5007_2():
    assert kincade.lang.load_strings("de")["sort"] == {
        "expand": {"ä": "ae", "ö": "oe", "ü": "ue"},
        "after_z": [],
        "surname_start": {},
        "keep_case_prefixes": ["Mc"],
        "ignore_particles": [
            "von",
            "zu",
            "vom",
            "zum",
            "zur",
            "und",
            "van",
            "de",
            "der",
            "den",
            "dem",
            "ten",
            "ter",
        ],
    }


# ---------------------------------------------------------------- French, Spanish, Italian


def test_french_skips_de_and_elided_d_but_keeps_articles_and_du():
    people = [
        ("Charles", "d’Artagnan"),
        ("Anne", "Arnaud"),
        ("Jean", "de Gaulle"),
        ("Paul", "Gauthier"),
        ("Jean", "de La Fontaine"),
        ("Louis", "Lambert"),
        ("Joachim", "du Bellay"),
        ("Marc", "Dubois"),
    ]
    assert heads(people, kincade.lang.load_strings("fr")) == [
        "ARNAUD, Anne",
        "ARTAGNAN, Charles d’",
        "DU BELLAY, Joachim",
        "DUBOIS, Marc",
        "GAULLE, Jean de",
        "GAUTHIER, Paul",
        "LA FONTAINE, Jean de",
        "LAMBERT, Louis",
    ]
    assert heads(people)[:4] == [
        "ARNAUD, Anne",
        "D’ARTAGNAN, Charles",
        "DE GAULLE, Jean",
        "DE LA FONTAINE, Jean",
    ]


def test_french_ligatures_sort_as_two_letters():
    people = [("Paul", "Ozanne"), ("Lucie", "Œuvray"), ("Olive", "Oeuvray")]
    assert heads(people, kincade.lang.load_strings("fr")) == [
        "ŒUVRAY, Lucie",
        "OEUVRAY, Olive",
        "OZANNE, Paul",
    ]
    # without the expansion œ is not a letter of a to z, so it sorts after them
    assert heads(people)[-1] == "ŒUVRAY, Lucie"


def test_an_elided_particle_alone_is_not_stripped():
    people = [("Anne", "Dupont"), ("Bert", "D’"), ("Carl", "Cadet")]
    assert heads(people, kincade.lang.load_strings("fr")) == [
        "CADET, Carl",
        "D’, Bert",
        "DUPONT, Anne",
    ]


def test_an_elided_particle_matches_either_apostrophe():
    strings = kincade.lang.load_strings(None, {"sort": {"ignore_particles": ["d'"]}})
    assert strings["sort"]["ignore_particles"] == ["d'"]
    people = [("Ann", "Brun"), ("Eve", "d’Arc"), ("Ida", "D'Amours"), ("Jo", "Carre")]
    assert heads(people, strings) == [
        "AMOURS, Ida D'",
        "ARC, Eve d’",
        "BRUN, Ann",
        "CARRE, Jo",
    ]


def test_french_files_hyphenated_names_word_by_word():
    people = [
        ("Charles", "Sainte-Beuve"),
        ("Antoine", "Saint-Exupéry"),
        ("Rosa", "Martinez"),
        ("Paul", "Martin-Rey"),
    ]
    assert heads(people, kincade.lang.load_strings("fr")) == [
        "MARTIN-REY, Paul",
        "MARTINEZ, Rosa",
        "SAINT-EXUPÉRY, Antoine",
        "SAINTE-BEUVE, Charles",
    ]


def test_spanish_files_enye_after_n_and_skips_de_del_and_their_articles():
    people = [
        ("Ana", "Muñoz"),
        ("Luis", "Muntaner"),
        ("Eva", "Murillo"),
        ("Juan", "de la Fuente"),
        ("Rosa", "Fuentes"),
        ("Pedro", "del Río"),
        ("Inés", "Ríos"),
    ]
    assert heads(people, kincade.lang.load_strings("es")) == [
        "FUENTE, Juan de la",
        "FUENTES, Rosa",
        "MUNTANER, Luis",
        "MUÑOZ, Ana",
        "MURILLO, Eva",
        "RÍO, Pedro del",
        "RÍOS, Inés",
    ]
    assert heads(people)[:4] == [
        "DE LA FUENTE, Juan",
        "DEL RÍO, Pedro",
        "FUENTES, Rosa",
        "MUÑOZ, Ana",
    ]


def test_spanish_keeps_a_leading_article_as_the_filing_word():
    people = [
        ("Manuel", "Las Heras"),
        ("Ana", "Heras"),
        ("Miguel", "de los Santos"),
        ("José", "San José"),
        ("Luis", "Ruiz Zorrilla"),
        ("Eva", "Ruiz-Mateos"),
    ]
    assert heads(people, kincade.lang.load_strings("es")) == [
        "HERAS, Ana",
        "LAS HERAS, Manuel",
        "RUIZ-MATEOS, Eva",
        "RUIZ ZORRILLA, Luis",
        "SAN JOSÉ, José",
        "SANTOS, Miguel de los",
    ]


def test_italian_files_surnames_with_their_particles_as_english_does():
    people = [
        ("Gino", "Russo"),
        ("Marco", "De Luca"),
        ("Luca", "Lo Russo"),
        ("Sara", "D’Angelo"),
        ("Anna", "Dal Lago"),
    ]
    italian = heads(people, kincade.lang.load_strings("it"))
    assert (
        italian
        == heads(people)
        == [
            "DAL LAGO, Anna",
            "D’ANGELO, Sara",
            "DE LUCA, Marco",
            "LO RUSSO, Luca",
            "RUSSO, Gino",
        ]
    )


# ----------------------------------------------------------------
# Swedish, Finnish, Danish, Norwegian


def test_swedish_letters_sort_after_z_in_the_order_given(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nafter_z = ["å", "ä", "ö"]\n')
    )
    people = [
        ("Anna", "Zetterberg"),
        ("Bo", "Åberg"),
        ("Cia", "Äkerlund"),
        ("Dan", "Öberg"),
        ("Eva", "Ahlström"),
    ]
    assert heads(people, strings) == [
        "AHLSTRÖM, Eva",
        "ZETTERBERG, Anna",
        "ÅBERG, Bo",
        "ÄKERLUND, Cia",
        "ÖBERG, Dan",
    ]
    assert heads(people) == [
        "ÅBERG, Bo",
        "AHLSTRÖM, Eva",
        "ÄKERLUND, Cia",
        "ÖBERG, Dan",
        "ZETTERBERG, Anna",
    ]


def test_danish_and_norwegian_letters_sort_after_z_in_the_order_given(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nafter_z = ["æ", "ø", "å"]\n')
    )
    people = [
        ("Anna", "Zacho"),
        ("Bo", "Åkjær"),
        ("Cia", "Østergaard"),
        ("Dan", "Ærøe"),
    ]
    assert heads(people, strings) == [
        "ZACHO, Anna",
        "ÆRØE, Dan",
        "ØSTERGAARD, Cia",
        "ÅKJÆR, Bo",
    ]


def test_after_z_letters_are_matched_before_their_accents_are_folded(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nafter_z = ["Å"]\n')
    )
    rules = kincade.lang.SortRules(strings["sort"])
    assert rules.fold("Åberg") > rules.fold("Zorn")  # folded to a, it would sort first
    assert rules.fold("Äkerlund") < rules.fold("Zorn")  # not listed, so it folds to a


def test_danish_aa_expansion_sorts_with_the_after_z_letter(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(
            tmp_path,
            '[sort]\nafter_z = ["æ", "ø", "å"]\n[sort.expand]\n"aa" = "å"\n',
        )
    )
    rules = kincade.lang.SortRules(strings["sort"])
    assert rules.fold("Aagaard") == rules.fold("Ågård")
    assert heads([("Anna", "Aagaard"), ("Bo", "Ågård"), ("Cia", "Zacho")], strings) == [
        "ZACHO, Cia",
        "AAGAARD, Anna",
        "ÅGÅRD, Bo",
    ]


# ----------------------------------------------------------------
# Spanish: ñ through expand


def test_spanish_enye_sorts_after_n_through_expand(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort.expand]\n"ñ" = "n~"\n')
    )
    people = [
        ("Ana", "Nuñez"),
        ("Beto", "Nunez"),
        ("Carla", "Nuevo"),
        ("Dani", "Nieto"),
        ("Eva", "Ortiz"),
        ("Fer", "Ñoño"),
    ]
    assert heads(people, strings) == [
        "NIETO, Dani",
        "NUEVO, Carla",
        "NUNEZ, Beto",
        "NUÑEZ, Ana",
        "ÑOÑO, Fer",
        "ORTIZ, Eva",
    ]
    # without the rule the enye folds to n and the English order mixes it in
    # with the N names
    assert heads(people)[:3] == ["NIETO, Dani", "ÑOÑO, Fer", "NUEVO, Carla"]


# ---------------------------------------------------------------- surname starts and Mc


MC_PEOPLE = [
    ("Ida", "Lee"),
    ("Ann", "MacDonald"),
    ("Bob", "McClure"),
    ("Eve", "McNair"),
    ("Zed", "Nash"),
]


@pytest.mark.parametrize(
    "body", ['[sort.surname_start]\nmc = "mac"\n', "[sort]\nmc_as_mac = true\n"]
)
def test_a_surname_start_files_mc_names_as_if_they_began_mac(tmp_path, body):
    # mc_as_mac = true, the version 1.0 setting, is read as mc = "mac"
    mac = kincade.lang.load_strings(write_lang(tmp_path, body))
    assert mac["sort"]["surname_start"] == {"mc": "mac"}
    assert heads(MC_PEOPLE) == [
        "LEE, Ida",
        "MACDONALD, Ann",
        "McCLURE, Bob",
        "McNAIR, Eve",
        "NASH, Zed",
    ]
    # the printed names do not change
    assert heads(MC_PEOPLE, mac) == [
        "LEE, Ida",
        "McCLURE, Bob",
        "MACDONALD, Ann",
        "McNAIR, Eve",
        "NASH, Zed",
    ]


def test_a_surname_start_is_matched_after_particles_and_longest_first(tmp_path):
    s = kincade.lang.load_strings(
        write_lang(
            tmp_path,
            '[sort]\nignore_particles = ["van"]\n'
            '[sort.surname_start]\nmc = "mac"\nmcc = "z"\n',
        )
    )
    rules = kincade.lang.SortRules(s["sort"])
    assert rules.fold("van McNair", surname=True) == "macnair"
    assert rules.fold("McClure", surname=True) == "zlure"
    assert rules.fold("McNair") == "mcnair"  # a given name is never changed


def test_mc_as_mac_false_changes_nothing(tmp_path):
    s = kincade.lang.load_strings(write_lang(tmp_path, "[sort]\nmc_as_mac = false\n"))
    assert s["sort"] == kincade.lang.DEFAULT_STRINGS["sort"]


@pytest.mark.parametrize(
    "prefixes,surname,printed",
    [
        ('["Mc"]', "McClure", "McCLURE"),
        ('["Mc"]', "Mcclure", "MCCLURE"),  # no capital after the prefix
        ('["Mc"]', "MacDonald", "MACDONALD"),
        ('["Mc", "Mac"]', "MacDonald", "MacDONALD"),
        ('["Mc", "Mac"]', "Macy", "MACY"),
        ("[]", "McClure", "MCCLURE"),
    ],
)
def test_keep_case_prefixes_keep_their_case_in_capitals(
    tmp_path, prefixes, surname, printed
):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, f"[sort]\nkeep_case_prefixes = {prefixes}\n")
    )
    rules = kincade.lang.SortRules(strings["sort"])
    assert kincade.lang.fmt_surname(surname, rules=rules) == printed
    assert heads([("Ann", surname)], strings) == [f"{printed}, Ann"]


def test_keep_case_prefixes_follow_the_particles(tmp_path):
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nignore_particles = ["van"]\n')
    )
    rules = kincade.lang.SortRules(strings["sort"])
    assert kincade.lang.fmt_surname("van McNair", rules=rules) == "van McNAIR"
    assert heads([("Eve", "van McNair")], strings) == ["McNAIR, Eve van"]


# ----------------------------------------------------------------
# loading and merging the settings


def test_settings_are_casefolded_once_loaded(tmp_path):
    s = kincade.lang.load_strings(
        write_lang(
            tmp_path,
            '[sort]\nafter_z = ["Å"]\nignore_particles = ["Van"]\n[sort.expand]\n"Ä" = "AE"\n'
            '[sort.surname_start]\nMc = "MAC"\n',
        )
    )
    assert s["sort"] == {
        "expand": {"ä": "ae"},
        "after_z": ["å"],
        "ignore_particles": ["van"],
        "surname_start": {"mc": "mac"},
        "keep_case_prefixes": ["Mc"],
    }


def test_expand_is_merged_with_the_language_table_and_lists_are_replaced():
    s = kincade.lang.load_strings(
        "de", {"sort": {"expand": {"ø": "oe"}, "ignore_particles": ["van"]}}
    )
    assert s["sort"]["expand"] == {"ä": "ae", "ö": "oe", "ü": "ue", "ø": "oe"}
    assert s["sort"]["ignore_particles"] == ["van"]
    assert s["sort"]["keep_case_prefixes"] == ["Mc"]  # the rest of the table stays


def test_a_language_file_can_give_only_the_sort_keys_it_changes(tmp_path):
    s = kincade.lang.load_strings(write_lang(tmp_path, '[sort]\nafter_z = ["å"]\n'))
    assert s["sort"] == {
        "expand": {},
        "after_z": ["å"],
        "ignore_particles": [],
        "surname_start": {},
        "keep_case_prefixes": ["Mc"],
    }


@pytest.mark.parametrize(
    "body,fragment",
    [
        ('[sort]\nafter_z = ["aa"]\n', "sort.after_z"),  # longer than one character
        ('[sort]\nafter_z = [""]\n', "sort.after_z"),
        ('[sort]\nafter_z = "å"\n', "sort.after_z"),  # a string, not a list
        ("[sort]\nafter_z = [1]\n", "sort.after_z"),
        (
            '[sort]\nafter_z = ["å", "Å"]\n',
            "sort.after_z",
        ),  # the same letter twice after casefolding
        ('[sort.expand]\n"" = "x"\n', "sort.expand"),  # an empty key
        ('[sort.expand]\n"ñ" = 3\n', "sort.expand"),  # a value that is not text
        ('[sort]\nexpand = ["ñ"]\n', "sort.expand"),  # a list where a table is expected
        ('[sort]\nignore_particles = "van"\n', "sort.ignore_particles"),
        (
            '[sort]\nignore_particles = ["de l’"]\n',
            "sort.ignore_particles",
        ),  # an elided particle is one word
        ('[sort]\nignore_particles = [""]\n', "sort.ignore_particles"),
        (
            '[sort]\nignore_particles = ["l’a"]\n',
            "sort.ignore_particles",
        ),  # an apostrophe only at the end, after the particle
        ('[sort]\nignore_particles = ["\'"]\n', "sort.ignore_particles"),
        ('[sort]\nmc_as_mac = "yes"\n', "sort.mc_as_mac"),
        ("[sort]\nmc_as_mac = 1\n", "sort.mc_as_mac"),  # a number is not true or false
        ('[sort.surname_start]\n"m\'" = "mac"\n', "sort.surname_start"),  # punctuation
        ('[sort.surname_start]\n" " = "mac"\n', "sort.surname_start"),
        ("[sort.surname_start]\nmc = 1\n", "sort.surname_start"),
        ('[sort]\nsurname_start = "mc"\n', "sort.surname_start"),
        ('[sort]\nkeep_case_prefixes = "Mc"\n', "sort.keep_case_prefixes"),
        ('[sort]\nkeep_case_prefixes = ["M c"]\n', "sort.keep_case_prefixes"),
        ('[sort]\nkeep_case_prefixes = [""]\n', "sort.keep_case_prefixes"),
        ('sort = "none"\n', "sort"),
    ],
)
def test_bad_sort_settings_are_errors_that_name_the_setting(tmp_path, body, fragment):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(write_lang(tmp_path, body))
    assert fragment in str(e.value)


def test_an_unknown_sort_key_is_warned_about_and_ignored(tmp_path, capsys):
    with pytest.warns(UserWarning, match="unknown key 'sort.case'"):
        s = kincade.lang.load_strings(write_lang(tmp_path, "[sort]\ncase = true\n"))
    assert "case" not in s["sort"]
    assert capsys.readouterr() == ("", "")


def test_a_bad_sort_setting_fails_the_command_line_before_the_gedcom_is_read(
    tmp_path, capsys
):
    bad = write_lang(tmp_path, '[sort]\nafter_z = ["aa"]\n')
    assert (
        kincade.cli.main(
            [
                str(FIX / "pedigree.ged"),
                "--root",
                "@I1@",
                "--lang",
                bad,
                "-o",
                str(tmp_path / "x.pdf"),
            ]
        )
        == 1
    )
    assert "sort.after_z" in capsys.readouterr().err
    assert not (tmp_path / "x.pdf").exists()


# ----------------------------------------------------------------
# the key comes from the stored surname


def test_the_sort_key_is_built_from_the_stored_surname_not_its_capitals(tmp_path):
    # Capitalized for display, "ırmak" becomes "IRMAK", which folds to "irmak": it would
    # sort as an i. The key must keep the letter the file gave, so the after_z letter
    # sorts after z, after "Zuber".
    strings = kincade.lang.load_strings(
        write_lang(tmp_path, '[sort]\nafter_z = ["ı"]\n')
    )
    people = [("Bo", "ırmak"), ("Ann", "Zuber")]
    assert givens(people, strings) == ["Ann", "Bo"]

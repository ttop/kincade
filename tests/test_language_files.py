"""The language TOML contract: every string the PDF prints comes from DEFAULT_STRINGS,
a bundled lang/*.toml file, a user or path-named file, or the Options.lang argument (a
name, a path or a mapping of strings).

Synthetic fixtures only.
"""

import contextlib
import datetime
import io
import os
import re
import tomllib
import warnings
from pathlib import Path

import pytest

import kincade
import kincade.charts
import kincade.cli
import kincade.lang
import kincade.pdf
from kincade.gedcom import parse_date, read_gedcom

from conftest import TODAY, USER_LANG_DIR, ged, render
from pdfread import drawn

TABLE_LEAVES = (
    "days.",
    "dates.with_day.",
    "dates.rewrite.",
    "sort.expand.",
    "sort.surname_start.",
)


def leaves(node, prefix=""):
    """Dotted paths of every leaf (a string, a list of strings, or a table whose keys
    are data: days, dates.with_day, dates.rewrite, sort.expand, sort.surname_start) of
    a nested strings dict."""
    if isinstance(node, dict) and prefix not in TABLE_LEAVES:
        return {
            p for key, value in node.items() for p in leaves(value, f"{prefix}{key}.")
        }
    return {prefix[:-1]}


def lang_file(tmp_path, text, name="x.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------- every bundled file


# the chart and index text the pedigree fixture draws in each Romance language
ROMANCE_RENDER = {
    "es": [
        "Árbol de antepasados — Jane ASHFORD",
        "Cuadro 1",
        "Cuadro 2",
        "Índice onomástico",
        "Creado el 10 oct. 2026 con Kincade",
        "Página 1 de 6",
        "n. 14 feb. 1980",
        "en Springfield, Illinois",
        "n. 3 mar. 1950",
        "f. 2 abr. 2020",
        "en Dayton, Ohio",
        "El n.º 1 de este cuadro corresponde al n.º 8 del cuadro 1.",
        "ASHFORD, Jane (n. 1980), 1-1",
    ],
    "fr": [
        "Arbre d’ascendance — Jane ASHFORD",
        "Tableau 1",
        "Tableau 2",
        "Index des noms",
        "Créé le 10 oct. 2026 avec Kincade",
        "Page 1 sur 6",
        "naiss. 14 févr. 1980",
        "à Springfield, Illinois",
        "naiss. 3 mars 1950",
        "décès 2 avr. 2020",
        "à Dayton, Ohio",
        "Le n° 1 de ce tableau correspond au n° 8 du tableau 1.",
        "ASHFORD, Jane (° 1980), 1-1",
    ],
    "it": [
        "Albero degli antenati — Jane ASHFORD",
        "Tavola 1",
        "Tavola 2",
        "Indice dei nomi",
        "Creato in data 10 ott. 2026 con Kincade",
        "Pagina 1 di 6",
        "n. 14 feb. 1980",
        "Springfield, Illinois",
        "n. 3 mar. 1950",
        "m. 2 apr. 2020",
        "Dayton, Ohio",
        "Il n. 1 di questa tavola corrisponde al n. 8 della tavola 1.",
        "ASHFORD, Jane (n. 1980), 1-1",
    ],
}

# the chart and index text the pedigree fixture draws in German
DE_RENDER = [
    "Ahnentafel — Jane ASHFORD",
    "Tafel 1",
    "Tafel 2",
    "Namensregister",
    "Erstellt am 10. Okt. 2026 mit Kincade",
    "geb. 14. Febr. 1980",
    "in Springfield, Illinois",
    "geb. 3. März 1950",
    "gest. 2. Apr. 2020",
    "in Dayton, Ohio",
]

FAN_TITLES = {
    "de": "Fächerahnentafel — Jane ASHFORD",
    "es": "Jane ASHFORD — Árbol en abanico",
    "fr": "Jane ASHFORD — Arbre en éventail",
    "it": "Jane ASHFORD — Albero a ventaglio",
    "en": "Jane ASHFORD — Fan chart",
}

# six dates picked to catch a misreading of the year or the word: a full date, the
# first of the month (1er / 1º), a leading approximation word, an approximation with a
# day (with_day), an open "from", and a between range (en dash). The seventh exercises
# the dates.rewrite table: Italian and French elide "dal"/"de" before a vowel.
SIX_DATES = [
    "13 JAN 1917",
    "1 MAR 1800",
    "ABT 1755",
    "BEF 3 MAR 1990",
    "FROM 1622",
    "BET 1622 AND 1632",
    "FROM 8 MAR 1910",
]
DATE_READINGS = {
    "de": [
        "13. Jan. 1917",
        "1. März 1800",
        "um 1755",
        "vor 3. März 1990",
        "ab 1622",
        "1622 – 1632",
        "ab 8. März 1910",
    ],
    "es": [
        "13 ene. 1917",
        "1 mar. 1800",
        "hacia 1755",
        "antes de 3 mar. 1990",
        "desde 1622",
        "1622–1632",
        "desde 8 mar. 1910",
    ],
    "fr": [
        "13 janv. 1917",
        "1er mars 1800",
        "vers 1755",
        "avant le 3 mars 1990",
        "à partir de 1622",
        "1622–1632",
        "à partir du 8 mars 1910",
    ],
    "it": [
        "13 gen. 1917",
        "1º mar. 1800",
        "ca. 1755",
        "ante 3 mar. 1990",
        "dal 1622",
        "1622–1632",
        "dall’8 mar. 1910",
    ],
    "en": [
        "13 Jan 1917",
        "1 Mar 1800",
        "abt 1755",
        "bef 3 Mar 1990",
        "from 1622",
        "1622-1632",
        "from 8 Mar 1910",
    ],
}

# the footer's "Created" date, for the first of the month, in each language's wording
FIRST_OF_MONTH_FOOTER = {
    "en": "Created 1 Mar 2026 using Kincade",
    "de": "Erstellt am 1. März 2026 mit Kincade",
    "es": "Creado el 1 mar. 2026 con Kincade",
    "fr": "Créé le 1er mars 2026 avec Kincade",
    "it": "Creato in data 1º mar. 2026 con Kincade",
}


def _no_english_labels(text):
    """None of the English-only markers (chart label, footer, index title, page text)
    appear."""
    return not any(
        t == "Index" or t.startswith(("b. ", "d. ", "Chart ", "Created ", "Page 1 of"))
        for t in text
    )


@pytest.mark.parametrize("lang", ["de", "en", "es", "fr", "it"])
def test_each_bundled_language_is_complete_and_draws_its_wording(lang, pedigree):
    path = kincade.lang.LANG_DIR / f"{lang}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert leaves(data) == leaves(kincade.lang.DEFAULT_STRINGS), lang
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        strings = kincade.lang.load_strings(lang)
    assert strings["title"]  # loaded with no warning raised above

    text = drawn(render(pedigree, generations=5, lang=lang))
    if lang == "en":
        # lang="en" draws exactly what no language draws
        assert text == drawn(render(pedigree, generations=5))
    else:
        group = DE_RENDER if lang == "de" else ROMANCE_RENDER[lang]
        for expected in group:
            assert expected in text, (lang, expected)
        assert _no_english_labels(text), lang

    fan = kincade.plan_fan(pedigree, "I1", lang=lang)
    fan_pdf = kincade.render_fan(
        fan,
        kincade.FanOptions(lang=lang, today=TODAY, fonts="base14", compress=False),
    )
    assert FAN_TITLES[lang] in drawn(fan_pdf), lang

    strings = kincade.lang.load_strings(lang)
    for raw, expected in zip(SIX_DATES, DATE_READINGS[lang], strict=True):
        assert kincade.lang.format_date(parse_date(raw), strings) == expected, (
            lang,
            raw,
        )

    footer_text = drawn(
        render(
            pedigree,
            generations=1,
            index=False,
            lang=lang,
            today=datetime.date(2026, 3, 1),
        )
    )
    assert FIRST_OF_MONTH_FOOTER[lang] in footer_text, lang


def test_english_file_mirrors_the_defaults_and_placeholders():
    assert (
        tomllib.loads((kincade.lang.LANG_DIR / "en.toml").read_text(encoding="utf-8"))
        == kincade.lang.DEFAULT_STRINGS
    )
    assert leaves(kincade.lang.DEFAULT_STRINGS) == set(kincade.lang.PLACEHOLDERS)


# ---------------------------------------------------------------- finding a language


def test_a_language_is_found_by_name_path_or_user_folder(tmp_path, monkeypatch):
    real_lang_dir = kincade.lang.LANG_DIR
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(kincade.lang, "LANG_DIR", bundled)
    monkeypatch.setattr(kincade.lang, "_user_lang_dir", lambda: user)
    # the user folder is found first...
    (user / "xx.toml").write_text('title = "User"\n', encoding="utf-8")
    assert kincade.lang.lang_path("xx") == user / "xx.toml"
    # ...but the bundled folder wins once a name is in both
    (bundled / "xx.toml").write_text('title = "Bundled"\n', encoding="utf-8")
    assert kincade.lang.lang_path("xx") == bundled / "xx.toml"
    assert kincade.lang.load_strings("xx")["title"] == "Bundled"
    # an unknown name lists both places it looked
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.lang_path("zz")
    assert (
        "zz.toml" in str(e.value)
        and str(bundled) in str(e.value)
        and str(user) in str(e.value)
    )
    # a value ending in .toml, or containing a path separator, is a path; "~" expands
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "my-wording.toml").write_text('title = "Mine"\n', encoding="utf-8")
    assert (
        kincade.lang.load_strings(str(tmp_path / "my-wording.toml"))["title"] == "Mine"
    )
    assert kincade.lang.load_strings("~/my-wording.toml")["title"] == "Mine"
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings("nowhere/missing")

    # with no home folder, as in some containers, only the (real) bundled folder is used
    monkeypatch.setattr(kincade.lang, "LANG_DIR", real_lang_dir)

    def no_home(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    monkeypatch.setattr(kincade.lang, "_user_lang_dir", USER_LANG_DIR)
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.lang_path("zz")
    assert str(e.value) == f"no language file zz.toml in {real_lang_dir}"
    assert kincade.lang.load_strings("de")["title"] == "Ahnentafel"


# ---------------------------------------------------------------- bad language files


def _check_invalid_toml(tmp_path):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(lang_file(tmp_path, 'title = "unclosed\n'))


def _check_wrong_value_type(tmp_path):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, "title = 3\n"))
    assert "title" in str(e.value)


def _check_bad_placeholder(tmp_path):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, 'footer = "{nope}"\n'))
    assert "nope" in str(e.value)
    # a placeholder in a key that takes none: a relationship note
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(None, {"relationship": {"adopted": "(adopted {n})"}})
    assert "relationship.adopted" in str(e.value)
    # likewise a record_id template with another placeholder
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(None, {"record_id": "[{nope}]"})
    assert "record_id" in str(e.value)


def _check_ellipsis_of_4_characters(tmp_path):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, 'ellipsis = "abcd"\n'))
    assert "ellipsis" in str(e.value)


def _check_bad_sort_or_dates(tmp_path):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, '[sort]\nafter_z = "a"\n'))
    assert "sort.after_z" in str(e.value)
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, '[dates]\nwith_day = "x"\n'))
    assert "dates.with_day" in str(e.value)


BAD_LANGUAGE_FILES = {
    "invalid toml": _check_invalid_toml,
    "wrong value type": _check_wrong_value_type,
    "bad placeholder": _check_bad_placeholder,
    "ellipsis of 4 characters": _check_ellipsis_of_4_characters,
    "bad sort or dates setting": _check_bad_sort_or_dates,
}


@pytest.mark.parametrize("case", BAD_LANGUAGE_FILES)
def test_bad_language_files_are_lang_errors_naming_the_key(tmp_path, case):
    BAD_LANGUAGE_FILES[case](tmp_path)


# ---------------------------------------------------------------- unknown keys, overrides


def test_unknown_keys_warn_and_overrides_apply(tmp_path, capsys):
    # one warning per unknown key, which is then ignored
    path = lang_file(
        tmp_path,
        'title = "Stammbaum"\ncolor = "red"\n[extra]\na = "1"\n[labels]\nnope = "x"\n',
    )
    with pytest.warns(UserWarning) as notices:
        s = kincade.lang.load_strings(path)
    err = "\n".join(str(notice.message) for notice in notices)
    assert s["title"] == "Stammbaum" and "color" not in s and "extra" not in s
    assert err.count("unknown key") == 3
    assert "'color'" in err and "'extra'" in err and "'labels.nope'" in err
    assert capsys.readouterr() == ("", "")

    # a strings mapping overrides the language, and is itself validated
    s = kincade.lang.load_strings("de", {"title": "Mine", "index": {"title": "X"}})
    assert s["title"] == "Mine" and s["index"]["title"] == "X"
    assert s["footer"] == kincade.lang.load_strings("de")["footer"]
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(None, {"footer": "{title}"})

    # title and footer render arguments beat the language file
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Root /ROOT/"))
    text = drawn(
        render(tree, "I1", lang="de", title="Mine", footer="Footer", index=False)
    )
    assert "Mine" in text and "Footer" in text and "Ahnentafel" not in text

    # version 1.0's sort.mc_as_mac is still read, as surname_start mc = "mac"
    mac = kincade.lang.load_strings(
        lang_file(tmp_path, "[sort]\nmc_as_mac = true\n", name="mac.toml")
    )
    assert mac["sort"]["surname_start"] == {"mc": "mac"}


# ---------------------------------------------------------------- a fully custom file


CUSTOM_LANGUAGE_FILE = """\
file_name = "{name} Custom"
record_id = "#{id}"
ellipsis = "~"
living_name = "Private"

[days]
1 = "1st"

[dates.with_day]
before = "before the"

[dates.rewrite]
"from 8" = "from8"

[index]
reference = "{chart}:{pos}"

[sort]
after_z = ["å"]
keep_case_prefixes = ["Mc", "Mac"]
ignore_particles = ["von", "der"]

[sort.surname_start]
mc = "mac"

[years]
born_only = "* {born}"
"""


def test_a_custom_language_changes_every_place_it_is_used(tmp_path):
    custom = lang_file(tmp_path, CUSTOM_LANGUAGE_FILE)

    # the days table and with_day apply to the box's date text
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", "2 DATE BEF 1 JAN 1917")
    )
    text = drawn(render(tree, "I1", lang=custom, show_ids=True))
    assert "b. before the 1st Jan 1917" in text
    # the record_id template and the index.reference template
    assert "#I1" in text
    assert any(t.startswith("DOE, Pat #I1") and t.endswith(", 1:1") for t in text)

    # dates.rewrite applies: "from 8" becomes "from8"
    rewrite_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Deb /Doe/", "1 BIRT", "2 DATE FROM 8 JAN 1920")
    )
    rewrite_text = drawn(render(rewrite_tree, "I1", lang=custom, index=False))
    assert "b. from8 Jan 1920" in rewrite_text

    # a place too long to fit is cut with the language's own ellipsis ("~")
    long_place = (
        "Verylongplacenamethatclearlyexceedstheboxwidthforanyboxatallwhatsoever" * 2
    )
    long_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Lex /Doe/", "1 BIRT", f"2 PLAC {long_place}")
    )
    long_text = drawn(render(long_tree, "I1", lang=custom, index=False))
    assert any(t.startswith("bp.") and t.endswith("~") for t in long_text)

    # the file name template, through the CLI
    ged_path = tmp_path / "pat.ged"
    ged_path.write_bytes(
        ged("0 @I1@ INDI", "1 NAME Pat /Doe/", "1 BIRT", "2 DATE 1900")
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert kincade.cli.main([str(ged_path), "--root", "I1", "--lang", custom]) == 0
        assert (tmp_path / "Pat Doe Custom.pdf").exists()
    finally:
        os.chdir(cwd)

    # keep_case_prefixes: MacDonald prints MacDONALD, Macy prints MACY (no capital
    # follows the prefix)
    mac_tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /MacDonald/",
            "0 @I2@ INDI",
            "1 NAME Mac /Macy/",
            "0 @I3@ INDI",
            "1 NAME Bob /McClure/",
            "0 @I4@ INDI",
            "1 NAME Zed /Nash/",
            "0 @I5@ INDI",
            "1 NAME Ida /Lee/",
        )
    )
    assert "Ann MacDONALD" in drawn(render(mac_tree, "I1", lang=custom))
    assert "Mac MACY" in drawn(render(mac_tree, "I2", lang=custom))

    # after_z = ["å"]: an Å surname files after every plain Z surname
    after_z_tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ulla /Åsen/",
            "0 @I2@ INDI",
            "1 NAME Vic /Zorn/",
        )
    )
    strings_for_sort = kincade.lang.load_strings(custom)
    az_slots = dict.fromkeys(range(1, 16))
    az_slots.update({1: "I1", 2: "I2"})
    az_order = kincade.pdf.build_index(
        after_z_tree,
        [kincade.charts.Chart(1, az_slots)],
        lambda pid: False,
        exclude_private=False,
        strings=strings_for_sort,
    )
    az_names = [e.split(",")[0] for e in az_order]
    assert az_names.index("ÅSEN") > az_names.index("ZORN")

    # surname_start mc = "mac": McClure files next to the Mac names, not after Nash
    slots = dict.fromkeys(range(1, 16))
    slots.update({i: f"I{i}" for i in range(1, 6)})
    chart = kincade.charts.Chart(1, slots)
    strings = kincade.lang.load_strings(custom)
    order = kincade.pdf.build_index(
        mac_tree, [chart], lambda pid: False, exclude_private=False, strings=strings
    )
    names = [e.split(",")[0] for e in order]
    assert names.index("McCLURE") < names.index("NASH")
    assert names.index("McCLURE") == names.index("MacDONALD") - 1

    # ignore_particles: "von der Heide" prints and indexes with the particles skipped
    heide_tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Anna /von der Heide/"))
    text = drawn(render(heide_tree, "I1", lang=custom, generations=1))
    assert "Anna von der HEIDE" in text
    assert any(t.startswith("HEIDE, Anna von der") for t in text)

    # living_name: --exclude-private shows "Private" instead of "Living"
    living_tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Liv /Doe/", "1 BIRT", "2 DATE 1980")
    )
    assert "Private" in drawn(
        render(living_tree, "I1", lang=custom, exclude_private=True)
    )
    liv_path = tmp_path / "liv.ged"
    liv_path.write_bytes(
        ged("0 @I1@ INDI", "1 NAME Liv /Doe/", "1 BIRT", "2 DATE 1980")
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        kincade.cli.main(
            [str(liv_path), "--find", "Liv", "--lang", custom, "--exclude-private"]
        )
    assert "Private" in out.getvalue()

    # years.born_only: a fan shows "* 1980" for a living person born 1980
    fan = kincade.plan_fan(living_tree, "I1", lang=custom)
    fan_pdf = kincade.render_fan(
        fan,
        kincade.FanOptions(lang=custom, today=TODAY, fonts="base14", compress=False),
    )
    assert "* 1980" in drawn(fan_pdf)


# ---------------------------------------------------------------- the index sort order


# about a dozen surnames that exercise particles, placeholders, decomposed umlauts,
# punctuation, "van Gogh" between/under its neighbors, "de"/"del"/"d'" particles, a
# ligature, and the Spanish enye
SORT_PEOPLE = [
    ("Anna", "Goethe"),
    ("Vincent", "van Gogh"),
    ("Nikolai", "Gogol"),
    ("Ulrich", "Müller"),  # decomposed umlaut
    ("Carl", "Muller"),
    ("Pat", "O'Brien"),
    ("Mary", "[?]"),  # a placeholder surname
    ("Ida", "von der Heide"),
    ("Jan", "zur Lippe"),
    ("Charles", "d’Artagnan"),
    ("Jean", "de Gaulle"),
    ("Lucie", "Œuvray"),
    ("Pedro", "del Río"),
    ("Ana", "Nuñez"),
    ("Beto", "Nunez"),
]

SORT_ORDER = {
    "en": [
        "D’ARTAGNAN, Charles",
        "DE GAULLE, Jean",
        "DEL RÍO, Pedro",
        "GOETHE, Anna",
        "GOGOL, Nikolai",
        "MULLER, Carl",
        "MÜLLER, Ulrich",
        "NUÑEZ, Ana",
        "NUNEZ, Beto",
        "O'BRIEN, Pat",
        "VAN GOGH, Vincent",
        "VON DER HEIDE, Ida",
        "ZUR LIPPE, Jan",
        "ŒUVRAY, Lucie",
        "[?], Mary",
    ],
    "de": [
        "D’ARTAGNAN, Charles",
        "DEL RÍO, Pedro",
        "GAULLE, Jean de",
        "GOETHE, Anna",
        "GOGH, Vincent van",
        "GOGOL, Nikolai",
        "HEIDE, Ida von der",
        "LIPPE, Jan zur",
        "MÜLLER, Ulrich",
        "MULLER, Carl",
        "NUÑEZ, Ana",
        "NUNEZ, Beto",
        "O'BRIEN, Pat",
        "ŒUVRAY, Lucie",
        "[?], Mary",
    ],
    "fr": [
        "ARTAGNAN, Charles d’",
        "DEL RÍO, Pedro",
        "GAULLE, Jean de",
        "GOETHE, Anna",
        "GOGOL, Nikolai",
        "MULLER, Carl",
        "MÜLLER, Ulrich",
        "NUÑEZ, Ana",
        "NUNEZ, Beto",
        "O'BRIEN, Pat",
        "ŒUVRAY, Lucie",
        "VAN GOGH, Vincent",
        "VON DER HEIDE, Ida",
        "ZUR LIPPE, Jan",
        "[?], Mary",
    ],
    "es": [
        "D’ARTAGNAN, Charles",
        "GAULLE, Jean de",
        "GOETHE, Anna",
        "GOGOL, Nikolai",
        "MULLER, Carl",
        "MÜLLER, Ulrich",
        "NUNEZ, Beto",
        "NUÑEZ, Ana",
        "O'BRIEN, Pat",
        "RÍO, Pedro del",
        "VAN GOGH, Vincent",
        "VON DER HEIDE, Ida",
        "ZUR LIPPE, Jan",
        "ŒUVRAY, Lucie",
        "[?], Mary",
    ],
}


def _index_heads(people, strings=None):
    """'SURNAME, Given [particles]' for each entry, in index order, without years or
    chart references."""
    lines = []
    for i, (given, surname) in enumerate(people, 1):
        lines += [f"0 @I{i}@ INDI", f"1 NAME {given} /{surname}/"]
    tree = read_gedcom(("\n".join(lines + ["0 TRLR"])).encode("utf-8"))
    slots = dict.fromkeys(range(1, 16))
    slots.update({i: f"I{i}" for i in range(1, len(people) + 1)})
    entries = kincade.pdf.build_index(
        tree,
        [kincade.charts.Chart(1, slots)],
        lambda pid: False,
        exclude_private=False,
        strings=strings or kincade.lang.DEFAULT_STRINGS,
    )
    return [re.sub(r"(, \d+[-/:]\d+)+$", "", e.split(" (")[0]) for e in entries]


@pytest.mark.parametrize("lang", ["en", "de", "fr", "es"])
def test_the_index_sorts_by_the_languages_rules(lang):
    strings = None if lang == "en" else kincade.lang.load_strings(lang)
    assert _index_heads(SORT_PEOPLE, strings) == SORT_ORDER[lang], lang
    if lang == "en":
        # Italian files the same names in the same order as English
        it_strings = kincade.lang.load_strings("it")
        assert _index_heads(SORT_PEOPLE, it_strings) == SORT_ORDER["en"]

"""Language support: every string the PDF prints comes from DEFAULT_STRINGS, a
lang/*.toml file, or the Options.lang argument (a name, a path or a mapping of strings).

Synthetic fixtures only.
"""

import datetime
import errno
import re
import tomllib
import warnings
from pathlib import Path

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import parse_date, read_gedcom

from conftest import FIX, TOO_LONG, ged, render, render_charts
from pdfread import drawn

ENGLISH_FOOTER = "Created 10 Oct 2026 using Kincade"


TABLE_LEAVES = ("days.", "dates.with_day.", "dates.rewrite.", "sort.expand.")


def leaves(node, prefix=""):
    """Dotted paths of every leaf (a string, a list of strings, or a table whose keys
    are data: days, dates.with_day, dates.rewrite, sort.expand) of a nested strings
    dict.
    """
    # the keys of these tables are data, so each table is one leaf
    if isinstance(node, dict) and prefix not in TABLE_LEAVES:
        return {
            p for key, value in node.items() for p in leaves(value, f"{prefix}{key}.")
        }
    return {prefix[:-1]}


def lang_file(tmp_path, text, name="x.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ----------------------------------------------------------------
# the English wording and the template file


def test_default_strings_are_the_english_wording():
    d = kincade.lang.DEFAULT_STRINGS
    assert d["title"] == "Cascading Pedigree"
    assert d["fan_title"] == "{name} — Fan chart"
    assert d["meta_title"] == "{title} — {name}"
    assert d["footer"] == "Created {date} using Kincade"
    assert d["date_format"] == "{day} {month} {year}"
    assert d["days"] == {}
    assert d["file_name"] == "{name} cascading pedigree"
    assert d["fan_file_name"] == "{name} fan chart"
    assert d["blank_file_name"] == "Blank cascading pedigree"
    assert d["chart_label"] == "Chart {n}"
    assert (
        d["continuation"]
        == "Number 1 on this chart is the same as number {pos} on chart {chart}."
    )
    assert d["ellipsis"] == "…"
    assert (
        d["months"]["short"]
        == kincade.lang.MONTHS
        == [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
    )
    assert d["index"] == {
        "title": "Index",
        "born": "b. {birth}",
        "died": "d. {death}",
        "joiner": " – ",
        "years": "({years})",
        "christened": "chr. {birth}",
        "buried": "bur. {death}",
        "cremated": "crem. {death}",
        "legend": "The numbers after each name indicate the chart number and box number. 6-1 is box 1 on chart 6.",
        "reference": "{chart}-{pos}",
    }
    assert d["labels"] == {
        "birth": "b.",
        "birth_place": "bp.",
        "spouse": "spouse:",
        "marriage": "m.",
        "marriage_place": "mp.",
        "death": "d.",
        "death_place": "dp.",
        "christening": "chr.",
        "christening_place": "chrp.",
        "burial": "bur.",
        "burial_place": "burp.",
        "cremation": "crem.",
        "cremation_place": "cremp.",
    }
    assert d["dates"] == {
        "about": "abt",
        "estimated": "est",
        "calculated": "cal",
        "before": "bef",
        "after": "aft",
        "from": "from",
        "to": "to",
        "range": "-",
        "with_day": {},
        "rewrite": {},
    }
    assert d["years"] == {
        "christening": "chr {y}",
        "burial": "bur {y}",
        "cremation": "crem {y}",
        "deceased": "Deceased",
        "about": "abt {y}",
        "before": "bef {y}",
        "after": "aft {y}",
        "between": "bet {y}",
    }


def test_german_fan_title_and_year_words():
    strings = kincade.lang.load_strings("de")
    assert strings["fan_title"] == "Fächerahnentafel — {name}"
    assert strings["years"] == {
        "christening": "get. {y}",
        "burial": "begr. {y}",
        "cremation": "krem. {y}",
        "deceased": "verstorben",
        "about": "um {y}",
        "before": "vor {y}",
        "after": "nach {y}",
        "between": "zw. {y}",
    }


def test_lang_en_toml_mirrors_the_default_strings():
    assert (
        tomllib.loads((kincade.lang.LANG_DIR / "en.toml").read_text(encoding="utf-8"))
        == kincade.lang.DEFAULT_STRINGS
    )


def test_every_string_names_its_placeholders():
    assert leaves(kincade.lang.DEFAULT_STRINGS) == set(kincade.lang.PLACEHOLDERS)


@pytest.mark.parametrize("lang", ["de", "es", "fr", "it"])
def test_each_bundled_language_translates_every_key_without_warnings(lang, capsys):
    path = kincade.lang.LANG_DIR / f"{lang}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert leaves(data) == leaves(kincade.lang.DEFAULT_STRINGS)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        strings = kincade.lang.load_strings(lang)
    # complete, so nothing falls back and every template is valid; the sort settings
    # are read into their normal form (d’ as d')
    assert {k: v for k, v in strings.items() if k != "sort"} == {
        k: v for k, v in data.items() if k != "sort"
    }
    assert capsys.readouterr().err == ""


def test_load_strings_without_arguments_is_a_fresh_english_copy():
    s = kincade.lang.load_strings()
    assert s == kincade.lang.DEFAULT_STRINGS and s is not kincade.lang.DEFAULT_STRINGS
    s["title"] = "changed"
    assert kincade.lang.DEFAULT_STRINGS["title"] == "Cascading Pedigree"


def test_the_bundled_languages_are_inside_the_package():
    assert kincade.lang.LANG_DIR == Path(kincade.__file__).resolve().parent / "lang"


# ----------------------------------------------------------------
# where a language name is looked up


def test_a_language_name_is_looked_up_in_the_bundled_folder_then_the_user_folder(
    tmp_path, monkeypatch
):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(kincade.lang, "LANG_DIR", bundled)
    monkeypatch.setattr(kincade.lang, "_user_lang_dir", lambda: user)
    (user / "xx.toml").write_text('title = "User"\n', encoding="utf-8")
    assert kincade.lang.lang_path("xx") == user / "xx.toml"
    (bundled / "xx.toml").write_text('title = "Bundled"\n', encoding="utf-8")
    # the bundled folder wins
    assert kincade.lang.lang_path("xx") == bundled / "xx.toml"
    assert kincade.lang.load_strings("xx")["title"] == "Bundled"


def test_an_unknown_language_name_lists_where_it_looked(tmp_path, monkeypatch):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    monkeypatch.setattr(kincade.lang, "LANG_DIR", bundled)
    monkeypatch.setattr(kincade.lang, "_user_lang_dir", lambda: user)
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.lang_path("zz")
    assert (
        "zz.toml" in str(e.value)
        and str(bundled) in str(e.value)
        and str(user) in str(e.value)
    )


@pytest.mark.usefixtures("no_home_folder")
def test_with_no_home_folder_a_language_name_is_looked_up_in_the_bundled_folder_only():
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.lang_path("zz")
    assert str(e.value) == f"no language file zz.toml in {kincade.lang.LANG_DIR}"
    assert kincade.lang.load_strings("de")["title"] == "Ahnentafel"


def test_a_path_or_a_toml_name_is_loaded_as_given(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "my-wording.toml").write_text('title = "Mine"\n', encoding="utf-8")
    assert (
        kincade.lang.load_strings(str(tmp_path / "my-wording.toml"))["title"] == "Mine"
    )
    # ~ is expanded
    assert kincade.lang.load_strings("~/my-wording.toml")["title"] == "Mine"
    # a path is never looked up in the language folders
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings("nowhere/missing")
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(str(tmp_path / "missing.toml"))


# ----------------------------------------------------------------
# merging, warnings and errors


def test_missing_keys_fall_back_to_english(tmp_path):
    s = kincade.lang.load_strings(
        lang_file(tmp_path, 'title = "Stammbaum"\n[index]\ntitle = "Register"\n')
    )
    assert s["title"] == "Stammbaum" and s["index"]["title"] == "Register"
    assert (
        s["index"]["born"] == "b. {birth}"
        and s["footer"] == kincade.lang.DEFAULT_STRINGS["footer"]
    )


def test_unknown_keys_are_warned_about_once_each_and_ignored(tmp_path, capsys):
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


def test_library_warnings_can_be_ignored_without_stderr(capsys):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        strings = kincade.lang.load_strings(strings={"extra": "invented"})
    assert strings["title"] == "Cascading Pedigree"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "body",
    [
        "title = 3\n",
        'title = ["Stammbaum"]\n',
        'labels = "b."\n',  # a table where a string is expected
        "[labels]\nbirth = true\n",
        '[months]\nshort = "Jan"\n',
        '[months]\nshort = ["Jan", "Feb"]\n',  # not 12 names
        "[months]\nshort = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]\n",
        "[index]\ntitle = { x = 1 }\n",
    ],
)
def test_values_of_the_wrong_type_are_errors(tmp_path, body):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(lang_file(tmp_path, body))


@pytest.mark.parametrize(
    "body,fragment",
    [
        (
            'footer = "Erstellt {datum}"\n',
            "datum",
        ),  # a placeholder the code does not supply
        ('chart_label = "Tafel {n} {x}"\n', "x"),
        ('footer = "Erstellt {}"\n', None),  # positional placeholders are not allowed
        ('footer = "Erstellt {date"\n', None),  # broken syntax
        ('footer = "Erstellt }"\n', None),
        (
            'footer = "Erstellt {title}"\n',
            "title",
        ),  # a real placeholder, but not one for this key
        (
            'title = "Stammbaum {n}"\n',
            None,
        ),  # a plain string has no placeholders at all
        ('continuation = "{pos} auf {title}"\n', "title"),
        ('[labels]\nbirth = "geb. {n}"\n', None),
        (
            '[months]\nshort = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "{dec}"]\n',
            None,
        ),
    ],
)
def test_placeholders_are_checked_when_the_file_loads(tmp_path, body, fragment):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, body))
    if fragment:
        assert fragment in str(e.value)


def test_templates_may_leave_placeholders_out(tmp_path):
    s = kincade.lang.load_strings(
        lang_file(tmp_path, 'footer = "Erstellt"\nchart_label = "Tafel {n}"\n')
    )
    assert s["footer"] == "Erstellt" and s["chart_label"] == "Tafel {n}"


# ----------------------------------------------------------------
# templates: plain {name} fields only


@pytest.mark.parametrize(
    "body,key",
    [
        ('chart_label = "Tafel {n:200}"\n', "chart_label"),  # a format spec
        ('chart_label = "Tafel {n!r}"\n', "chart_label"),  # a conversion
        ('footer = "Erstellt {date.__class__}"\n', "footer"),  # attribute access
        ('footer = "Erstellt {date[0]}"\n', "footer"),  # index access
        ('chart_label = "Tafel {}"\n', "chart_label"),  # an empty field
        ('chart_label = "Tafel {0}"\n', "chart_label"),  # a positional field
        ('footer = "Erstellt {date"\n', "footer"),  # unbalanced
        ('footer = "Erstellt date}"\n', "footer"),  # a lone closing brace
        (
            'footer = "Erstellt {{date}"\n',
            "footer",
        ),  # an escaped brace, then an unbalanced one
        (
            '[index]\nborn = "geb. {birth:>9}"\n',
            "index.born",
        ),  # a nested key is named in full
    ],
)
def test_a_field_that_is_not_a_plain_placeholder_is_a_langerror_naming_the_key(
    tmp_path, body, key
):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, body))
    assert key in str(e.value)


def test_double_braces_are_literal_braces_in_a_template(tmp_path):
    s = kincade.lang.load_strings(
        lang_file(tmp_path, 'chart_label = "Tafel {{{n}}}"\n')
    )
    assert kincade.lang.fill(s["chart_label"], ("n",), {"n": 1}) == "Tafel {1}"


def test_fill_substitutes_plain_names_and_double_braces_are_literal():
    assert (
        kincade.lang.fill("Tafel {n} {{x}} {{{n}}} {n}", ("n",), {"n": 3})
        == "Tafel 3 {x} {3} 3"
    )


def test_fill_never_reads_a_substituted_value_as_a_template():
    assert (
        kincade.lang.fill("{name}!", ("name",), {"name": "{title} {0:9}"})
        == "{title} {0:9}!"
    )


@pytest.mark.parametrize(
    "text",
    [
        "{n:3}",
        "{n!r}",
        "{n.real}",
        "{n[0]}",
        "{}",
        "{0}",
        "{x}",
        "{n",
        "n}",
        "{n{",
        "{{n}",
    ],
)
def test_fill_refuses_anything_but_a_plain_allowed_name(text):
    with pytest.raises(ValueError):
        kincade.lang.fill(text, ("n",), {"n": 1})


def test_no_language_template_is_filled_with_str_format():
    source = "".join(
        path.read_text(encoding="utf-8")
        for path in Path(kincade.__file__).parent.glob("*.py")
    )
    assert re.search(r"\.format\(", source) is None


def test_invalid_toml_is_an_error(tmp_path):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(lang_file(tmp_path, 'title = "unclosed\n'))


def test_the_strings_argument_takes_precedence_over_the_language():
    s = kincade.lang.load_strings("de", {"title": "Mine", "index": {"title": "X"}})
    assert s["title"] == "Mine" and s["index"]["title"] == "X"
    # the rest is German
    assert s["footer"] == kincade.lang.load_strings("de")["footer"]


def test_the_strings_argument_is_validated_too():
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(None, {"footer": "{title}"})


# ---------------------------------------------------------------- English output


def test_the_default_render_draws_the_english_text(pedigree):
    text = drawn(render(pedigree, generations=5))
    assert (
        "Cascading Pedigree — Jane ASHFORD" in text
        and "Chart 1" in text
        and "Index" in text
    )
    assert ENGLISH_FOOTER in text
    assert "Number 1 on this chart is the same as number 8 on chart 1." in text
    assert "b. 14 Feb 1980" in text and "bp. Springfield, Illinois" in text


def test_lang_en_draws_exactly_what_no_language_draws(pedigree):
    assert drawn(render(pedigree, generations=5, lang="en")) == drawn(
        render(pedigree, generations=5)
    )


def test_parser_lang_and_title_default_to_none():
    args = kincade.cli._parser().parse_args(["x.ged", "--root", "I1"])
    assert args.lang is None and args.title is None
    assert (
        kincade.cli._parser().parse_args(["x.ged", "--root", "I1", "--lang", "de"]).lang
        == "de"
    )


# ---------------------------------------------------------------- German rendering


def test_german_render_uses_the_german_wording(pedigree):
    text = drawn(render(pedigree, generations=5, lang="de"))
    for expected in [
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
    ]:
        assert expected in text, expected
    assert not any(
        t.startswith(("b. ", "d. ", "Chart ", "Created ", "Index")) for t in text
    )


def test_german_continuation_line(pedigree):
    text = drawn(render(pedigree, generations=5, lang="de", index=False))
    assert "Nr. 1 auf dieser Tafel ist identisch mit Nr. 8 auf Tafel 1." in text


def test_german_metadata_title(pedigree):
    assert b"/Title (Ahnentafel " in render(pedigree, generations=1, lang="de")


def test_title_and_footer_arguments_override_the_language(pedigree):
    text = drawn(
        render(pedigree, generations=1, lang="de", title="Mine", footer="Footer")
    )
    assert "Mine" in text and "Footer" in text and "Ahnentafel" not in text


def test_strings_override_the_footer_date_format(pedigree):
    text = drawn(
        render(
            pedigree,
            generations=1,
            index=False,
            lang={"date_format": "{month} {day}, {year}"},
        )
    )
    assert "Created Oct 10, 2026 using Kincade" in text


def test_language_text_is_made_drawable_in_the_font_set(pedigree):
    # no cp1252 glyphs
    text = drawn(render(pedigree, generations=1, index=False, lang={"title": "日本"}))
    assert "?? — Jane ASHFORD" in text


@pytest.mark.parametrize("value", ['""', '"...."', '"abcd"', '"ab\\ncd"'])
def test_ellipsis_must_be_one_to_three_characters(tmp_path, value):
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(lang_file(tmp_path, f"ellipsis = {value}\n"))
    assert "ellipsis" in str(e.value)


@pytest.mark.parametrize("value", ["…", "...", "→→→"])
def test_ellipsis_of_one_to_three_characters_is_accepted(tmp_path, value):
    assert (
        kincade.lang.load_strings(lang_file(tmp_path, f'ellipsis = "{value}"\n'))[
            "ellipsis"
        ]
        == value
    )


def test_an_ellipsis_argument_of_no_characters_is_a_langerror():
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(None, {"ellipsis": ""})


def test_ellipsis_comes_from_the_language(pedigree):
    assert kincade.pdf.fit("x" * 200, "Times-Roman", 9, 100, ellipsis="...").endswith(
        "..."
    )
    text, scale = kincade.pdf.fit_squeezed(
        "x" * 200, "Times-Roman", 9, 100, ellipsis="..."
    )
    assert text.endswith("...") and 0.5 <= scale <= 1.0
    text = drawn(
        render(
            pedigree,
            generations=1,
            index=False,
            lang={"ellipsis": "...", "title": "T" * 400},
        )
    )
    assert any(t.startswith("TTT") and t.endswith("...") for t in text)


# ---------------------------------------------------------------- dates


DE_DATES = [
    ("13 JAN 1917", "13. Jan. 1917"),
    ("1 MAR 1800", "1. März 1800"),
    ("5 MAY 1900", "5. Mai 1900"),
    ("10 OCT 1900", "10. Okt. 1900"),
    ("24 DEC 1900", "24. Dez. 1900"),
    ("JAN 1917", "Jan. 1917"),  # no day: not a full date, so no date_format
    ("1917", "1917"),
    ("ABT 1755", "um 1755"),
    ("~1863", "um 1863"),
    ("EST 1755", "geschätzt 1755"),
    ("CAL 1755", "err. 1755"),
    ("BEF 1800", "vor 1800"),
    ("AFT 1800", "nach 1800"),
    ("BET 1622 AND 1632", "1622 – 1632"),
    ("FROM 1622 TO 1632", "1622 – 1632"),
    ("FROM 1622", "ab 1622"),
    ("TO 1632", "bis 1632"),
    ("", ""),
]


@pytest.mark.parametrize("raw,expected", DE_DATES)
def test_german_dates(raw, expected):
    assert (
        kincade.lang.format_date(parse_date(raw), kincade.lang.load_strings("de"))
        == expected
    )


def test_format_date_without_strings_is_english():
    assert kincade.lang.format_date(parse_date("13 JAN 1917")) == "13 Jan 1917"
    assert kincade.lang.format_date(parse_date("ABT 1755")) == "abt 1755"


def test_date_format_reorders_full_dates_only():
    s = kincade.lang.load_strings(None, {"date_format": "{month} {day}, {year}"})
    assert kincade.lang.format_date(parse_date("13 JAN 1917"), s) == "Jan 13, 1917"
    assert kincade.lang.format_date(parse_date("JAN 1917"), s) == "Jan 1917"
    assert kincade.lang.format_date(parse_date("ABT 1755"), s) == "abt 1755"


def test_german_index_years_and_locators():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Jane /Doe/",
            "1 BIRT",
            "2 DATE 13 JAN 1850",
            "1 DEAT",
            "2 DATE 3 OCT 1920",
        )
    )
    charts = plan_charts(tree, "I1")
    assert kincade.pdf.build_index(
        tree,
        charts,
        lambda pid: False,
        exclude_private=False,
        strings=kincade.lang.load_strings("de"),
    ) == ["DOE, Jane (* 1850, † 1920), 1/1"]
    assert kincade.pdf.build_index(
        tree, charts, lambda pid: False, exclude_private=False
    ) == ["DOE, Jane (b. 1850 – d. 1920), 1-1"]


# ---------------------------------------------------------------- Spanish, French, Italian


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


@pytest.mark.parametrize("lang", sorted(ROMANCE_RENDER))
def test_spanish_french_and_italian_renders_use_their_wording(pedigree, lang):
    text = drawn(render(pedigree, generations=5, lang=lang))
    for expected in ROMANCE_RENDER[lang]:
        assert expected in text, expected
    assert not any(
        t == "Index" or t.startswith(("b. ", "d. ", "Chart ", "Created ", "Page 1 of"))
        for t in text
    )


ROMANCE_DATES = [
    # raw, Spanish, French, Italian
    ("13 JAN 1917", "13 ene. 1917", "13 janv. 1917", "13 gen. 1917"),
    ("1 MAR 1800", "1 mar. 1800", "1er mars 1800", "1º mar. 1800"),
    ("1 AUG", "1 ago.", "1er août", "1º ago."),
    ("5 MAY 1900", "5 may. 1900", "5 mai 1900", "5 mag. 1900"),
    ("24 DEC 1900", "24 dic. 1900", "24 déc. 1900", "24 dic. 1900"),
    ("SEP 1917", "sept. 1917", "sept. 1917", "set. 1917"),
    ("ABT 1755", "hacia 1755", "vers 1755", "ca. 1755"),
    ("EST 1755", "est. 1755", "estim. 1755", "stim. 1755"),
    ("CAL 1755", "calc. 1755", "calc. 1755", "calc. 1755"),
    ("BEF 1800", "antes de 1800", "avant 1800", "ante 1800"),
    ("AFT 1800", "después de 1800", "après 1800", "post 1800"),
    ("BET 1622 AND 1632", "1622–1632", "1622–1632", "1622–1632"),
    ("FROM 1622", "desde 1622", "à partir de 1622", "dal 1622"),
    ("TO 1632", "hasta 1632", "jusqu’en 1632", "fino al 1632"),
    ("JUL 1900", "jul. 1900", "juill. 1900", "lug. 1900"),
    # before a day: French takes the article, Italian elides before a vowel
    (
        "BEF 3 MAR 1990",
        "antes de 3 mar. 1990",
        "avant le 3 mars 1990",
        "ante 3 mar. 1990",
    ),
    (
        "ABT 1 JAN 1900",
        "hacia 1 ene. 1900",
        "vers le 1er janv. 1900",
        "ca. 1º gen. 1900",
    ),
    (
        "FROM 8 MAR 1910",
        "desde 8 mar. 1910",
        "à partir du 8 mars 1910",
        "dall’8 mar. 1910",
    ),
    (
        "TO 11 APR 1980",
        "hasta 11 abr. 1980",
        "jusqu’au 11 avr. 1980",
        "fino all’11 apr. 1980",
    ),
    ("FROM APR 1960", "desde abr. 1960", "à partir d’avr. 1960", "dall’apr. 1960"),
    ("TO OCT 1960", "hasta oct. 1960", "jusqu’en oct. 1960", "fino all’ott. 1960"),
    (
        "FROM 18 MAR 1910",
        "desde 18 mar. 1910",
        "à partir du 18 mars 1910",
        "dal 18 mar. 1910",
    ),
]


@pytest.mark.parametrize("raw,es,fr,it", ROMANCE_DATES)
def test_spanish_french_and_italian_dates(raw, es, fr, it):
    for lang, expected in (("es", es), ("fr", fr), ("it", it)):
        strings = kincade.lang.load_strings(lang)
        assert kincade.lang.format_date(parse_date(raw), strings) == expected


@pytest.mark.parametrize(
    "lang,footer",
    [
        (None, "Created 1 Mar 2026 using Kincade"),
        ("de", "Erstellt am 1. März 2026 mit Kincade"),
        ("es", "Creado el 1 mar. 2026 con Kincade"),
        ("fr", "Créé le 1er mars 2026 avec Kincade"),
        ("it", "Creato in data 1º mar. 2026 con Kincade"),
    ],
)
def test_the_first_of_the_month_in_the_footer_is_written_as_the_language_writes_it(
    pedigree, lang, footer
):
    text = drawn(
        render(
            pedigree,
            generations=1,
            index=False,
            lang=lang,
            today=datetime.date(2026, 3, 1),
        )
    )
    assert footer in text


def test_the_days_table_writes_the_days_it_lists_and_adds_to_the_language_below():
    s = kincade.lang.load_strings("fr", {"days": {2: "2e", "3": "3e"}})
    assert s["days"] == {"1": "1er", "2": "2e", "3": "3e"}
    assert kincade.lang.format_date(parse_date("1 JAN 1917"), s) == "1er janv. 1917"
    assert kincade.lang.format_date(parse_date("2 JAN 1917"), s) == "2e janv. 1917"
    assert kincade.lang.format_date(parse_date("11 JAN 1917"), s) == "11 janv. 1917"
    assert kincade.lang.format_date(parse_date("BEF 1 JAN 1917"), s) == (
        "avant le 1er janv. 1917"
    )


@pytest.mark.parametrize(
    "dates",
    [
        {"with_day": {"range": "au"}},
        {"with_day": {"before": ""}},
        {"with_day": {"before": "{date}"}},
        {"with_day": "avant le"},
        {"rewrite": {"": "x"}},
        {"rewrite": {"dal 8": 8}},
        {"rewrite": {"dal 8": "{day}"}},
        {"rewrite": ["dal 8"]},
    ],
)
def test_bad_date_tables_are_errors(dates):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(None, {"dates": dates})


def test_date_rewrites_match_whole_words_only():
    s = kincade.lang.load_strings(None, {"dates": {"rewrite": {"from 8": "from8"}}})
    assert (
        kincade.lang.format_date(parse_date("FROM 8 MAR 1910"), s) == "from8 Mar 1910"
    )
    assert kincade.lang.format_date(parse_date("FROM 1880"), s) == "from 1880"


def test_the_index_reference_is_the_languages_template(pedigree):
    text = drawn(
        render(pedigree, generations=1, lang={"index": {"reference": "{chart}:{pos}"}})
    )
    assert any(t.startswith("ASHFORD, Jane") and t.endswith(", 1:1") for t in text)


@pytest.mark.parametrize(
    "lang,box,entry",
    [
        (None, "Anna VON DER HEIDE", "VON DER HEIDE, Anna"),
        ("de", "Anna von der HEIDE", "HEIDE, Anna von der"),
    ],
)
def test_skipped_particles_print_in_recorded_case_and_after_the_given_name(
    lang, box, entry
):
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Anna /von der Heide/"))
    text = drawn(render(tree, lang=lang))
    assert box in text
    assert any(t.startswith(entry + ",") for t in text)
    # preserve_case keeps every word as recorded
    assert "Anna von der Heide" in drawn(render(tree, lang=lang, preserve_case=True))


@pytest.mark.parametrize(
    "days",
    [
        "1er",
        {"0": "0"},
        {"32": "32e"},
        {"first": "1er"},
        {True: "1er"},
        {"1": ""},
        {"1": 1},
        {"1": "{day}"},
    ],
)
def test_a_days_table_needs_days_from_1_to_31_with_plain_text(days):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(None, {"days": days})


@pytest.mark.parametrize(
    "lang,expected",
    [
        ("es", "ASHFORD, Ann (baut. 1750, sepult. 1800), 1-1"),
        ("fr", "ASHFORD, Ann (bapt. 1750, inh. 1800), 1-1"),
        ("it", "ASHFORD, Ann (batt. 1750, sep. 1800), 1-1"),
    ],
)
def test_spanish_french_and_italian_stand_ins_in_boxes_and_index(lang, expected):
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Ann /Ashford/",
            "1 CHR",
            "2 DATE 1750",
            "2 PLAC Little Hall",
            "1 BURI",
            "2 DATE 1800",
        )
    )
    strings = kincade.lang.load_strings(lang)
    text = drawn(render(tree, lang=lang))
    christening = strings["labels"]["christening"]
    place = strings["labels"]["christening_place"]
    # an empty place label leaves the place bare
    assert f"{christening} 1750" in text
    assert (f"{place} Little Hall" if place else "Little Hall") in text
    assert f"{strings['labels']['burial']} 1800" in text
    assert expected in text


# ----------------------------------------------------------------
# library arguments and the command line


def test_library_lang_argument_is_resolved_at_render_time(pedigree):
    with pytest.raises(kincade.lang.LangError):
        render(pedigree, lang="zz")


def test_library_strings_argument_is_checked_at_render_time(pedigree):
    with pytest.raises(kincade.lang.LangError):
        render(pedigree, lang={"footer": "{title}"})


def test_cli_lang_flag_selects_the_language_and_the_flags_win(
    tmp_path, capsys, rendered_options
):
    base = [
        str(FIX / "pedigree.ged"),
        "--root",
        "@I1@",
        "--generations",
        "2",
        "-o",
        str(tmp_path / "x.pdf"),
    ]
    assert kincade.cli.main(base + ["--lang", "de", "--title", "Mine"]) == 0
    assert (
        rendered_options[-1].title == "Mine"
        and rendered_options[-1].lang["title"] == "Ahnentafel"
    )
    assert kincade.cli.main(base) == 0
    assert (
        rendered_options[-1].title is None
        and rendered_options[-1].lang["title"] == "Cascading Pedigree"
    )
    assert kincade.cli.main(base + ["--lang", "zz"]) == 1
    assert "zz.toml" in capsys.readouterr().err


def test_cli_bad_language_file_exits_1(tmp_path, capsys):
    bad = lang_file(tmp_path, "title = 3\n")
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
    assert "title must be a string" in capsys.readouterr().err


@pytest.mark.parametrize(
    "chart,words", [([], "Ahnentafel"), (["--fan"], "Fächerahnentafel")]
)
def test_the_default_output_is_named_by_the_languages_file_name(
    tmp_path, pedigree, chart, words
):
    args = [str(FIX / "pedigree.ged"), "--root", "@I1@", "--generations", "2"]
    assert kincade.cli.main([*args, "--lang", "de", *chart]) == 0
    name = kincade.lang.display_name(pedigree.people["I1"], preserve_case=True)
    assert [path.name for path in tmp_path.glob("*.pdf")] == [f"{words} {name}.pdf"]


def test_the_blank_chart_is_named_by_the_languages_blank_file_name(tmp_path):
    assert kincade.cli.main(["--blank", "--lang", "fr"]) == 0
    assert [path.name for path in tmp_path.glob("*.pdf")] == [
        "Arbre d'ascendance vierge.pdf"
    ]


@pytest.mark.parametrize(
    "template,name,expected",
    [
        ("{name} Tafel", "Zoë/Wilks", "Zoë_Wilks Tafel.pdf"),
        ("{name} Tafel", "..", "Tafel.pdf"),
        ("Ahnen: {name}", "Ann", "Ahnen_ Ann.pdf"),
        ("{name}", "", "Kincade.pdf"),
    ],
)
def test_a_file_name_template_is_made_safe_around_the_name(template, name, expected):
    strings = kincade.lang.load_strings(None, {"file_name": template})
    assert kincade.cli.default_output_name(name, strings) == expected


# ----------------------------------------------------------------
# values that cannot be used


def test_a_language_file_with_a_number_too_long_for_tomllib_is_a_langerror(tmp_path):
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(lang_file(tmp_path, "title = " + "9" * 5000 + "\n"))


def test_a_language_path_with_a_nul_or_an_unknown_home_is_a_langerror():
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings("a\x00b.toml")
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings("~zz-no-such-user-kincade/x.toml")


# ----------------------------------------------------------------
# names the file system rejects


def test_a_language_name_too_long_for_the_file_system_is_a_langerror():
    # on Python 3.11-3.13 is_file raises OSError here
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.lang_path(TOO_LONG)
    with pytest.raises(kincade.lang.LangError):
        kincade.lang.load_strings(TOO_LONG)
    with pytest.raises(kincade.lang.LangError):
        render_charts(
            read_gedcom(ged("0 @I1@ INDI", "1 NAME Root /ROOT/")), lang=TOO_LONG
        )


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENAMETOOLONG, "File name too long"),
        PermissionError(13, "Permission denied"),
        OSError(5, "Input/output error"),
        ValueError("embedded null byte"),
    ],
)
def test_any_error_probing_for_a_language_file_is_a_langerror(monkeypatch, error):
    def fail(self):
        raise error

    monkeypatch.setattr(Path, "is_file", fail)
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.lang_path("de")
    message = str(e.value)
    assert (
        "\n" not in message
        and "de.toml" in message
        and (getattr(error, "strerror", None) or str(error)) in message
    )


def test_an_unreadable_language_path_is_a_langerror(tmp_path):
    for value in (
        str(tmp_path),
        str(tmp_path / "no" / "such.toml"),
        str(tmp_path / TOO_LONG) + ".toml",
    ):
        with pytest.raises(kincade.lang.LangError):
            kincade.lang.load_strings(value)

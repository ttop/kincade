"""The page in its languages: chosen by ?lang=, by the browser or by the picker, with
the chart language following the page's until the reader picks another."""

import re

import pytest
from playwright.sync_api import expect

from conftest import text

MARRIAGES = b"""0 HEAD
0 @I1@ INDI
1 NAME Root /Ashford/
1 DEAT Y
1 FAMS @F1@
1 FAMS @F2@
0 @I2@ INDI
1 NAME First /McClure/
1 DEAT Y
0 @I3@ INDI
1 NAME Second /DeWitt/
1 DEAT Y
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
0 @F2@ FAM
1 HUSB @I1@
1 WIFE @I3@
1 MARR
2 DATE 2022
2 PLAC Secondtown
0 TRLR
"""


def test_both_language_menus_list_the_bundled_languages_by_their_own_names(app):
    app.start()
    for selector in ("#page-lang", "#chart-lang"):
        options = app.page.locator(f"{selector} option")
        assert options.all_text_contents() == [
            "Deutsch",
            "English",
            "Español",
            "Français",
            "Italiano",
        ]
        assert [
            options.nth(index).get_attribute("value")
            for index in range(options.count())
        ] == ["de", "en", "es", "fr", "it"]


def test_a_lang_address_opens_the_page_and_its_charts_in_french(app):
    app.start(lang="fr")
    page = app.page
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    assert page.title() == "Kincade — Arbres généalogiques"
    expect(page.locator("#tree-heading")).to_have_text("Arbre généalogique")
    expect(page.locator("#page-lang")).to_have_value("fr")
    expect(page.locator("#chart-lang")).to_have_value("fr")
    expect(page.locator("#pedigree-title")).to_have_attribute(
        "placeholder", "Arbre d’ascendance — Nom de la personne de départ"
    )
    expect(page.locator("#footer")).to_have_attribute(
        "placeholder", re.compile(r"^Créé le \S+ \S+ \d{4} avec Kincade$")
    )
    app.sample()
    expect(page.locator("#file-summary")).to_have_text(
        "george-washington.ged : 47 personnes"
    )
    expect(page.locator("#root-summary")).to_have_text(
        "Personne de départ : I1, George WASHINGTON"
    )
    expect(page.locator("#pdf-summary")).to_contain_text(
        "5 tableaux, 1 page d’index, 6 pages"
    )
    assert app.sent("render")[-1]["settings"]["lang"] == "fr"
    body = text(app.pdf())
    assert "Arbre d’ascendance — George WASHINGTON" in body
    assert "Index des noms" in body and "Tableau 2" in body
    app.chart("fan")
    expect(page.locator("#pdf-summary")).to_contain_text(
        "arbre en éventail, 6 générations, 30 personnes"
    )
    assert "George WASHINGTON — Arbre en éventail" in text(app.pdf())


def test_switching_the_page_language_rewords_the_page_and_the_chart_follows(app):
    app.start()
    app.sample()
    page = app.page
    expect(page.locator("#pdf-summary")).to_contain_text("5 charts, 1 index page")
    before = len(app.replies("rendered"))
    page.locator("#page-lang").select_option("it")
    app.wait_render(before)
    app.pdf_ready()
    expect(page.locator("html")).to_have_attribute("lang", "it")
    expect(page.locator("#tree-heading")).to_have_text("Albero genealogico")
    expect(page.locator("#file-summary")).to_have_text(
        "george-washington.ged: 47 persone"
    )
    expect(page.locator("#root-summary")).to_have_text(
        "Persona di partenza: I1, George WASHINGTON"
    )
    expect(page.locator("#root-action")).to_have_attribute(
        "aria-label", "Annulla la scelta della persona"
    )
    expect(page.locator("#pedigree-generation-choice option[value=all]")).to_have_text(
        "Tutte le generazioni"
    )
    expect(page.locator("#pdf-summary")).to_contain_text(
        "5 tavole, 1 pagina dell’indice, 6 pagine"
    )
    expect(page.locator("#chart-lang")).to_have_value("it")
    assert app.sent("render")[-1]["settings"]["lang"] == "it"
    assert "Albero degli antenati — George WASHINGTON" in text(app.pdf())
    # the address keeps the choice
    assert re.search(r"[?&]lang=it\b", page.url)


def test_a_chart_language_chosen_apart_from_the_page_stays_when_the_page_changes(app):
    app.start()
    app.sample()
    page = app.page
    page.locator("#more-options summary").click()
    app.change("#chart-lang", "de")
    expect(page.locator("#tree-heading")).to_have_text("Family tree")
    expect(page.locator("#footer")).to_have_attribute(
        "placeholder", re.compile(r"^Erstellt am .+ mit Kincade$")
    )
    assert "Ahnentafel — George WASHINGTON" in text(app.pdf())
    sent = len(app.sent("render"))
    page.locator("#page-lang").select_option("es")
    expect(page.locator("#tree-heading")).to_have_text("Árbol familiar")
    expect(page.locator("#chart-lang")).to_have_value("de")
    expect(page.locator("#pdf-summary")).to_contain_text(
        "5 cuadros, 1 página de índice, 6 páginas"
    )
    # rewording the page draws no new chart
    assert len(app.sent("render")) == sent


@pytest.mark.parametrize(
    "languages,expected", [(["es-MX", "es", "en"], "es"), (["ja-JP", "ja"], "en")]
)
def test_the_browsers_languages_choose_the_page_language(app, languages, expected):
    app.page.add_init_script(
        f"Object.defineProperty(navigator, 'languages', {{get: () => {languages!r}}})"
    )
    app.start(expect_lang=expected)
    expect(app.page.locator("#page-lang")).to_have_value(expected)
    expect(app.page.locator("#chart-lang")).to_have_value(expected)
    expect(app.page.locator("html")).to_have_attribute("lang", expected)


def test_root_marriages_are_worded_in_the_page_language(app):
    app.start(lang="fr")
    app.upload(MARRIAGES)
    app.select()
    option = app.page.locator("#root-family option[value=F2]")
    expect(option).to_have_text("F2 · Second DEWITT · mar. 2022 · à Secondtown")
    app.page.locator("#page-lang").select_option("en")
    expect(option).to_have_text("F2 · Second DEWITT · m. 2022 · mp. Secondtown")

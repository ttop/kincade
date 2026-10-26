"""Five end-to-end journeys drive the real built site through Playwright, with real
Pyodide renders and real worker replies. Everything a user cannot see from the page
or the downloaded PDF is a Python test at the worker boundary instead."""

import hashlib
import json
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect

from conftest import embedded_fonts, text


def test_the_sample_under_the_csp_header(app):
    """The CSP-restricted build renders the bundled sample as both chart types, the
    typeahead narrows and recovers, and a second root's marriages can be chosen."""
    app.start("csp")
    expect(app.page.locator("#option-controls")).to_be_enabled()
    expect(app.page.locator("#search")).to_be_disabled()
    expect(app.page.locator("#more-options")).not_to_have_attribute("open", "")
    app.sample()
    expect(app.page.locator("#file-summary")).to_contain_text("47 people")
    expect(app.page.locator("#pdf-summary")).to_contain_text(
        "5 charts, 1 index page, 6 pages"
    )
    pdf = app.pdf()
    assert len(pdf.pages) == 6
    assert all(
        tuple(float(x) for x in page.mediabox[2:]) == (612, 792) for page in pdf.pages
    )
    assert pdf.metadata.title == "Cascading Pedigree — George WASHINGTON"
    assert pdf.metadata.title in text(pdf)
    assert len(embedded_fonts(pdf)) == 4
    expect(app.page.locator("#pdf-summary")).not_to_contain_text("Built-in fonts used")
    href = app.page.locator("#download-pdf").get_attribute("href")
    assert app.download() == "George Washington cascading pedigree.pdf"
    expect(app.page.locator("#preview")).to_be_visible()
    frame = app.page.locator("#pdf-frame")
    expect(frame).to_have_attribute("src", f"{href}#view=FitH&navpanes=0")
    assert frame.bounding_box()["height"] > 0

    search = app.page.locator("#search")
    search.fill("ball")
    expect(app.page.locator("#results")).to_contain_text("Mary BALL")
    search.press("Escape")
    expect(search).to_have_value("George WASHINGTON")

    app.chart("fan")
    expect(app.page.locator("#pdf-summary")).to_contain_text(
        "fan chart, 6 generations, 30 people"
    )
    pdf = app.pdf()
    assert len(pdf.pages) == 1
    assert tuple(float(x) for x in pdf.pages[0].mediabox[2:]) == (792, 612)
    assert len(embedded_fonts(pdf)) == 2
    expect(app.page.locator("#pdf-summary")).not_to_contain_text("Built-in fonts used")
    assert app.download() == "George Washington fan chart.pdf"

    app.chart("pedigree")
    app.select("I2")
    choice = app.page.get_by_label("Root marriage", exact=True)
    expect(choice.locator("option[value=F25]")).to_contain_text("Jane BUTLER")
    expect(choice.locator("option[value=F2]")).to_contain_text("Mary BALL")
    app.change("#root-family", "F2")
    body = text(app.pdf())
    assert "Mary BALL" in body and "1731" in body
    assert "Jane BUTLER" not in body
    app.chart("fan")
    assert "root_family" not in app.sent("render")[-1]["settings"]


def test_your_own_file_and_its_options(app):
    """An uploaded file is searched, selected and rendered with every option group,
    privacy keeps the chosen name local, and overlapping renders never race."""
    app.start()
    app.upload()
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    search = app.page.locator("#search")
    search.fill("ash")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    search.press("ArrowDown")
    search.press("Enter")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text("Root: I1, Jane ASHFORD")
    assert "Jane ASHFORD" in text(app.pdf())
    assert app.sent("render")[-1]["settings"] == {
        "generations": None,
        "paper": "letter",
        "large_print": False,
        "exclude_private": False,
        "empty_boxes": True,
        "show_ids": False,
        "preserve_case": False,
        "adoptive_parents": False,
        "event_standins": True,
        "shorten_places": True,
        "shadow": False,
        "root_family": None,
        "title": None,
        "page_numbers": True,
        "index": True,
        "footer": None,
        "lang": "en",
    }

    app.page.locator("#more-options summary").click()
    app.change("#preserve-case", False)
    assert "Mary McClure" in text(app.pdf())
    app.change("#show-ids", True)
    app.change("#empty-boxes", True)
    app.change("#pedigree-title", "Custom title")
    app.change("#footer", "Custom footer")
    with_footer = text(app.pdf())
    assert "[I1]" in with_footer  # show_ids
    assert "Custom title" in with_footer
    assert "Custom footer" in with_footer
    app.change("#no-footer", True)
    expect(app.page.locator("#footer")).to_be_disabled()
    expect(app.page.locator("#footer")).to_have_value("Custom footer")
    assert "Custom footer" not in text(app.pdf())
    assert app.sent("render")[-1]["settings"] == {
        "generations": None,
        "paper": "letter",
        "large_print": False,
        "exclude_private": False,
        "empty_boxes": False,
        "show_ids": True,
        "preserve_case": True,
        "adoptive_parents": False,
        "event_standins": True,
        "shorten_places": True,
        "shadow": False,
        "root_family": None,
        "title": "Custom title",
        "page_numbers": True,
        "index": True,
        "footer": False,
        "lang": "en",
    }

    app.change("#exclude-private", True)
    private_pdf = app.pdf()
    shared_text = text(private_pdf) + str(private_pdf.metadata)
    assert "Living" in text(private_pdf)
    assert "Living" in str(private_pdf.metadata)
    assert "14 Feb 1980" not in text(private_pdf)
    assert "Jane ASHFORD" not in shared_text
    assert app.download() == "Living cascading pedigree.pdf"
    expect(app.page.locator("#search")).to_have_value("Jane ASHFORD")
    expect(
        app.page.locator('#results button[data-record-id="I1"] .years')
    ).to_have_text("")

    pdfs_before = app.page.evaluate("acceptance.pdfs.length")
    app.hold("rendered")
    app.generations("2", wait=False)
    app.held("rendered")
    expect(app.page.locator("#rendering-overlay")).to_be_visible()
    sent = len(app.sent("render"))
    old_href = app.page.locator("#download-pdf").get_attribute("href")
    app.generations("3", wait=False)
    app.page.locator("#chart-fan").check()
    app.page.locator("#fan-generations").select_option("4")
    assert len(app.sent("render")) == sent, "a render stays in flight"
    assert app.page.locator("#download-pdf").get_attribute("href") == old_href
    app.release("rendered")
    app.pdf_ready()
    request = app.sent("render")[-1]
    assert request["chart"] == "fan"
    assert request["settings"]["generations"] == 4
    assert len(app.sent("render")) == sent + 1
    # The discarded stale reply never reaches showPdf, so only the final
    # fan render publishes a new Blob.
    assert app.page.evaluate("acceptance.pdfs.length") == pdfs_before + 1


def test_a_fresh_install_in_a_mounted_folder_over_plain_http(fresh_app, directory_site):
    """A static host that rewrites a mounted directory without redirecting the
    browser still installs, over plain HTTP, and both chart types download."""
    app = fresh_app
    site = directory_site.replace("127.0.0.1", "kincade.test")
    entry = "/tools/kincade?from=blog#example"
    with app.page.expect_response(
        lambda response: (
            response.url.startswith(site + "/")
            and urlsplit(response.url).path.endswith(".whl")
        ),
        timeout=120000,
    ) as download:
        app.page.goto(site + entry)
    response = download.value
    manifest = json.loads(app.page.locator("#manifest").text_content())
    wheel = manifest["wheel"]
    assert (
        response.url == f"{site}/tools/kincade/{wheel['name']}?v={wheel['sha256'][:12]}"
    )
    assert response.status == 200
    assert hashlib.sha256(response.body()).hexdigest() == wheel["sha256"]
    assert app.page.evaluate("isSecureContext") is False
    expect(app.page.locator("#status")).to_have_text("Ready", timeout=120000)
    assert app.page.url == site + entry
    app.sample()
    pedigree = app.pdf()
    assert len(pedigree.pages) == 6
    assert "George WASHINGTON" in text(pedigree)
    assert len(embedded_fonts(pedigree)) == 4
    app.chart("fan")
    fan = app.pdf()
    assert len(fan.pages) == 1
    assert "George WASHINGTON" in text(fan)
    assert len(embedded_fonts(fan)) == 2
    assert not app.failed_requests, app.failed_requests
    assert not app.console_errors, app.console_errors


def test_integrity_failures(app):
    """A bad font hash falls back to built-in fonts; a corrupted wheel keeps failing
    on retry; an HTTP error on the wheel names the status and the site owner; a
    clean start afterwards recovers fully."""
    app.start("font-hash")
    assert app.replies("ready")[-1]["fonts"] == "base14"
    app.sample()
    expect(app.page.locator("#pdf-summary")).to_contain_text("Built-in fonts used")
    assert not embedded_fonts(app.pdf())
    assert app.download().endswith(".pdf")

    app.start("wheel-bad", ready=False)
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)
    expect(app.page.locator("#status")).to_contain_text(
        "Installing Kincade failed (this site)"
    )
    expect(app.page.locator("#status")).to_contain_text("Reload the page")
    with app.page.expect_navigation():
        app.page.locator("#retry").click()
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)

    whl_pattern = app.site + "/**/*.whl?*"
    app.page.route(
        whl_pattern,
        lambda route: route.fulfill(
            status=403, content_type="application/xml", body="<Code>AccessDenied</Code>"
        ),
    )
    app.start("clean", ready=False)
    manifest = json.loads(app.page.locator("#manifest").text_content())
    wheel = manifest["wheel"]
    url = f"{app.site}/clean/{wheel['name']}?v={wheel['sha256'][:12]}"
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)
    expect(app.page.locator("#status")).to_contain_text(f"HTTP 403 for {url}")
    expect(app.page.locator("#status")).to_contain_text("site owner")
    app.page.unroute(whl_pattern)

    app.start()
    app.sample()
    assert len(embedded_fonts(app.pdf())) == 4


def test_the_page_in_french_then_other_languages(app):
    """The page bootstraps in French from the address, follows the sample into
    both chart types, and the page and chart languages can be changed apart."""
    app.start()
    for selector in ("#page-lang", "#chart-lang"):
        options = app.page.locator(f"{selector} option")
        assert options.all_text_contents() == [
            "Deutsch",
            "English",
            "Español",
            "Français",
            "Italiano",
        ], selector
        assert [
            options.nth(index).get_attribute("value")
            for index in range(options.count())
        ] == ["de", "en", "es", "fr", "it"], selector

    app.start(lang="fr")
    page = app.page
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    assert page.title() == "Kincade — Arbres généalogiques"
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
    expect(page.locator("#pdf-summary")).to_contain_text(
        "5 tableaux, 1 page d’index, 6 pages"
    )
    assert app.sent("render")[-1]["settings"]["lang"] == "fr"
    assert "Arbre d’ascendance — George WASHINGTON" in text(app.pdf())
    app.chart("fan")
    expect(page.locator("#pdf-summary")).to_contain_text(
        "arbre en éventail, 6 générations, 30 personnes"
    )

    before = len(app.replies("rendered"))
    page.locator("#page-lang").select_option("it")
    app.wait_render(before)
    app.pdf_ready()
    expect(page.locator("html")).to_have_attribute("lang", "it")
    expect(page.locator("#tree-heading")).to_have_text("Albero genealogico")
    assert re.search(r"[?&]lang=it\b", page.url)
    assert app.sent("render")[-1]["settings"]["lang"] == "it"

    page.locator("#more-options summary").click()
    app.change("#chart-lang", "de")
    assert "Fächerahnentafel — George WASHINGTON" in text(app.pdf())

    sent = len(app.sent("render"))
    page.locator("#page-lang").select_option("es")
    expect(page.locator("#tree-heading")).to_have_text("Árbol familiar")
    expect(page.locator("#chart-lang")).to_have_value("de")
    assert len(app.sent("render")) == sent, "the chart language stays de"

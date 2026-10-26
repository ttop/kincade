"""Browser acceptance uses historical and synthetic trees with real Pyodide PDFs."""

import re

import pytest
from playwright.sync_api import expect
from pypdf.generic import ContentStream

from conftest import content, embedded_fonts, text


def test_bootstrap_sample_defaults_and_download(app):
    app.start()
    expect(app.page.locator("#option-controls")).to_be_enabled()
    expect(app.page.locator("#search")).to_be_disabled()
    expect(app.page.locator("#more-options")).not_to_have_attribute("open", "")
    app.sample()
    expect(app.page.locator("#file-summary")).to_contain_text("47 people")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    expect(app.page.locator("#pdf-summary")).to_contain_text(
        "5 charts, 1 index page, 6 pages"
    )
    pdf = app.pdf()
    assert len(pdf.pages) == 6
    assert pdf.metadata.title == "Cascading Pedigree — George WASHINGTON"
    assert pdf.metadata.title in text(pdf)
    assert len(embedded_fonts(pdf)) == 4
    expect(app.page.locator("#pdf-summary")).not_to_contain_text("Built-in fonts used")
    assert app.download() == "George Washington cascading pedigree.pdf"
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


UNIQUE_NAMES = b"""0 @A1@ INDI
1 NAME Ely /Synthetic/
0 @B1@ INDI
1 NAME Bea /Synthetic/
0 @C1@ INDI
1 NAME Cam /Synthetic/
0 TRLR
"""


@pytest.mark.parametrize("selection", ["click", "search-enter", "row-enter"])
def test_unique_three_letter_search_requires_affirmative_selection(app, selection):
    app.start()
    app.upload(UNIQUE_NAMES)
    search = app.page.locator("#search")
    search.fill("Ely")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#results button")).to_have_count(1)
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    assert not app.sent("render")
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert app.page.locator("#download-pdf").get_attribute("href") is None
    expect(app.page.locator("#root-choices")).to_be_visible()
    expect(search).to_be_focused()

    if selection == "click":
        app.page.locator('#results button[data-record-id="A1"]').click()
    elif selection == "search-enter":
        search.press("Enter")
    else:
        search.press("ArrowDown")
        expect(search).to_be_focused()
        expect(app.page.locator("#results button")).to_have_attribute(
            "aria-selected", "true"
        )
        app.page.keyboard.press("Enter")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text("Root: A1, Ely SYNTHETIC")
    assert len(app.sent("render")) == 1
    assert app.sent("render")[0]["rootId"] == "A1"
    expect(app.page.locator("#root-choices")).to_be_hidden()
    expect(search).to_be_focused()
    assert "Ely" in text(app.pdf())


def test_unique_search_retains_selected_root_and_pdf_until_enter(app):
    app.start()
    app.upload(UNIQUE_NAMES)
    app.select("A1")
    url = app.page.locator("#download-pdf").get_attribute("href")
    renders = len(app.sent("render"))
    search = app.page.locator("#search")
    search.fill("Bea")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#results button")).to_have_count(1)
    expect(app.page.locator("#root-summary")).to_have_text("Root: A1, Ely SYNTHETIC")
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    assert len(app.sent("render")) == renders
    expect(app.page.locator("#root-choices")).to_be_visible()
    expect(search).to_be_focused()
    search.press("Enter")
    app.wait_render(renders)
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text("Root: B1, Bea SYNTHETIC")
    assert len(app.sent("render")) == renders + 1
    assert app.page.locator("#download-pdf").get_attribute("href") != url
    assert "Bea" in text(app.pdf())


def test_enter_flushes_pending_unique_search_and_selects_current_row_once(app):
    app.start()
    app.upload(UNIQUE_NAMES)
    app.page.clock.install(time="2026-10-13T12:00:00Z")
    app.page.clock.pause_at("2026-10-13T12:00:01Z")
    app.hold("results")
    searches = len(app.sent("search"))
    search = app.page.locator("#search")
    search.fill("Bea")
    assert len(app.sent("search")) == searches
    search.press("Enter")
    app.held("results")
    assert len(app.sent("search")) == searches + 1
    assert app.sent("search")[-1]["text"] == "Bea"
    assert not app.sent("render")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    app.release("results")
    app.page.clock.run_for(150)
    app.page.clock.resume()
    app.pdf_ready()
    assert len(app.sent("search")) == searches + 1
    assert len(app.sent("render")) == 1
    assert app.sent("render")[0]["rootId"] == "B1"
    expect(app.page.locator("#root-summary")).to_have_text("Root: B1, Bea SYNTHETIC")


@pytest.mark.parametrize("source", ["upload", "drop"])
def test_single_person_file_requires_affirmative_selection(app, source):
    app.start()
    if source == "upload":
        app.upload(b"0 @D1@ INDI\n1 NAME Drop /Synthetic/\n0 TRLR", "single.ged")
    else:
        app.page.evaluate("""() => {
          const d = new DataTransfer();
          d.items.add(new File(['0 @D1@ INDI\\n1 NAME Drop /Synthetic/\\n0 TRLR'], 'single.ged'));
          document.querySelector('#drop-zone').dispatchEvent(
            new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: d}));
        }""")
    expect(app.page.locator("#file-summary")).to_have_text("single.ged: 1 person")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    assert not app.sent("render")
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    expect(app.page.locator("#root-choices")).to_be_hidden()
    app.select("D1")
    assert len(app.sent("render")) == 1
    expect(app.page.locator("#root-summary")).to_have_text("Root: D1, Drop SYNTHETIC")


def test_upload_drop_search_keyboard_and_explicit_selection(app):
    app.start()
    app.upload()
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    search = app.page.locator("#search")
    search.focus()
    expect(app.page.locator("#result-summary")).to_have_text("28 matches")
    search.fill("mcclure")
    expect(app.page.locator("#result-summary")).to_have_text("3 matches")
    search.press("Enter")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_contain_text("McCLURE")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    search.fill("not-a-person")
    expect(app.page.locator("#result-summary")).to_have_text("0 matches")
    search.fill("")
    expect(app.page.locator("#result-summary")).to_have_text("28 matches")
    search.press("ArrowDown")
    expect(search).to_be_focused()
    app.page.keyboard.press("ArrowDown")
    app.page.keyboard.press("Enter")
    expect(app.page.locator("#root-summary")).to_contain_text("I2,")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    app.upload()
    search.fill("I1")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    search.press("Enter")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text("Root: I1, Jane ASHFORD")
    app.page.evaluate("""() => {
      const d = new DataTransfer();
      d.items.add(new File(['0 @D1@ INDI\\n1 NAME Drop /Synthetic/\\n0 TRLR'], 'drop.ged'));
      const z = document.querySelector('#drop-zone');
      z.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: d}));
      if (!z.classList.contains('dragging')) throw Error('No drag highlight');
      z.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: d}));
    }""")
    expect(app.page.locator("#file-summary")).to_have_text("drop.ged: 1 person")
    expect(app.page.locator("#drop-zone")).not_to_have_class(re.compile(".*dragging.*"))
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    app.select("D1")
    expect(app.page.locator("#root-summary")).to_contain_text("D1, Drop SYNTHETIC")


def test_search_limit_literal_names_and_late_closed_results(app):
    app.start()
    data = "\n".join(
        f"0 @I{i}@ INDI\n1 NAME Person{i} /Synthetic/" for i in range(1, 206)
    ).encode()
    app.upload(data)
    app.page.locator("#search").focus()
    expect(app.page.locator("#result-summary")).to_have_text("200 of 205 shown")
    expect(app.page.locator("#results button")).to_have_count(200)
    app.hold("results")
    app.page.locator("#search").fill("Person2")
    app.held("results")
    app.page.locator("#search").press("Escape")
    app.release("results")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    app.page.locator("#search").focus()
    app.page.locator("#sample").focus()
    expect(app.page.locator("#root-choices")).to_be_hidden()
    app.upload(b"0 @X1@ INDI\n1 NAME <img src=x onerror=alert(1)> /Literal/\n0 TRLR")
    app.select("X1")
    expect(app.page.locator("#root-summary")).to_contain_text(
        "<img src=x onerror=alert(1)>"
    )
    assert app.page.locator("#root-controls img").count() == 0
    assert "<img src=x onerror=alert(1)>" in text(app.pdf())


@pytest.mark.parametrize("generations", range(2, 8))
def test_fan_generations_and_every_empty_position_outlined(app, generations):
    app.start()
    app.upload(b"0 @I1@ INDI\n1 NAME Jane /Ashford/\n0 TRLR")
    app.select()
    app.chart("fan")
    if generations != 6:
        app.change("#fan-generations", generations)
    pdf = app.pdf()
    expect(app.page.locator("#pdf-summary")).to_contain_text(
        f"fan chart, {generations} generations, 1 person"
    )
    # Distinct dashed, closed and stroked paths exist for EVERY missing ancestor.
    blanks = re.findall(rb"\[2 2\] 0 d\s+(.*?)\bh\s+S", content(pdf), re.DOTALL)
    assert len(blanks) == len(set(blanks)) == 2**generations - 2
    assert "Jane ASHFORD" in text(pdf)
    assert app.download() == "Jane Ashford fan chart.pdf"


@pytest.mark.parametrize(
    "paper,size",
    [
        ("letter", (792, 612)),
        ("a4", (841.8898, 595.2756)),
        ("tabloid", (1224, 792)),
        ("a3", (1190.551, 841.8898)),
    ],
)
@pytest.mark.parametrize("ink", ["color", "grayscale", "bw"])
def test_fan_papers_and_inks_real_pdf(app, paper, size, ink):
    app.start()
    app.sample()
    app.chart("fan")
    if paper != "letter":
        app.change("#fan-paper", paper)
    initial = content(app.pdf())
    if ink != "color":
        app.change("#ink", ink)
        assert content(app.pdf()) != initial
    pdf = app.pdf()
    assert len(pdf.pages) == 1
    assert tuple(float(x) for x in pdf.pages[0].mediabox[2:]) == pytest.approx(
        size, abs=0.01
    )
    assert app.sent("render")[-1]["settings"]["ink"] == ink
    operations = ContentStream(pdf.pages[0].get_contents(), pdf).operations
    fills = [tuple(float(x) for x in args) for args, op in operations if op == b"rg"]
    strokes = [tuple(float(x) for x in args) for args, op in operations if op == b"RG"]
    if ink == "color":
        assert any(len(set(rgb)) > 1 for rgb in fills)
    elif ink == "grayscale":
        assert all(len(set(rgb)) == 1 for rgb in fills)  # planning supplies gray fills
        assert (0.25, 0.25, 0.25) in strokes  # drawing uses grayscale separators
    else:
        assert not any(op in {b"f", b"f*", b"B", b"B*"} for _, op in operations)
        assert (0.0, 0.0, 0.0) in strokes


def test_preview_layout_resize_and_color_schemes(app):
    app.start()
    app.sample()
    page = app.page
    assert page.locator("#pdf-section").bounding_box()["y"] < 500
    assert (
        page.locator("#pdf-section").bounding_box()["x"]
        > page.locator(".controls-rail").bounding_box()["x"]
    )
    frame = page.locator("#pdf-frame")
    src = frame.get_attribute("src")
    assert src.endswith("#view=FitH&navpanes=0")
    box = frame.bounding_box()
    app.assert_one_page()
    app.generations(1)
    assert len(app.pdf().pages) == 2  # chart + index; one paper page remains visible
    assert frame.bounding_box()["height"] == box["height"]
    src = frame.get_attribute("src")
    page.set_viewport_size({"width": 1100, "height": 1000})
    page.wait_for_function(
        "h => document.querySelector('#pdf-frame').getBoundingClientRect().height < h",
        arg=box["height"],
    )
    app.assert_one_page()
    assert frame.get_attribute("src") == src
    page.set_viewport_size({"width": 767, "height": 1000})
    expect(page.locator("#preview")).to_be_hidden()
    expect(page.locator("#open-pdf")).to_be_visible()
    assert frame.get_attribute("src") is None
    page.set_viewport_size({"width": 768, "height": 1000})
    expect(page.locator("#preview")).to_be_visible()
    page.set_viewport_size({"width": 320, "height": 1000})
    for scheme in ["dark", "light"]:
        page.emulate_media(color_scheme=scheme)
        assert page.evaluate("document.documentElement.scrollWidth") == 320
        assert page.locator("main").bounding_box()["x"] == 16
        assert page.locator("main").bounding_box()["width"] == 288
        assert page.locator("body").evaluate(
            "e => getComputedStyle(e).color !== getComputedStyle(e).backgroundColor"
        )
    assert app.download().endswith(".pdf")


@pytest.mark.parametrize(
    "selector,value",
    [
        ("#large-print", True),
        ("#exclude-private", True),
        ("#empty-boxes", True),
        ("#show-ids", True),
        ("#shadow", True),
        ("#page-numbers", False),
        ("#index", False),
    ],
)
def test_pedigree_options_change_real_drawing(app, selector, value):
    app.start()
    app.upload()
    app.select()
    app.page.locator("#more-options summary").click()
    before = content(app.pdf())
    app.change(selector, value)
    after = app.pdf()
    assert content(after) != before
    if selector == "#index":
        assert len(after.pages) == 6
    elif selector == "#show-ids":
        assert "I1" in text(after)
    elif selector == "#exclude-private":
        assert "14 Feb 1980" not in text(after)


SPECIAL = b"""0 HEAD
0 @I1@ INDI
1 NAME Jane /Ashford/
1 CHR
2 DATE 1 JAN 1980
2 PLAC A Very Long Imaginary Neighborhood, A Very Long Imaginary Municipality, Fiction County, Fiction State, Fiction Country
1 BURI
2 DATE 1 JAN 2020
1 FAMC @F1@
1 FAMC @F2@
2 PEDI adopted
0 @I2@ INDI
1 NAME Birth /Synthetic/
1 DEAT
2 DATE 1980
0 @I3@ INDI
1 NAME Adoptive /Synthetic/
1 DEAT
2 DATE 1980
0 @F1@ FAM
1 HUSB @I2@
1 CHIL @I1@
0 @F2@ FAM
1 HUSB @I3@
1 CHIL @I1@
0 TRLR
"""


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
def test_adoptive_and_standin_options_have_visible_effects(app, chart):
    app.start()
    app.upload(SPECIAL)
    app.select()
    if chart == "fan":
        app.chart("fan")
    app.page.locator("#more-options summary").click()
    assert "Birth" in text(app.pdf())
    app.change("#adoptive-parents", True)
    assert "Adoptive" in text(app.pdf())
    assert "Birth" not in text(app.pdf())
    before = text(app.pdf())
    app.change("#event-standins", False)
    assert text(app.pdf()) != before
    assert "1980" in before  # christening used as a birth stand-in
    if chart == "pedigree":
        before = content(app.pdf())
        app.change("#shorten-places", False)
        # Stand-ins are currently disabled, so restore them before checking places.
        app.change("#event-standins", True)
        expanded = text(app.pdf())
        app.change("#shorten-places", True)
        assert text(app.pdf()) != expanded
        assert content(app.pdf()) != before
    assert app.download() == (
        "Jane Ashford fan chart.pdf"
        if chart == "fan"
        else "Jane Ashford cascading pedigree.pdf"
    )


def test_titles_footer_debounce_collapsed_retention_and_per_chart_settings(app):
    app.start()
    app.sample()
    page = app.page
    page.locator("#more-options summary").click()
    # Keep browser-command overhead outside the exact 400ms debounce boundary.
    page.clock.install(time="2026-10-13T12:00:00Z")
    page.clock.pause_at("2026-10-13T12:00:01Z")
    before = len(app.sent("render"))
    page.locator("#pedigree-title").fill("Custom pedigree")
    page.clock.run_for(399)
    assert len(app.sent("render")) == before
    page.clock.run_for(1)
    page.clock.resume()
    app.pdf_ready()
    page.wait_for_function(
        "n => acceptance.replies.filter(x => x.type === 'rendered').length > n",
        arg=before,
    )
    assert "Custom pedigree" in text(app.pdf())
    app.change("#footer", "Synthetic footer")
    app.change("#no-footer", True)
    expect(page.locator("#footer")).to_be_disabled()
    expect(page.locator("#footer")).to_have_value("Synthetic footer")
    assert "Synthetic footer" not in text(app.pdf())
    app.change("#no-footer", False)
    assert "Synthetic footer" in text(app.pdf())
    app.generations(3)
    page.locator("#more-options summary").click()
    app.change("#pedigree-paper", "a4")
    assert "Custom pedigree" in text(app.pdf())
    app.chart("fan")
    expect(page.locator("#pedigree-generations")).to_be_hidden()
    expect(page.locator("#ink")).to_be_visible()
    page.locator("#more-options summary").click()
    app.change("#fan-title", "Custom fan")
    app.change("#fan-generations", 4)
    app.change("#fan-paper", "a3")
    app.change("#exclude-private", True)
    page.locator("#more-options summary").click()
    app.change("#fan-paper", "tabloid")
    assert "Custom fan" in text(app.pdf())
    assert "Synthetic footer" in text(app.pdf())
    app.chart("pedigree")
    expect(page.locator("#pedigree-generations")).to_have_value("3")
    expect(page.locator("#pedigree-paper")).to_have_value("a4")
    expect(page.locator("#exclude-private")).to_be_checked()
    assert "Custom pedigree" in text(app.pdf())
    app.chart("fan")
    expect(page.locator("#fan-generations")).to_have_value("4")
    expect(page.locator("#fan-paper")).to_have_value("tabloid")
    assert "Custom fan" in text(app.pdf())


@pytest.mark.parametrize("variant", ["font-blocked", "font-hash"])
def test_all_or_nothing_font_fallback(app, variant):
    app.start(variant)
    assert app.replies("ready")[-1]["fonts"] == "base14"
    app.sample()
    expect(app.page.locator("#pdf-summary")).to_contain_text("Built-in fonts used")
    assert not embedded_fonts(app.pdf())
    assert app.download().endswith(".pdf")


def test_wheel_integrity_failure_retry_and_clean_recovery(app):
    app.start("wheel-bad", ready=False)
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)
    expect(app.page.locator("#status")).to_contain_text(
        "Installing Kincade failed (this site)"
    )
    expect(app.page.locator("#status")).to_contain_text("Reload the page")
    with app.page.expect_navigation():
        app.page.locator("#retry").click()
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)
    app.start()
    app.sample()
    assert len(embedded_fonts(app.pdf())) == 4


@pytest.mark.parametrize("insecure", [False, True])
def test_csp_and_insecure_http_real_bootstrap_both_charts(app, insecure):
    app.start("clean" if insecure else "csp", insecure=insecure)
    assert app.page.evaluate("isSecureContext") is (not insecure)
    app.sample()
    assert len(app.pdf().pages) == 6
    assert app.download().endswith("cascading pedigree.pdf")
    app.chart("fan")
    assert len(app.pdf().pages) == 1
    assert app.download().endswith("fan chart.pdf")
    assert not app.page.evaluate("acceptance.violations")


@pytest.mark.parametrize(
    "paper,size", [("letter", (612, 792)), ("a4", (595.2756, 841.8898))]
)
@pytest.mark.parametrize("large_print", [False, True])
@pytest.mark.parametrize("index", [False, True])
def test_pedigree_paper_print_index_and_one_page_preview(
    app, paper, size, large_print, index
):
    app.start()
    app.sample()
    app.page.locator("#more-options summary").click()
    if paper != "letter":
        app.change("#pedigree-paper", paper)
    if large_print:
        app.change("#large-print", True)
    if not index:
        app.change("#index", False)
    pdf = app.pdf()
    assert tuple(float(x) for x in pdf.pages[0].mediabox[2:]) == pytest.approx(
        size, abs=0.01
    )
    app.assert_one_page()
    assert len(pdf.pages) > 1


def test_every_default_mapping_and_reset_titles_footers(app):
    app.start()
    app.sample()
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
    expect(app.page.locator("#preserve-case")).to_be_checked()
    app.change("#preserve-case", False)
    assert app.sent("render")[-1]["settings"]["preserve_case"] is True
    app.change("#preserve-case", True)
    expect(app.page.locator("#preserve-case")).to_be_checked()
    assert app.sent("render")[-1]["settings"]["preserve_case"] is False
    app.change("#pedigree-title", "Custom title")
    app.change("#footer", "Custom footer")
    app.change("#pedigree-title", "")
    app.change("#footer", "")
    assert "Cascading Pedigree" in text(app.pdf())
    assert "using Kincade" in text(app.pdf())
    assert "Custom title" not in text(app.pdf())
    app.chart("fan")
    assert app.sent("render")[-1]["settings"] == {
        "generations": 6,
        "paper": "letter",
        "ink": "color",
        "exclude_private": False,
        "adoptive_parents": False,
        "event_standins": True,
        "preserve_case": False,
        "title": None,
        "footer": None,
        "lang": "en",
    }
    app.change("#footer", "Shared footer")
    app.change("#no-footer", True)
    expect(app.page.locator("#footer")).to_be_disabled()
    expect(app.page.locator("#footer")).to_have_value("Shared footer")
    assert "Shared footer" not in text(app.pdf())
    app.change("#no-footer", False)
    assert "Shared footer" in text(app.pdf())


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
@pytest.mark.parametrize("preserve", [False, True])
def test_privacy_conceals_names_in_pdf_metadata_and_downloads(app, chart, preserve):
    app.start()
    app.upload()
    app.select()
    if chart == "fan":
        app.chart(chart)
    if preserve:
        app.page.locator("#more-options summary").click()
        app.change("#preserve-case", False)
    public_pdf = app.pdf()
    assert "Jane ASHFORD" in text(public_pdf)
    app.change("#exclude-private", True)
    private_pdf = app.pdf()
    shared_text = text(private_pdf) + str(private_pdf.metadata)
    assert "Jane ASHFORD" not in shared_text
    assert "mary mcclure" not in shared_text.casefold()
    birth = "1980–" if chart == "fan" else "14 Feb 1980"
    assert birth not in text(private_pdf)
    assert "Living" in text(private_pdf)
    suffix = "fan chart" if chart == "fan" else "cascading pedigree"
    assert app.download() == f"Living {suffix}.pdf"
    # Local root selection stays available while exported identities are hidden.
    expect(app.page.locator("#search")).to_have_value("Jane ASHFORD")
    expect(
        app.page.locator('#results button[data-record-id="I1"] .years')
    ).to_have_text("")
    app.change("#exclude-private", False)
    assert "Jane ASHFORD" in text(app.pdf())
    assert app.download() == f"Jane ASHFORD {suffix}.pdf"


def test_fan_end_arc_labels_keep_names_dates_and_clockwise_frames(app):
    import math

    # An invented four-generation tree puts both end labels and their neighbors
    # in ring 3; the fifth generation remains outlined for writing in by hand.
    names = {
        8: "Albert /Doe/",
        9: "Jane /Doe/",
        14: "Peter /MALSH/",
        15: "Catherine /Doe/",
    }
    records = []
    for slot in range(1, 16):
        records.extend(
            [
                f"0 @I{slot}@ INDI",
                f"1 NAME {names.get(slot, f'Person{slot} /Synthetic/')}",
            ]
        )
        if slot in names:
            records.extend(["1 BIRT", "2 DATE 1820", "1 DEAT", "2 DATE 1891"])
        if slot < 8:
            records.append(f"1 FAMC @F{slot}@")
            records.extend(
                [
                    f"0 @F{slot}@ FAM",
                    f"1 HUSB @I{2 * slot}@",
                    f"1 WIFE @I{2 * slot + 1}@",
                    f"1 CHIL @I{slot}@",
                ]
            )
    app.start()
    app.upload(("\n".join(records) + "\n0 TRLR").encode(), "arc-labels.ged")
    app.select()
    app.chart("fan")
    app.change("#fan-generations", 5)
    pdf = app.pdf()  # real Worker/Pyodide rendering and product download
    assert len(pdf.pages) == 1
    assert tuple(float(x) for x in pdf.pages[0].mediabox[2:]) == (792, 612)
    assert len(embedded_fonts(pdf)) == 2
    body = text(pdf)
    assert body.count("1820–1891") == 4
    operations = ContentStream(pdf.pages[0].get_contents(), pdf).operations
    # The center disc is the first outline. Its four cubic endpoints give the
    # emitted center and scale, independent of text_direction or font fitting.
    start = next(i for i, (_, op) in enumerate(operations) if op == b"m")
    curves = operations[start + 1 : start + 5]
    assert all(op == b"c" for _, op in curves)
    xs = [float(args[-2]) for args, _ in curves]
    ys = [float(args[-1]) for args, _ in curves]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    units = (max(xs) - min(xs)) / 250
    objects, runs, matrix = [], [], None
    for args, op in operations:
        if op == b"BT":
            runs = []
        elif op == b"Tm":
            matrix = tuple(float(x) for x in args)
        elif op == b"Tj":
            runs.append((str(args[0]), matrix))
        elif op == b"ET" and runs:
            objects.append(runs)
    # Joined Tj objects retain the literal labels; extract_text may insert a
    # heuristic newline midway through a curved name such as Peter MALSH.
    for name in ("Albert DOE", "Jane DOE", "Peter MALSH", "Catherine DOE"):
        index = next(
            i for i, obj in enumerate(objects) if "".join(ch for ch, _ in obj) == name
        )
        name_runs, year_runs = objects[index : index + 2]
        assert len(year_runs) == 9  # the complete date follows its name
        radii = []
        for obj in (name_runs, year_runs):
            previous = None
            for ch, (a, b, c, d, x, y) in obj:
                assert len(ch) == 1  # the labels retain actual curved placement
                dx, dy = x - cx, y - cy
                radius = math.hypot(dx, dy)
                assert 300 * units < radius < 425 * units
                assert a * dy - b * dx > 0  # baseline advances clockwise
                assert c * dx + d * dy > 0  # glyph tops face outward
                if previous is not None:
                    assert previous[0] * dy - previous[1] * dx < 0
                previous = (dx, dy)
            radii.append(math.hypot(obj[0][1][4] - cx, obj[0][1][5] - cy))
        assert radii[0] > radii[1]  # names remain outside dates


def test_uppercase_last_name_checkbox_is_shared_by_both_chart_types(app):
    app.start()
    app.upload(SPECIAL)
    app.select()
    app.page.locator("#more-options summary").click()
    expect(app.page.locator("#preserve-case")).to_be_checked()
    expect(app.page.get_by_label("Last name UPPERCASE", exact=True)).to_be_checked()
    assert app.sent("render")[-1]["settings"]["preserve_case"] is False
    assert "Jane ASHFORD" in text(app.pdf())
    app.change("#preserve-case", False)
    pedigree = app.pdf()
    assert "Jane Ashford" in text(pedigree)
    assert "Ashford, Jane" in text(pedigree)
    assert app.download() == "Jane Ashford cascading pedigree.pdf"
    app.chart("fan")
    expect(app.page.locator("#preserve-case")).not_to_be_checked()
    preserved_fan = app.pdf()
    assert "Jane Ashford" in text(preserved_fan)
    assert "Jane Ashford" in preserved_fan.metadata.title
    assert app.download() == "Jane Ashford fan chart.pdf"
    app.change("#preserve-case", True)
    expect(app.page.locator("#preserve-case")).to_be_checked()
    uppercase_fan = app.pdf()
    assert "Jane ASHFORD" in text(uppercase_fan)
    assert "Jane ASHFORD" in uppercase_fan.metadata.title
    assert app.download() == "Jane Ashford fan chart.pdf"
    app.chart("pedigree")
    expect(app.page.locator("#preserve-case")).to_be_checked()
    assert "Jane ASHFORD" in text(app.pdf())

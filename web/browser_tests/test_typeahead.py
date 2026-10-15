"""Connected combobox behavior in the real page and Python worker."""

import pytest
from playwright.sync_api import expect

from conftest import CACHE

DUPLICATES = b"""0 @A1@ INDI
1 NAME Alex /Synthetic/
1 BIRT
2 DATE 1 JAN 1880
1 DEAT
2 DATE 1 JAN 1950
0 @B1@ INDI
1 NAME Alex /Synthetic/
1 BIRT
2 DATE 1 JAN 1920
1 DEAT
2 DATE 1 JAN 1990
0 @C1@ INDI
1 NAME Bea /Synthetic/
0 TRLR
"""


@pytest.mark.parametrize("width", [1440, 320])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_popup_attaches_to_input_without_moving_options_or_chart(app, width, theme):
    app.page.set_viewport_size({"width": width, "height": 1000})
    app.page.emulate_media(color_scheme=theme)
    app.start()
    app.upload(DUPLICATES)
    search = app.page.locator("#search")
    popup = app.page.locator("#root-choices")
    options = app.page.locator('[aria-labelledby="options-heading"]')
    chart = app.page.locator(".chart-area")
    before = [options.bounding_box(), chart.bounding_box()]
    CACHE.mkdir(parents=True, exist_ok=True)
    app.page.screenshot(path=str(CACHE / f"typeahead-empty-{width}-{theme}.png"))
    app.page.get_by_role("button", name="Open person list", exact=True).click()
    expect(search).to_be_focused()
    expect(popup).to_be_visible()
    field, choices = search.bounding_box(), popup.bounding_box()
    assert abs(choices["y"] - field["y"] - field["height"]) <= 1
    assert abs(choices["x"] - field["x"]) <= 1
    assert abs(choices["width"] - field["width"]) <= 1
    assert [options.bounding_box(), chart.bounding_box()] == before
    assert app.page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    CACHE.mkdir(parents=True, exist_ok=True)
    app.page.screenshot(path=str(CACHE / f"typeahead-open-{width}-{theme}.png"))
    app.page.locator('#results button[data-record-id="B1"]').click()
    app.pdf_ready()
    expect(search).to_have_value("Alex SYNTHETIC")
    app.page.screenshot(path=str(CACHE / f"typeahead-selected-{width}-{theme}.png"))


def test_combobox_navigates_duplicate_names_with_input_focus_and_explicit_enter(app):
    app.start()
    app.upload(DUPLICATES)
    search = app.page.get_by_role("combobox", name="Search by name or record ID")
    search.click()
    expect(search).to_have_attribute("aria-controls", "results")
    expect(search).to_have_attribute("aria-autocomplete", "list")
    expect(app.page.get_by_role("listbox", name="Matching people")).to_be_visible()
    search.fill("Alex")
    expect(app.page.locator("#result-summary")).to_have_text("2 matches")
    rows = app.page.get_by_role("listbox").get_by_role("option")
    expect(rows.nth(0)).to_contain_text("A1")
    expect(rows.nth(0)).to_contain_text("1880-1950")
    expect(rows.nth(1)).to_contain_text("B1")
    expect(rows.nth(1)).to_contain_text("1920-1990")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)
    assert search.get_attribute("aria-activedescendant") is None
    search.press("ArrowDown")
    expect(search).to_be_focused()
    expect(search).to_have_attribute(
        "aria-activedescendant", rows.nth(0).get_attribute("id")
    )
    search.press("ArrowDown")
    expect(rows.nth(1)).to_have_attribute("aria-selected", "true")
    search.press("ArrowUp")
    expect(rows.nth(0)).to_have_attribute("aria-selected", "true")
    search.press("ArrowDown")
    assert not app.sent("render")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    search.press("Enter")
    app.pdf_ready()
    assert app.sent("render")[-1]["rootId"] == "B1"
    expect(search).to_have_value("Alex SYNTHETIC")
    expect(search).to_be_focused()
    expect(search).to_have_attribute("aria-expanded", "false")
    assert search.get_attribute("aria-activedescendant") is None
    expect(app.page.locator("#root-summary")).to_have_text("Root: B1, Alex SYNTHETIC")
    # Clicking the committed name makes it easy to replace with a fresh query.
    search.click()
    assert search.evaluate("e => e.selectionEnd - e.selectionStart") == len(
        "Alex SYNTHETIC"
    )
    search.fill("C1")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.get_by_role("listbox").get_by_role("option")).to_contain_text(
        "Bea SYNTHETIC"
    )
    assert len(app.sent("render")) == 1


@pytest.mark.parametrize("dismiss", ["escape", "tab", "outside"])
def test_dismissal_does_not_commit_highlight_or_draft_query(app, dismiss):
    app.start()
    app.sample()
    search = app.page.locator("#search")
    url = app.page.locator("#download-pdf").get_attribute("href")
    renders = len(app.sent("render"))
    search.fill("ball")
    expect(app.page.locator("#result-summary")).to_have_text("3 matches")
    search.press("ArrowDown")
    expect(search).to_be_focused()
    if dismiss == "escape":
        search.press("Escape")
    elif dismiss == "tab":
        search.press("Tab")
        expect(
            app.page.get_by_role("button", name="Clear selected person")
        ).to_be_focused()
    else:
        app.page.locator("h1").click()
    expect(app.page.locator("#root-choices")).to_be_hidden()
    assert search.get_attribute("aria-activedescendant") is None
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    assert len(app.sent("render")) == renders
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    search.click()
    expect(app.page.locator("#root-choices")).to_be_visible()
    expect(search).to_have_value("George WASHINGTON")


def test_new_query_removes_stale_choices_and_enter_awaits_inflight_result(app):
    app.start()
    app.upload(DUPLICATES)
    app.page.clock.install(time="2026-10-13T12:00:00Z")
    app.page.clock.pause_at("2026-10-13T12:00:01Z")
    app.hold("results")
    search = app.page.locator("#search")
    search.click()
    search.press("ArrowDown")
    search.fill("Bea")
    expect(app.page.locator("#results button")).to_have_count(0)
    assert search.get_attribute("aria-activedescendant") is None
    search.press("ArrowDown")
    assert search.get_attribute("aria-activedescendant") is None
    app.page.clock.run_for(150)
    app.held("results")
    searches = len(app.sent("search"))
    search.press("Enter")
    assert not app.sent("render")
    assert len(app.sent("search")) == searches
    app.release("results")
    app.page.clock.resume()
    app.pdf_ready()
    assert app.sent("render")[-1]["rootId"] == "C1"
    expect(search).to_have_value("Bea SYNTHETIC")


def test_active_row_scrolls_into_view_and_composition_enter_does_not_pick(app):
    app.start()
    app.upload(
        "\n".join(
            f"0 @I{i}@ INDI\n1 NAME Person{i} /Synthetic/" for i in range(1, 50)
        ).encode()
    )
    search = app.page.locator("#search")
    search.click()
    search.press("ArrowUp")
    expect(search).to_be_focused()
    row = app.page.locator("#results button").last
    expect(row).to_have_attribute("aria-selected", "true")
    visible, active = app.page.locator("#results").bounding_box(), row.bounding_box()
    assert active["y"] >= visible["y"]
    assert active["y"] + active["height"] <= visible["y"] + visible["height"] + 1
    search.dispatch_event("keydown", {"key": "Enter", "isComposing": True})
    assert not app.sent("render")
    search.press("Enter")
    app.pdf_ready()
    assert app.sent("render")[-1]["rootId"] == "I49"


def test_popup_does_not_shift_the_root_card_or_options(app):
    app.start()
    app.upload(DUPLICATES)
    root = app.page.locator('[aria-labelledby="root-heading"]')
    options = app.page.locator('[aria-labelledby="options-heading"]')
    before = [root.bounding_box(), options.bounding_box()]
    app.page.locator("#search").click()
    assert [root.bounding_box(), options.bounding_box()] == before


def test_sample_committed_name_is_displayed_in_the_field(app):
    app.start()
    app.sample()
    expect(app.page.locator("#search")).to_have_value("George WASHINGTON")


def test_committed_query_enter_keeps_later_different_name_selection(app):
    app.start()
    app.upload(
        b"0 @A1@ INDI\n1 NAME Alex /Synthetic/\n0 @B1@ INDI\n1 NAME Bea /Synthetic/\n0 TRLR"
    )
    search = app.page.locator("#search")
    search.click()
    searches = len(app.sent("search"))
    app.page.locator('#results button[data-record-id="B1"]').click()
    app.pdf_ready()
    assert len(app.sent("search")) == searches
    renders = len(app.sent("render"))
    url = app.page.locator("#download-pdf").get_attribute("href")
    search.press("Enter")
    expect(app.page.locator("#root-summary")).to_have_text("Root: B1, Bea SYNTHETIC")
    expect(search).to_have_value("Bea SYNTHETIC")
    assert len(app.sent("render")) == renders
    assert len(app.sent("search")) == searches
    assert app.page.locator("#download-pdf").get_attribute("href") == url


def test_committed_query_reopen_navigation_uses_visible_name(app):
    app.start()
    app.upload(DUPLICATES)
    search = app.page.locator("#search")
    search.click()
    app.page.locator('#results button[data-record-id="C1"]').click()
    app.pdf_ready()
    search.click()
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#results button")).to_have_count(1)
    expect(app.page.locator("#results button")).to_contain_text("Bea SYNTHETIC")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)
    renders = len(app.sent("render"))
    search.press("ArrowDown")
    expect(search).to_be_focused()
    expect(app.page.locator('#results button[data-record-id="C1"]')).to_have_attribute(
        "aria-selected", "true"
    )
    assert len(app.sent("render")) == renders
    search.press("Enter")
    expect(app.page.locator("#root-summary")).to_have_text("Root: C1, Bea SYNTHETIC")


def test_committed_query_reopen_finds_duplicate_names_after_id_selection(app):
    app.start()
    app.upload(DUPLICATES)
    search = app.page.locator("#search")
    search.fill("B1")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    app.page.locator('#results button[data-record-id="B1"]').click()
    app.pdf_ready()
    renders = len(app.sent("render"))
    searches = len(app.sent("search"))
    search.press("ArrowDown")
    expect(app.page.locator("#result-summary")).to_have_text("2 matches")
    assert len(app.sent("search")) == searches + 1
    assert app.sent("search")[-1]["text"] == "Alex SYNTHETIC"
    rows = app.page.get_by_role("listbox").get_by_role("option")
    expect(rows.nth(0)).to_contain_text("A1")
    expect(rows.nth(1)).to_contain_text("B1")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)
    search.press("ArrowDown")
    expect(rows.nth(0)).to_have_attribute("aria-selected", "true")
    assert len(app.sent("render")) == renders
    assert len(app.sent("search")) == searches + 1
    search.press("Enter")
    expect(app.page.locator("#root-summary")).to_have_text("Root: A1, Alex SYNTHETIC")

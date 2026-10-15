"""Committed selection, discoverable controls, and explicit clear in the real worker."""

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("dismiss", ["escape", "tab", "outside"])
@pytest.mark.parametrize("query", ["", "ball"])
def test_dismissed_query_restores_selected_name_and_pdf(app, dismiss, query):
    app.start()
    app.sample()
    search = app.page.locator("#search")
    old_url = app.page.locator("#download-pdf").get_attribute("href")
    renders = len(app.sent("render"))
    search.fill(query)
    expect(search).to_have_value(query)
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    assert app.page.locator("#download-pdf").get_attribute("href") == old_url
    if dismiss == "outside":
        app.page.locator("h1").click()
    else:
        search.press("Escape" if dismiss == "escape" else "Tab")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    expect(search).to_have_value("George WASHINGTON")
    assert app.page.locator("#download-pdf").get_attribute("href") == old_url
    assert len(app.sent("render")) == renders
    search.click()
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#results button")).to_contain_text("George WASHINGTON")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)


def test_selected_clear_is_integrated_accessible_and_removes_preview(app):
    app.start()
    app.sample()
    search = app.page.locator("#search")
    clear = app.page.get_by_role("button", name="Clear selected person", exact=True)
    expect(clear).to_be_visible()
    expect(clear.locator('[data-icon="clear"]')).to_be_visible()
    expect(clear.locator('[data-icon="list"]')).to_be_hidden()
    expect(app.page.locator("#root-summary")).to_have_css("position", "absolute")
    assert search.get_attribute("aria-describedby") == "root-summary"
    assert search.get_attribute("type") == "text"
    field, control = search.bounding_box(), clear.bounding_box()
    assert control["x"] >= field["x"]
    assert control["x"] + control["width"] <= field["x"] + field["width"]
    assert control["height"] >= 32
    renders = len(app.sent("render"))
    clear.focus()
    clear.press("Enter")
    expect(search).to_have_value("")
    expect(search).to_be_focused()
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert app.page.locator("#download-pdf").get_attribute("href") is None
    assert app.page.locator("#pdf-frame").get_attribute("src") is None
    expect(app.page.locator("#pdf-summary")).to_have_text("")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    arrow = app.page.get_by_role("button", name="Open person list", exact=True)
    expect(arrow.locator('[data-icon="list"]')).to_be_visible()
    expect(arrow.locator('[data-icon="clear"]')).to_be_hidden()
    expect(app.page.locator("#root-choices")).to_be_hidden()
    assert len(app.sent("render")) == renders
    arrow.click()
    expect(search).to_be_focused()
    expect(app.page.locator("#root-choices")).to_be_visible()
    expect(app.page.locator("#result-summary")).to_have_text("47 matches")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)
    assert len(app.sent("render")) == renders
    app.page.locator('#results button[data-record-id="I2"]').click()
    app.pdf_ready()
    assert app.sent("render")[-1]["rootId"] == "I2"
    expect(search).not_to_have_value("")


def test_rootless_arrow_disabled_until_tree_then_opens_without_choosing(app):
    app.start()
    arrow = app.page.get_by_role("button", name="Open person list", exact=True)
    expect(arrow).to_be_disabled()
    app.upload()
    expect(arrow).to_be_enabled()
    arrow.click()
    expect(app.page.locator("#search")).to_be_focused()
    expect(app.page.locator("#root-choices")).to_be_visible()
    expect(app.page.locator("#result-summary")).to_have_text("28 matches")
    assert not app.sent("render")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")


@pytest.mark.parametrize("reselect_before_reply", [False, True])
def test_clear_rejects_delayed_pdf_and_next_selection_renders_normally(
    app, reselect_before_reply
):
    app.start()
    app.sample()
    app.hold("rendered")
    app.generations("2", wait=False)
    app.held("rendered")
    old = app.sent("render")[-1]
    renders = len(app.sent("render"))
    pdfs = app.page.evaluate("acceptance.pdfs.length")
    app.page.get_by_role("button", name="Clear selected person", exact=True).click()
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert len(app.sent("render")) == renders
    if reselect_before_reply:
        app.select("I2", wait=False)
        assert len(app.sent("render")) == renders
    app.release_one("rendered", old["seq"])
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert app.page.evaluate("acceptance.pdfs.length") == pdfs
    if not reselect_before_reply:
        expect(app.page.locator("#render-status")).to_be_hidden()
        assert len(app.sent("render")) == renders
        app.select("I2", wait=False)
    app.held("rendered")
    assert len(app.sent("render")) == renders + 1
    assert app.sent("render")[-1]["rootId"] == "I2"
    assert app.sent("render")[-1]["seq"] == old["seq"] + 1
    app.release("rendered")
    app.pdf_ready()
    assert app.page.evaluate("acceptance.pdfs.length") == pdfs + 1


def test_rootless_arrow_preserves_delayed_sample_intent(app):
    app.start()
    app.hold("results")
    app.page.locator("#sample").click()
    app.held("results")
    app.page.get_by_role("button", name="Open person list", exact=True).click()
    app.release("results")
    app.pdf_ready()
    expect(app.page.locator("#search")).to_have_value("George WASHINGTON")
    expect(app.page.locator("#root-choices")).to_be_hidden()
    assert len(app.sent("render")) == 1
    assert app.sent("render")[-1]["rootId"] == "I1"


def test_clear_cancels_delayed_manual_enter_and_sample_reselection(app):
    app.start()
    app.sample()
    app.hold("results")
    search = app.page.locator("#search")
    search.fill("ball")
    search.press("Enter")
    app.held("results")
    renders = len(app.sent("render"))
    app.page.get_by_role("button", name="Clear selected person", exact=True).click()
    app.release("results")
    expect(search).to_have_value("")
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert len(app.sent("render")) == renders
    # Option refresh must not reapply the successfully opened sample's I1 intent.
    app.page.locator("#exclude-private").check()
    app.page.get_by_role("button", name="Open person list", exact=True).click()
    expect(app.page.locator("#result-summary")).to_have_text("47 matches")
    assert len(app.sent("render")) == renders
    app.page.locator('#results button[data-record-id="I2"]').click()
    app.pdf_ready()
    assert app.sent("render")[-1]["rootId"] == "I2"


def test_clear_cancels_already_queued_sample_selection(app):
    app.start()
    app.upload()
    app.select("I1")
    app.hold("opened")
    app.page.locator("#sample").click()
    app.held("opened")
    renders = len(app.sent("render"))
    results = len(app.replies("results"))
    app.page.get_by_role("button", name="Clear selected person", exact=True).click()
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    app.release("opened")
    app.page.wait_for_function(
        "n => acceptance.replies.filter(x => x.type === 'results').length > n",
        arg=results,
    )
    expect(app.page.locator("#search")).to_have_value("")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    assert len(app.sent("render")) == renders
    app.select("I2")
    assert app.sent("render")[-1]["rootId"] == "I2"
    # Choosing a real file restores the visible example action after clear.
    app.upload()
    # A fresh example choice owns new I1 selection intent.
    app.hold("opened")
    app.page.locator("#sample").click()
    app.held("opened")
    app.release("opened")
    app.pdf_ready()
    expect(app.page.locator("#search")).to_have_value("George WASHINGTON")
    assert app.sent("render")[-1]["rootId"] == "I1"

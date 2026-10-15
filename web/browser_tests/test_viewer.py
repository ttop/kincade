"""Native Chromium PDF viewer and actual history lifecycle acceptance."""

from playwright.sync_api import expect


def test_native_pdf_viewer_page_navigation_and_zoom(app):
    app.start()
    app.sample()
    viewer = app.assert_one_page()
    toolbar = viewer.locator("viewer-toolbar")
    expect(toolbar).to_be_visible()
    page_number = viewer.locator("viewer-page-selector input")
    expect(page_number).to_have_value("1")
    page_number.fill("2")
    page_number.press("Enter")
    expect(page_number).to_have_value("2")
    viewer.wait_for_function(
        "() => document.querySelector('pdf-viewer').viewport_.getMostVisiblePage() === 1"
    )
    before = viewer.locator("pdf-viewer").evaluate("e => e.viewport_.getZoom()")
    viewer.get_by_role("button", name="Zoom in", exact=True).click()
    viewer.wait_for_function(
        "n => document.querySelector('pdf-viewer').viewport_.getZoom() > n", arg=before
    )
    # FitH's initial zoom can round to the next preset (e.g. 124.8% → 125%).
    # The viewport must change even when the displayed integer stays the same.
    after = viewer.locator("pdf-viewer").evaluate("e => e.viewport_.getZoom()")
    viewer.get_by_role("button", name="Zoom in", exact=True).click()
    viewer.wait_for_function(
        "n => document.querySelector('pdf-viewer').viewport_.getZoom() > n", arg=after
    )
    assert int(
        viewer.get_by_role("textbox", name="Zoom level", exact=True)
        .input_value()
        .rstrip("%")
    ) > round(before * 100)


def test_actual_back_forward_cache_keeps_pdf_usable(app):
    app.start()
    app.sample()
    app.page.set_viewport_size({"width": 767, "height": 1000})
    expect(app.page.locator("#preview")).to_be_hidden()
    url = app.page.locator("#download-pdf").get_attribute("href")
    app.page.goto(f"{app.site}/away")
    app.page.go_back(wait_until="commit")
    assert app.page.evaluate("acceptance.pageshows.includes(true)"), app.page.evaluate(
        "JSON.stringify(performance.getEntriesByType('navigation').map(x => ({type:x.type,reasons:x.notRestoredReasons})))"
    )
    expect(app.page.locator("#pdf-summary")).to_contain_text("5 charts", timeout=30000)
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    assert len(app.pdf().pages) == 6
    assert app.download().endswith(".pdf")
    assert not any("unload" in error.lower() for error in app.console_errors)
    app.page.reload()
    expect(app.page.locator("#status")).to_have_text("Ready", timeout=120000)
    app.sample()


def test_wide_back_returns_usable_page_with_restore_or_reload(app):
    app.start()
    app.sample()
    app.page.goto(f"{app.site}/away")
    app.page.go_back(wait_until="commit")
    expect(app.page.locator("#status")).to_have_text("Ready", timeout=120000)
    restored = app.page.evaluate("acceptance.pageshows.includes(true)")
    if not restored:
        # Chrome may decline caching a viewer child; the returned page still works.
        expect(app.page.locator("#pdf-section")).to_be_hidden()
        app.sample()
    else:
        expect(app.page.locator("#pdf-summary")).to_contain_text("5 charts")
    assert len(app.pdf().pages) == 6
    assert app.download().endswith(".pdf")
    assert not any("unload" in error.lower() for error in app.console_errors)

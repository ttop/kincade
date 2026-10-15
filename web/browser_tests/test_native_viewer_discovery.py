"""Real PDF child replacement must not conceal parent lifecycle failures."""

import pytest
from playwright.sync_api import Error as BrowserError

from conftest import ROOT, App


def test_current_viewer_survives_detached_child_in_frame_snapshot(app, monkeypatch):
    app.start()
    app.upload((ROOT / "tests/fixtures/cycle.ged").read_bytes())
    app.select()
    old = app.assert_one_page()
    old_source = app.page.locator("#pdf-frame").get_attribute("src")
    app.change("#large-print", True)
    source = app.page.locator("#pdf-frame").get_attribute("src")
    assert source != old_source
    # Let real native viewer teardown complete, without inventing a Frame/error.
    for _ in range(50):
        if old.is_detached():
            break
        app.page.wait_for_timeout(100)
    assert old.is_detached()
    assert old not in app.page.frames
    with pytest.raises(BrowserError) as detached:
        old.locator("pdf-viewer").count()
    assert type(detached.value).__name__ == "TargetClosedError"
    print(
        f"Actual detached PDF child: {type(detached.value).__name__}: {detached.value}"
    )
    assert app.page.evaluate("document.readyState") == "complete"
    assert not app.page.is_closed()
    assert app.page.context.browser.is_connected()

    # Recreate the stale snapshot boundary only. Every Frame, locator operation,
    # readiness check and geometry result still comes from the real browser.
    frames = type(app.page).frames
    with monkeypatch.context() as patch:
        patch.setattr(
            type(app.page),
            "frames",
            property(lambda page: [old, *frames.fget(page)]),
        )
        current = app.assert_one_page()
    assert current is not old
    assert current.locator("#plugin").get_attribute("original-url") == source


@pytest.mark.parametrize("failure", ["page.close", "context.close", "page.crash"])
def test_native_viewer_propagates_actual_parent_loss(
    browser_context, site, monkeypatch, capsys, failure
):
    context = browser_context.browser.new_context()
    page = context.new_page()
    probe = App(page, site)
    try:
        page.set_content('<iframe id="pdf-frame" src="about:blank"></iframe>')
        snapshot = page.frames[1:]
        assert len(snapshot) == 1
        lost = False

        def lose_parent_at_snapshot(_page):
            nonlocal lost
            if not lost:
                lost = True
                if failure == "page.close":
                    page.close()
                elif failure == "context.close":
                    context.close()
                else:
                    with pytest.raises(BrowserError):
                        page.goto("chrome://crash", timeout=5000)
            return snapshot

        with monkeypatch.context() as patch:
            patch.setattr(type(page), "frames", property(lose_parent_at_snapshot))
            with pytest.raises(BrowserError):
                probe.native_viewer()
        assert failure in probe.lifecycle_failed
        assert "Native PDF lifecycle:" in capsys.readouterr().out
    finally:
        probe.dispose()
        context.close()


def test_native_viewer_rejects_source_replaced_during_discovery(
    app, monkeypatch, capsys
):
    app.start()
    app.sample()
    app.assert_one_page()
    frames = type(app.page).frames
    replaced = False

    def replace_at_snapshot(page):
        nonlocal replaced
        if not replaced:
            replaced = True
            app.change("#large-print", True)
        return frames.fget(page)

    with monkeypatch.context() as patch:
        patch.setattr(type(app.page), "frames", property(replace_at_snapshot))
        with pytest.raises(AssertionError, match="Native PDF source changed"):
            app.native_viewer()
    assert "Native PDF lifecycle:" in capsys.readouterr().out
    # A new discovery captures the replacement and still checks real geometry.
    app.assert_one_page()

"""Hold real replies at the Worker boundary; never substitute Python or PDF results."""

import pytest
from playwright.sync_api import expect
from pypdf.generic import ContentStream

from conftest import ROOT, text


def test_stale_search_and_closed_picker(app):
    app.start()
    app.sample()
    assert_stale_search_and_closed_picker(app)


def assert_stale_search_and_closed_picker(app):
    url = app.page.locator("#download-pdf").get_attribute("href")
    renders = len(app.sent("render"))
    app.hold("results")
    search = app.page.locator("#search")
    search.fill("washington")
    app.held("results")
    old = app.replies("results")[-1]["seq"]
    search.fill("ball")
    app.held("results", 2)
    current = app.replies("results")[-1]["seq"]
    assert current > old
    search.press("Escape")
    expect(search).to_have_value("George WASHINGTON")
    baseline_rows = app.page.locator("#results button").all_text_contents()
    baseline_summary = app.page.locator("#result-summary").text_content()
    app.release_one("results", old)
    # A stale result must never appear, even while the current result is held.
    assert app.page.locator("#results button").all_text_contents() == baseline_rows
    assert app.page.locator("#result-summary").text_content() == baseline_summary
    assert app.page.evaluate(
        "seq => acceptance.held.some(x => x.event.data.type === 'results' && x.event.data.seq === seq)",
        current,
    )
    expect(app.page.locator("#root-choices")).to_be_hidden()
    app.release_one("results", current)
    # Dismissal restored the committed name, so even the draft's current reply
    # is now stale and must leave the closed picker unchanged.
    assert app.page.locator("#results button").all_text_contents() == baseline_rows
    assert app.page.locator("#result-summary").text_content() == baseline_summary
    expect(app.page.locator("#root-choices")).to_be_hidden()
    searches = len(app.sent("search"))
    search.press("Enter")
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    assert len(app.sent("render")) == renders
    assert len(app.sent("search")) == searches
    search.click()
    app.held("results")
    assert app.sent("search")[-1]["text"] == "George WASHINGTON"
    app.release("results")
    expect(app.page.locator("#result-summary")).to_have_text("1 match")
    expect(app.page.locator("#results")).to_contain_text("WASHINGTON")
    expect(app.page.locator("#results")).not_to_contain_text("BALL")
    expect(app.page.locator('#results [aria-selected="true"]')).to_have_count(0)
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    assert len(app.sent("render")) == renders


def test_one_render_in_flight_exact_latest_snapshot_and_chart_staleness(app):
    app.start()
    app.sample()
    old_url = app.page.locator("#download-pdf").get_attribute("href")
    app.hold("rendered")
    app.generations("2", wait=False)
    app.held("rendered")
    expect(app.page.locator("#rendering-overlay")).to_be_visible()
    sent = len(app.sent("render"))
    app.generations("3", wait=False)
    app.page.locator("#pedigree-paper").select_option("a4")
    app.page.locator("#chart-fan").check()
    app.page.locator("#fan-generations").select_option("4")
    app.page.locator("#fan-paper").select_option("a3")
    app.page.locator("#exclude-private").check()
    assert len(app.sent("render")) == sent
    assert app.page.locator("#download-pdf").get_attribute("href") == old_url
    app.release("rendered")
    app.pdf_ready()
    req = app.sent("render")[-1]
    assert req["chart"] == "fan"
    assert req["rootId"] == "I1"
    assert req["settings"] == {
        "generations": 4,
        "paper": "a3",
        "ink": "color",
        "exclude_private": True,
        "adoptive_parents": False,
        "event_standins": True,
        "preserve_case": False,
        "title": None,
        "footer": None,
        "lang": "en",
    }
    expect(app.page.locator("#pdf-summary")).to_contain_text("fan chart, 4 generations")
    assert len(app.pdf().pages) == 1
    assert len(app.sent("render")) == sent + 1
    assert (
        app.page.evaluate("acceptance.pdfs.length") == 2
    )  # stale PDF never briefly published


@pytest.mark.parametrize("invalid", ["0", "-1", "1.5"])
def test_invalid_pedigree_fan_invalid_accepts_current_fan_and_geometry(app, invalid):
    app.start()
    app.sample()
    url = app.page.locator("#download-pdf").get_attribute("href")
    n = len(app.sent("render"))
    app.generations(invalid, wait=False)
    expect(app.page.locator("#generations-error")).to_be_visible()
    assert len(app.sent("render")) == n
    assert app.page.locator("#download-pdf").get_attribute("href") == url
    app.hold("rendered")
    app.page.locator("#chart-fan").check()
    app.held("rendered")
    seq = app.sent("render")[-1]["seq"]
    app.page.locator("#chart-pedigree").check()
    assert len(app.sent("render")) == n + 1
    app.release("rendered")
    app.pdf_ready()
    assert app.replies("rendered")[-1]["seq"] == seq
    expect(app.page.locator("#pdf-summary")).to_contain_text("fan chart")
    assert float(app.pdf().pages[0].mediabox.width) == 792
    app.page.set_viewport_size({"width": 1200, "height": 1000})
    viewer = app.assert_one_page()
    native_ratio = viewer.locator("pdf-viewer").evaluate(
        "e => {const p=e.viewport_.getPageScreenRect(0); return p.width / p.height;}"
    )
    assert native_ratio == pytest.approx(792 / 612, abs=0.002)
    app.generations(3)
    expect(app.page.locator("#pdf-summary")).to_contain_text("chart")
    assert float(app.pdf().pages[0].mediabox.width) == 612


@pytest.mark.parametrize("valid", [True, False])
def test_open_barrier_replacement_while_rendering(app, valid):
    app.start()
    app.sample()
    app.hold("rendered")
    app.generations("3", wait=False)
    app.held("rendered")
    app.hold("opened" if valid else "error")
    data = (
        b"0 @X1@ INDI\n1 NAME Replacement /Synthetic/\n0 @X2@ INDI\n1 NAME Other /Synthetic/\n0 TRLR"
        if valid
        else b"0 HEAD\n0 TRLR"
    )
    app.page.locator("#file").set_input_files(
        {
            "name": "replacement.ged",
            "mimeType": "application/octet-stream",
            "buffer": data,
        }
    )
    app.held("opened" if valid else "error")
    sent = len(app.sent("render"))
    app.page.locator("#chart-fan").check()
    app.release("rendered")
    assert len(app.sent("render")) == sent
    app.release("opened" if valid else "error")
    if valid:
        expect(app.page.locator("#file-summary")).to_have_text(
            "replacement.ged: 2 people"
        )
        expect(app.page.locator("#pdf-section")).to_be_hidden()
        app.page.wait_for_function("() => acceptance.replies.at(-1).type === 'results'")
        app.select("X1")
        assert "Replacement" in text(app.pdf())
    else:
        app.pdf_ready()
        expect(app.page.locator("#open-error")).to_contain_text("no people")
        expect(app.page.locator("#root-summary")).to_have_text(
            "Root: I1, George WASHINGTON"
        )
        expect(app.page.locator("#pdf-summary")).to_contain_text("fan chart")


def test_last_file_before_ready_and_uploaded_sample_has_no_sample_intent(app):
    app.start(ready=False, gates=("ready",))
    app.held("ready")
    app.page.locator("#sample").click()
    app.page.locator("#file").set_input_files(
        {
            "name": "first.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 @A@ INDI\n1 NAME First /Synthetic/",
        }
    )
    app.page.locator("#file").set_input_files(
        ROOT / "docs/examples/george-washington.ged"
    )
    app.release("ready")
    expect(app.page.locator("#file-summary")).to_have_text(
        "george-washington.ged: 47 people"
    )
    app.page.wait_for_function("() => acceptance.replies.at(-1).type === 'results'")
    assert len(app.sent("open")) == 1
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    assert not app.sent("render")


def test_held_sample_provenance_and_current_options(app):
    app.start(ready=False, gates=("ready",))
    app.held("ready")
    app.page.locator("#sample").click()
    app.hold("results")
    app.release("ready")
    app.held("results")
    app.page.locator("#chart-fan").check()
    app.page.locator("#fan-generations").select_option("3")
    app.page.locator("#exclude-private").check()
    app.held("results", 2)
    app.release("results")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    expect(app.page.locator("#root-choices")).to_be_hidden()
    expect(app.page.locator("#pdf-summary")).to_contain_text("fan chart, 3 generations")


def test_sample_initial_results_failed_replacement_recovers_i1_once(app):
    app.start()
    app.hold("results")
    app.page.locator("#sample").click()
    app.held("results")
    app.hold("error")
    app.page.locator("#file").set_input_files(
        {
            "name": "empty.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    app.held("error")
    app.release("results")
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    app.release("error")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    assert len(app.sent("search")) == 2
    assert len(app.sent("render")) == 1


def test_pending_search_after_failed_open_sent_once_manual_root_precedence(app):
    app.start()
    app.sample()
    app.select("I2")
    app.hold("error")
    app.page.locator("#file").set_input_files(
        {
            "name": "empty.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    app.held("error")
    before = len(app.sent("search"))
    app.page.locator("#search").fill("ball")
    app.page.locator("#search").press("Enter")
    assert len(app.sent("search")) == before
    app.release("error")
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_contain_text("BALL")
    assert len(app.sent("search")) == before + 1


def test_unreadable_replacement_retains_prior_root_pdf_and_recovers(app):
    app.start()
    app.sample()
    before = len(app.sent("render"))
    app.page.locator("#file").set_input_files(
        {
            "name": "unreadable.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"\x00\xff\xfe\x01binary without GEDCOM records",
        }
    )
    expect(app.page.locator("#open-error")).to_be_visible()
    app.wait_render(before)
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_have_text(
        "Root: I1, George WASHINGTON"
    )
    assert len(app.pdf().pages) == 6


def test_manual_root_failed_open_does_not_reapply_sample_intent(app):
    app.start()
    app.sample()
    app.select("I2")
    before = len(app.sent("search"))
    app.page.locator("#file").set_input_files(
        {
            "name": "empty.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    expect(app.page.locator("#open-error")).to_be_visible()
    app.pdf_ready()
    expect(app.page.locator("#root-summary")).to_contain_text("I2,")
    assert len(app.sent("search")) == before


def test_root_changes_during_render_send_only_latest_root(app):
    app.start()
    app.sample()
    app.hold("rendered")
    app.generations("2", wait=False)
    app.held("rendered")
    before = len(app.sent("render"))
    for record in ["I2", "I3"]:
        app.page.locator("#search").click()
        app.page.locator("#search").fill(record)
        app.page.locator(f'#results button[data-record-id="{record}"]').click()
    assert len(app.sent("render")) == before
    app.release("rendered")
    app.pdf_ready()
    assert len(app.sent("render")) == before + 1
    assert app.sent("render")[-1]["rootId"] == "I3"
    assert app.download() == "Mary Ball cascading pedigree.pdf"
    assert app.page.evaluate("acceptance.pdfs.length") == 2


@pytest.mark.parametrize(
    "final_valid", [True, False], ids=["final-upload", "failed-final-open"]
)
def test_queued_opens_keep_barrier_and_final_file_provenance(app, final_valid):
    app.start(gates=("opened", "error", "results"))
    app.page.locator("#sample").click()
    app.held("opened")
    # Queue a second real open while the first response is still outstanding.
    data = (
        b"0 @I1@ INDI\n1 NAME Jane /Upload/\n0 @I2@ INDI\n1 NAME Other /Upload/\n0 TRLR"
        if final_valid
        else b"0 HEAD\n0 TRLR"
    )
    app.page.locator("#file").set_input_files(
        {
            "name": "george-washington.ged",
            "mimeType": "application/octet-stream",
            "buffer": data,
        }
    )
    if final_valid:
        app.held("opened", 2)
    else:
        app.held("error")
    assert len(app.sent("open")) == 2
    assert not app.sent("search")
    assert not app.sent("render")

    app.release_one("opened")
    expect(app.page.locator("#file-summary")).to_have_text(
        "george-washington.ged: 47 people"
    )
    expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
    app.page.locator("#chart-fan").check()
    app.page.locator("#fan-generations").select_option("3")
    app.page.locator("#exclude-private").check()
    # Even the initial sample search and subsequent option refresh wait for the
    # LAST outstanding open; no intermediate sample root or PDF is published.
    assert not app.sent("search")
    assert not app.sent("render")
    expect(app.page.locator("#pdf-section")).to_be_hidden()

    app.release_one("opened" if final_valid else "error")
    app.held("results")
    assert len(app.sent("search")) == 1
    assert not app.sent("render")
    app.release_one("results", app.sent("search")[-1]["seq"])
    assert len(app.sent("search")) == 1
    if final_valid:
        expect(app.page.locator("#file-summary")).to_have_text(
            "george-washington.ged: 2 people"
        )
        # The upload's filename and I1 record must not inherit sample intent.
        expect(app.page.locator("#root-summary")).to_have_text("Choose a root person.")
        expect(app.page.locator("#root-choices")).to_be_hidden()
        assert not app.sent("render")
        app.select("I1")
        expect(app.page.locator("#root-summary")).to_have_text("Root: I1, Jane UPLOAD")
        expect(app.page.locator("#pdf-summary")).to_contain_text(
            "fan chart, 3 generations, 1 person"
        )
        assert app.download() == "Living fan chart.pdf"
        uploaded_text = text(app.pdf())
        assert "Jane Upload" not in uploaded_text
        assert "Living" in uploaded_text
    else:
        app.pdf_ready()
        expect(app.page.locator("#open-error")).to_contain_text("no people")
        expect(app.page.locator("#file-summary")).to_have_text(
            "george-washington.ged: 47 people"
        )
        expect(app.page.locator("#root-summary")).to_have_text(
            "Root: I1, George WASHINGTON"
        )
        expect(app.page.locator("#pdf-summary")).to_contain_text(
            "fan chart, 3 generations"
        )
        assert app.download() == "George Washington fan chart.pdf"
        sample_pdf = app.pdf()
        sample_text = text(sample_pdf)
        assert "George WASHINGTON" in sample_text
        # Curved glyph positions may make extraction split inside the surname.
        assert "AugustineWASHINGTON" in "".join(sample_text.split())
        labels, glyphs = [], []
        for arguments, operator in ContentStream(
            sample_pdf.pages[0].get_contents(), sample_pdf
        ).operations:
            if operator == b"BT":
                glyphs = []
            elif operator == b"Tj":
                glyphs.append(str(arguments[0]))
            elif operator == b"ET":
                labels.append("".join(glyphs))
        assert "Augustine WASHINGTON" in labels
    assert len(app.sent("render")) == 1
    assert app.sent("render")[-1]["chart"] == "fan"
    assert app.sent("render")[-1]["settings"]["generations"] == 3
    assert app.sent("render")[-1]["settings"]["exclude_private"] is True

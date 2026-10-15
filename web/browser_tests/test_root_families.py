"""Root marriage choices exercise real metadata and rendered spouse/date pairs."""

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
1 FAMS @F1@
0 @I3@ INDI
1 NAME Second /DeWitt/
1 BIRT
2 DATE 2000
1 FAMS @F2@
0 @I4@ INDI
1 NAME Alone /Root/
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 MARR
2 DATE 1901
2 PLAC Firsttown
0 @F2@ FAM
1 HUSB @I1@
1 WIFE @I3@
1 MARR
2 DATE 2022
2 PLAC Secondtown
0 TRLR
"""


def ready_families(app, count=3):
    expect(app.page.locator("#root-family option")).to_have_count(count)
    if count > 1:
        expect(app.page.locator("#root-family")).to_be_enabled()


@pytest.mark.parametrize("width", [390, 1440])
def test_example_multiple_marriages_are_available_below_the_root_picker(app, width):
    app.page.set_viewport_size({"width": width, "height": 1000})
    app.start()
    choice = app.page.get_by_label("Root marriage", exact=True)
    expect(choice).to_be_hidden()
    app.sample()
    expect(choice).to_be_hidden()  # George has one marriage.
    app.select("I2")
    ready_families(app)
    expect(choice).to_be_visible()
    expect(app.page.locator("#more-options")).not_to_have_attribute("open", "")
    expect(
        app.page.get_by_role("region", name="Root person", exact=True).get_by_label(
            "Root marriage", exact=True
        )
    ).to_be_visible()
    search_box = app.page.locator("#search").bounding_box()
    marriage_box = choice.bounding_box()
    assert marriage_box["y"] >= search_box["y"] + search_box["height"]
    expect(choice.locator("option[value=F25]")).to_contain_text("Jane BUTLER")
    expect(choice.locator("option[value=F2]")).to_contain_text("Mary BALL")
    app.change("#root-family", "F2")
    body = text(app.pdf())
    assert "Mary BALL" in body and "1731" in body
    assert "Jane BUTLER" not in body
    app.select("I1")
    expect(choice).to_be_hidden()
    app.chart("fan")
    app.chart("pedigree")
    expect(choice).to_be_hidden()


def test_marriage_picker_requires_more_than_one_family_even_with_more_options_open(app):
    app.start()
    app.page.locator("#more-options summary").click()
    choice = app.page.get_by_label("Root marriage", exact=True)
    expect(choice).to_be_hidden()
    app.upload(MARRIAGES)
    expect(choice).to_be_hidden()
    app.select("I4")
    ready_families(app, 1)
    expect(choice).to_be_hidden()
    app.select("I2")
    ready_families(app, 2)
    expect(choice).to_be_hidden()
    app.select("I1")
    ready_families(app)
    expect(choice).to_be_visible()
    app.page.locator("#root-action").click()
    expect(choice).to_be_hidden()
    app.page.locator("#chart-fan").check()
    app.page.locator("#chart-pedigree").check()
    expect(choice).to_be_hidden()


def test_selected_root_family_changes_spouse_and_marriage_and_stays_out_of_fan(app):
    app.start()
    app.upload(MARRIAGES)
    app.select()
    ready_families(app)
    choice = app.page.get_by_label("Root marriage", exact=True)
    expect(choice).to_have_value("")
    assert app.sent("render")[-1]["settings"]["root_family"] is None
    initial = text(app.pdf())
    assert "First McCLURE" in initial and "1901" in initial
    assert "Second DEWITT" not in initial and "2022" not in initial
    app.change("#root-family", "F2")
    selected = text(app.pdf())
    assert "Second DEWITT" in selected and "2022" in selected
    assert "First McCLURE" not in selected and "1901" not in selected
    assert app.sent("render")[-1]["settings"]["root_family"] == "F2"
    app.chart("fan")
    expect(choice).to_be_hidden()
    assert "root_family" not in app.sent("render")[-1]["settings"]
    assert "Second DEWITT" not in text(app.pdf())
    app.chart("pedigree")
    expect(choice).to_have_value("F2")
    assert "Second DEWITT" in text(app.pdf())
    app.change("#root-family", "")
    assert app.sent("render")[-1]["settings"]["root_family"] is None
    assert "First McCLURE" in text(app.pdf())


def test_root_family_labels_refresh_privacy_and_case_without_resetting_selection(app):
    app.start()
    app.upload(MARRIAGES)
    app.select()
    app.page.locator("#more-options summary").click()
    ready_families(app)
    app.change("#root-family", "F2")
    app.change("#preserve-case", False)
    expect(app.page.locator("#root-family option[value=F2]")).to_have_text(
        "F2 · Second DeWitt · m. 2022 · mp. Secondtown"
    )
    expect(app.page.locator("#root-family")).to_have_value("F2")
    app.change("#exclude-private", True)
    expect(app.page.locator("#root-family option[value=F2]")).to_have_text(
        "F2 · Living"
    )
    expect(app.page.locator("#root-family")).to_have_value("F2")
    private = text(app.pdf())
    assert (
        "Second" not in private
        and "2022" not in private
        and "Secondtown" not in private
    )
    app.change("#large-print", True)
    ready_families(app)
    expect(app.page.locator("#root-family")).to_have_value("F2")
    app.change("#adoptive-parents", True)
    ready_families(app)
    expect(app.page.locator("#root-family")).to_have_value("F2")
    app.change("#exclude-private", False)
    expect(app.page.locator("#root-family option[value=F2]")).to_contain_text(
        "Second DeWitt"
    )
    assert "Second DeWitt" in text(app.pdf())


def test_root_family_reset_for_new_root_clear_and_successful_file_only(app):
    app.start()
    app.upload(MARRIAGES)
    app.select()
    app.page.locator("#more-options summary").click()
    ready_families(app)
    app.change("#root-family", "F2")
    app.page.locator("#file").set_input_files(
        {
            "name": "empty.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    expect(app.page.locator("#open-error")).to_be_visible()
    ready_families(app)
    expect(app.page.locator("#root-family")).to_have_value("F2")
    app.select("I2")
    ready_families(app, 2)
    expect(app.page.locator("#root-family")).to_have_value("")
    assert app.sent("render")[-1]["settings"]["root_family"] is None
    app.select("I1")
    ready_families(app)
    app.change("#root-family", "F2")
    app.page.locator("#root-action").click()
    ready_families(app, 1)
    expect(app.page.locator("#root-family")).to_have_value("")
    expect(app.page.locator("#root-family")).to_be_disabled()
    app.select("I1")
    ready_families(app)
    app.change("#root-family", "F2")
    app.upload(b"0 @I1@ INDI\n1 NAME New /Root/\n0 TRLR")
    ready_families(app, 1)
    app.select("I1")
    ready_families(app, 1)
    expect(app.page.locator("#root-family")).to_have_value("")
    assert app.sent("render")[-1]["settings"]["root_family"] is None


def test_stale_root_family_metadata_cannot_restore_labels_or_selection(app):
    app.start()
    app.upload(MARRIAGES)
    app.select()
    app.page.locator("#more-options summary").click()
    ready_families(app)
    app.change("#root-family", "F2")
    app.hold("root-metadata")
    app.page.locator("#preserve-case").uncheck()
    app.held("root-metadata")
    stale = app.sent("root-metadata")[-1]
    expect(app.page.locator("#root-family option")).to_have_count(1)
    expect(app.page.locator("#root-family")).to_be_hidden()
    app.page.locator("#exclude-private").check()
    app.held("root-metadata", 2)
    current = app.sent("root-metadata")[-1]
    app.release_one("root-metadata", stale["seq"])
    expect(app.page.locator("#root-family option")).to_have_count(1)
    expect(app.page.locator("#root-family")).to_be_hidden()
    app.release_one("root-metadata", current["seq"])
    ready_families(app)
    expect(app.page.locator("#root-family option[value=F2]")).to_have_text(
        "F2 · Living"
    )
    expect(app.page.locator("#root-family")).to_have_value("F2")
    app.select("I4", wait=False)
    app.held("root-metadata")
    old_root = app.sent("root-metadata")[-1]
    app.page.locator("#root-action").click()
    app.release_one("root-metadata", old_root["seq"])
    ready_families(app, 1)
    expect(app.page.locator("#root-family")).to_have_value("")
    app.select("I1", wait=False)
    app.held("root-metadata")
    old_tree = app.sent("root-metadata")[-1]
    app.upload(b"0 @I1@ INDI\n1 NAME New /Root/\n0 TRLR")
    app.select("I1", wait=False)
    app.held("root-metadata", 2)
    new_tree = app.sent("root-metadata")[-1]
    app.release_one("root-metadata", old_tree["seq"])
    ready_families(app, 1)
    app.release_one("root-metadata", new_tree["seq"])
    ready_families(app, 1)
    expect(app.page.locator("#root-family")).to_have_value("")
    app.release("root-metadata")
    app.pdf_ready()

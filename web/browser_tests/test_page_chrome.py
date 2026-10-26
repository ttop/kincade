"""Truthful file provenance and guidance through actual browser actions."""

from playwright.sync_api import expect

from conftest import ROOT


def test_example_action_tracks_successful_source_through_failure_and_clear(app):
    app.start()
    example = app.page.locator("#sample")
    expect(example).to_be_visible()
    app.sample()
    expect(example).to_be_hidden()
    expect(example).to_have_text("See an example")
    expect(app.page.locator("#file-summary")).to_have_text(
        "george-washington.ged: 47 people"
    )
    # A failed upload cannot claim the successful sample is now an upload.
    app.page.locator("#file").set_input_files(
        {
            "name": "invalid.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    expect(app.page.locator("#open-error")).to_contain_text("no people")
    expect(example).to_be_hidden()
    expect(app.page.locator("#file-summary")).to_have_text(
        "george-washington.ged: 47 people"
    )
    app.page.get_by_role("button", name="Clear selected person", exact=True).click()
    expect(example).to_be_hidden()  # Source identity outlives automatic root intent.
    app.upload(
        (ROOT / "docs/examples/george-washington.ged").read_bytes(),
        "george-washington.ged",
    )
    expect(example).to_be_visible()  # Same filename, real uploaded source.
    app.sample()
    expect(example).to_be_hidden()
    assert app.sent("render")[-1]["rootId"] == "I1"


def test_compact_file_picker_supports_keyboard_and_truthful_drop_source(app):
    app.start()
    chooser = app.page.get_by_role("button", name="Choose file", exact=True)
    expect(chooser).to_be_visible()
    chooser.focus()
    with app.page.expect_file_chooser() as selected:
        chooser.press("Enter")
    selected.value.set_files(
        {
            "name": "keyboard.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 @K@ INDI\n1 NAME Keyboard /Synthetic/",
        }
    )
    expect(app.page.locator("#file-summary")).to_have_text("keyboard.ged: 1 person")
    expect(app.page.locator("#file")).to_be_hidden()
    assert app.page.locator("#file").input_value() == ""
    app.page.locator("#drop-zone").evaluate(
        """e => {const transfer = new DataTransfer();
        transfer.items.add(new File(['0 @D@ INDI\\n1 NAME Dropped /Synthetic/'], 'drop.ged'));
        e.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));}"""
    )
    expect(app.page.locator("#file-summary")).to_have_text("drop.ged: 1 person")
    expect(app.page.locator("#sample")).to_be_visible()
    assert app.page.locator("#file").input_value() == ""
    expect(chooser).to_be_enabled()


def test_root_prompt_follows_loaded_selection_clear_and_pending_render(app):
    app.start()
    prompt = app.page.locator("#root-prompt")
    expect(prompt).to_be_hidden()
    app.upload()
    expect(prompt).to_be_visible()
    expect(app.page.locator("#status")).not_to_be_in_viewport()
    expect(prompt).to_have_text("Choose a root person to see the chart.")
    app.hold("rendered")
    app.select("I1", wait=False)
    app.held("rendered")
    expect(prompt).to_be_hidden()
    app.page.get_by_role("button", name="Clear selected person", exact=True).click()
    expect(prompt).to_be_visible()
    app.release("rendered")
    expect(prompt).to_be_visible()
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    app.select("I2")
    expect(prompt).to_be_hidden()

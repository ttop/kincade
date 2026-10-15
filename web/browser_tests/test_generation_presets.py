"""Page-boundary choices exercise real Worker/Pyodide and ancestry PDF cutoffs."""

import pytest
from playwright.sync_api import expect

from conftest import ROOT, text


def chain(depth=17):
    lines = []
    for n in range(1, depth + 1):
        lines += [f"0 @I{n}@ INDI", f"1 NAME Depth{n:02d} /Chain/"]
        if n < depth:
            lines += [f"1 FAMC @F{n}@", f"0 @F{n}@ FAM", f"1 HUSB @I{n + 1}@"]
    return "\n".join(lines).encode()


def choices(app):
    return app.page.locator("#pedigree-generation-choice option").all_text_contents()


@pytest.mark.parametrize("width", [320, 700, 1440])
def test_selected_generation_text_fits_the_responsive_control(app, width):
    app.page.set_viewport_size({"width": width, "height": 1000})
    app.start()
    app.sample()
    choice = app.page.locator("#pedigree-generation-choice")
    expect(choice).to_be_visible()
    metrics = choice.evaluate(
        """e => {
          const style = getComputedStyle(e);
          const context = document.createElement('canvas').getContext('2d');
          context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
          const textWidth = context.measureText(e.selectedOptions[0].text).width;
          const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
          const borders = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
          return {needed: textWidth + padding + borders + 24, width: e.getBoundingClientRect().width};
        }"""
    )
    assert metrics["needed"] <= metrics["width"], metrics
    expect(choice).to_have_value("all")
    assert app.sent("render")[-1]["settings"]["generations"] is None


def test_default_choices_and_fan_are_chart_specific(app):
    app.start()
    app.sample()
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("all")
    assert choices(app) == ["All generations", "4", "7", "Custom…"]
    expect(app.page.locator("#pedigree-generations")).to_be_hidden()
    assert app.sent("render")[-1]["settings"]["generations"] is None
    app.chart("fan")
    expect(app.page.locator("#fan-generations")).to_have_value("6")
    assert app.page.locator("#fan-generations option").all_text_contents() == [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
    ]
    assert app.sent("render")[-1]["settings"]["generations"] == 6


@pytest.mark.parametrize(
    "large,limits",
    [(False, [4, 7, 10, 13, 16, 19]), (True, [3, 5, 7, 9, 11, 13, 15, 17])],
)
def test_presets_cut_off_actual_ancestry_pdfs(app, large, limits):
    app.start()
    app.upload(chain())
    app.select()
    app.page.locator("#more-options summary").click()
    app.change("#index", False)
    app.change("#empty-boxes", True)
    if large:
        app.change("#large-print", True)
    for ordinal, limit in enumerate(limits):
        app.change("#pedigree-generation-choice", ordinal)
        request = app.sent("render")[-1]
        assert request["settings"]["generations"] == limit
        pdf = app.pdf()
        assert len(pdf.pages) == ordinal + 1
        assert float(pdf.pages[0].mediabox.width) == 612
        assert float(pdf.pages[0].mediabox.height) == 792
        body = text(pdf)
        assert f"Depth{min(limit, 17):02d}" in body
        assert f"Depth{limit + 1:02d}" not in body
    app.change("#pedigree-generation-choice", "all")
    assert app.sent("render")[-1]["settings"]["generations"] is None
    assert "Depth17" in text(app.pdf())
    app.generations(8)
    assert app.sent("render")[-1]["settings"]["generations"] == 8
    custom_body = text(app.pdf())
    assert "Depth08" in custom_body
    assert "Depth09" not in custom_body


def test_print_toggle_preserves_preset_ordinal_and_custom_literal(app):
    app.start()
    app.upload()
    app.select()
    app.change("#pedigree-generation-choice", 1)
    before = app.sent("render")[-1]["seq"]
    app.change("#large-print", True)
    assert choices(app) == ["All generations", "3", "5", "7", "9", "Custom…"]
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("1")
    assert app.sent("render")[-1]["settings"]["generations"] == 5
    assert app.sent("render")[-1]["seq"] == before + 1
    app.change("#large-print", False)
    assert app.sent("render")[-1]["settings"]["generations"] == 7
    app.change("#large-print", True)
    app.change("#pedigree-generation-choice", 2)  # Large 7 has a different ordinal.
    app.change("#large-print", False)
    assert app.sent("render")[-1]["settings"]["generations"] == 10
    app.change("#pedigree-generation-choice", "all")
    app.change("#large-print", True)
    assert app.sent("render")[-1]["settings"]["generations"] is None
    app.generations(7)
    app.change("#large-print", False)
    assert app.sent("render")[-1]["settings"]["generations"] == 7
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("custom")
    sent = len(app.sent("render"))
    app.page.locator("#pedigree-generation-choice").select_option(index=2)
    assert len(app.sent("render")) == sent  # Custom 7 and normal preset 7 agree.
    app.change("#large-print", True)
    assert app.sent("render")[-1]["settings"]["generations"] == 5


def test_custom_reveal_disclosure_invalid_draft_and_unblocking(app):
    app.start()
    app.sample()
    sent = len(app.sent("render"))
    seq = app.sent("render")[-1]["seq"]
    app.page.locator("#pedigree-generation-choice").select_option("custom")
    expect(app.page.locator("#more-options")).to_have_attribute("open", "")
    expect(app.page.get_by_label("Custom generations", exact=True)).to_be_focused()
    assert len(app.sent("render")) == sent  # Empty custom and All are identical.
    app.page.locator("#more-options summary").click()
    app.page.locator("#more-options summary").click()
    assert len(app.sent("render")) == sent
    app.generations("1.5", wait=False)
    expect(app.page.locator("#generations-error")).to_be_visible()
    app.page.locator("#large-print").check()
    expect(app.page.locator("#pedigree-generations")).to_have_value("1.5")
    assert len(app.sent("render")) == sent
    app.change("#pedigree-generation-choice", 0)
    assert app.sent("render")[-1]["seq"] == seq + 1
    assert app.sent("render")[-1]["settings"]["generations"] == 3
    expect(app.page.locator("#pedigree-generations")).to_be_hidden()
    app.page.locator("#pedigree-generation-choice").select_option("custom")
    expect(app.page.locator("#pedigree-generations")).to_have_value("1.5")
    expect(app.page.locator("#generations-error")).to_be_visible()
    app.change("#pedigree-generation-choice", "all")
    assert app.sent("render")[-1]["settings"]["generations"] is None
    app.page.locator("#pedigree-generation-choice").select_option("custom")
    app.chart("fan")
    app.page.locator("#chart-pedigree").check()
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("custom")
    expect(app.page.locator("#pedigree-generations")).to_have_value("1.5")
    expect(app.page.locator("#large-print")).to_be_checked()
    app.generations(3)
    assert app.sent("render")[-1]["settings"]["generations"] == 3
    app.generations("")
    assert app.sent("render")[-1]["settings"]["generations"] is None
    sent = len(app.sent("render"))
    app.page.locator("#pedigree-generation-choice").select_option("all")
    assert len(app.sent("render")) == sent
    expect(app.page.locator("#pedigree-generations")).to_be_hidden()


def test_held_reply_captures_remapped_latest_preset_once(app):
    app.start()
    # The third preset must exist even before the print metadata reply arrives.
    app.upload()
    app.select()
    app.hold("rendered")
    app.page.locator("#pedigree-generation-choice").select_option(index=2)
    app.held("rendered")
    first = app.sent("render")[-1]
    app.page.locator("#large-print").check()
    app.page.locator("#pedigree-generation-choice").select_option(index=3)
    app.page.locator("#more-options summary").click()
    app.page.locator("#more-options summary").click()
    assert app.sent("render")[-1] == first
    app.release_one("rendered", first["seq"])
    app.held("rendered")
    latest = app.sent("render")[-1]
    assert latest["seq"] == first["seq"] + 2
    assert latest["settings"]["generations"] == 7
    assert latest["settings"]["large_print"] is True
    assert set(latest["settings"]) == set(first["settings"])
    app.release("rendered")
    app.pdf_ready()
    assert app.page.evaluate("acceptance.pdfs.length") == 2


def await_horizon(app, last):
    expect(app.page.locator("#pedigree-generation-choice option").nth(-2)).to_have_text(
        str(last)
    )
    expect(
        app.page.locator("#pedigree-generation-choice option").nth(-2)
    ).to_be_enabled()


@pytest.mark.parametrize(
    "depth,normal,large",
    [
        (11, [4, 7, 10, 13], [3, 5, 7, 9, 11]),
        (17, [4, 7, 10, 13, 16, 19], [3, 5, 7, 9, 11, 13, 15, 17]),
    ],
)
def test_root_horizon_caps_and_extends_choices_without_changing_all(
    app, depth, normal, large
):
    app.start()
    app.upload(chain(depth))
    assert not app.sent("root-metadata")  # No full plans per search row.
    app.select()
    await_horizon(app, normal[-1])
    assert choices(app) == ["All generations", *map(str, normal), "Custom…"]
    assert app.sent("render")[-1]["settings"]["generations"] is None
    app.change("#large-print", True)
    await_horizon(app, large[-1])
    assert choices(app) == ["All generations", *map(str, large), "Custom…"]
    assert app.sent("render")[-1]["settings"]["generations"] is None
    assert len(app.sent("root-metadata")) == 2


def test_new_shallow_root_clamps_before_its_first_snapshot_and_stays_clamped(app):
    app.start()
    app.upload(chain())
    app.select()
    await_horizon(app, 19)
    app.change("#pedigree-generation-choice", 5)
    previous = app.sent("render")[-1]["seq"]
    app.select("I17")
    await_horizon(app, 4)
    assert choices(app) == ["All generations", "4", "Custom…"]
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("0")
    request = app.sent("render")[-1]
    assert (request["rootId"], request["settings"]["generations"], request["seq"]) == (
        "I17",
        4,
        previous + 1,
    )
    assert "Depth17" in text(app.pdf())
    assert "Depth16" not in text(app.pdf())
    app.select("I1")
    await_horizon(app, 19)
    assert app.sent("render")[-1]["settings"]["generations"] == 4
    app.change("#pedigree-generation-choice", 1)
    previous = app.sent("render")[-1]["seq"]
    app.select("I5")
    await_horizon(app, 13)
    assert app.sent("render")[-1]["settings"]["generations"] == 7
    assert app.sent("render")[-1]["seq"] == previous + 1


def parent_chain():
    return (
        chain(11).replace(
            b"1 FAMC @F1@", b"1 FAMC @F1@\n2 PEDI birth\n1 FAMC @AF@\n2 PEDI adopted"
        )
        + b"\n0 @A1@ INDI\n1 NAME Adopted /Parent/\n0 @AF@ FAM\n1 HUSB @A1@"
    )


def test_parent_and_print_context_clamps_and_retains_ordinal(app):
    app.start()
    app.upload(parent_chain())
    app.select()
    await_horizon(app, 13)
    app.change("#pedigree-generation-choice", 3)
    app.change("#large-print", True)
    await_horizon(app, 11)
    assert app.sent("render")[-1]["settings"]["generations"] == 9
    app.page.locator("#more-options summary").click()
    before = app.sent("render")[-1]["seq"]
    app.change("#adoptive-parents", True)
    await_horizon(app, 3)
    request = app.sent("render")[-1]
    assert request["settings"]["generations"] == 3
    assert request["seq"] == before + 1
    assert "Adopted" in text(app.pdf())
    assert "Depth03" not in text(app.pdf())
    app.change("#adoptive-parents", False)
    await_horizon(app, 11)
    assert app.sent("render")[-1]["settings"]["generations"] == 3
    app.change("#large-print", False)
    await_horizon(app, 13)
    assert app.sent("render")[-1]["settings"]["generations"] == 4


def test_metadata_and_render_barriers_publish_one_latest_snapshot(app):
    app.start()
    app.upload(parent_chain())
    app.select()
    await_horizon(app, 13)
    app.change("#pedigree-generation-choice", 3)
    app.hold("rendered")
    app.page.locator("#large-print").check()
    app.held("rendered")
    first = app.sent("render")[-1]
    app.hold("root-metadata")
    app.select("I2", wait=False)
    app.held("root-metadata")
    stale = app.sent("root-metadata")[-1]
    app.page.locator("#more-options summary").click()
    app.page.locator("#adoptive-parents").check()
    app.page.locator("#large-print").uncheck()
    app.select("I11", wait=False)
    app.held("root-metadata", 4)
    current = app.sent("root-metadata")[-1]
    sent = len(app.sent("render"))
    app.release_one("rendered", first["seq"])
    assert (
        len(app.sent("render")) == sent
    )  # Render barrier clear, metadata still gates.
    app.release_one("root-metadata", stale["seq"])
    assert len(app.sent("render")) == sent
    app.release_one("root-metadata", current["seq"])
    app.held("rendered")
    latest = app.sent("render")[-1]
    assert latest["seq"] == first["seq"] + 4
    assert latest["rootId"] == "I11"
    assert latest["settings"]["generations"] == 4
    assert latest["settings"]["large_print"] is False
    assert latest["settings"]["adoptive_parents"] is True
    assert set(latest["settings"]) == set(first["settings"])
    app.release("root-metadata")
    assert len(app.sent("render")) == sent + 1
    app.release("rendered")
    app.pdf_ready()
    assert "Depth11" in text(app.pdf())
    assert app.page.evaluate("acceptance.pdfs.length") == 3


def test_held_metadata_clear_and_reused_ids_cannot_restore_old_horizon(app):
    app.start()
    app.upload(chain())
    app.hold("root-metadata")
    app.select()
    app.held("root-metadata")
    old = app.sent("root-metadata")[-1]
    app.page.locator("#root-action").click()
    app.release_one("root-metadata", old["seq"])
    expect(app.page.locator("#pdf-section")).to_be_hidden()
    assert (
        not app.page.locator("#pedigree-generation-choice option")
        .filter(has_text="19")
        .count()
    )
    app.upload(chain(11))
    app.select()
    app.held("root-metadata")
    eleven = app.sent("root-metadata")[-1]
    app.upload(chain(1))
    app.select()
    app.held("root-metadata", 2)
    newest = app.sent("root-metadata")[-1]
    assert newest["treeVersion"] > eleven["treeVersion"] > old["treeVersion"]
    app.release_one("root-metadata", eleven["seq"])
    assert (
        not app.page.locator("#pedigree-generation-choice option")
        .filter(has_text="13")
        .count()
    )
    app.release_one("root-metadata", newest["seq"])
    await_horizon(app, 4)
    app.release("root-metadata")
    assert choices(app) == ["All generations", "4", "Custom…"]
    assert app.sent("render")[-1]["settings"]["generations"] is None


def test_metadata_pending_keeps_custom_and_fan_usable_and_current_fan_accepted(app):
    app.start()
    app.upload(chain(11))
    app.hold("root-metadata")
    app.select()
    app.held("root-metadata")
    app.generations(5)
    assert app.sent("render")[-1]["settings"]["generations"] == 5
    app.generations("1.5", wait=False)
    app.hold("rendered")
    app.page.locator("#chart-fan").check()
    app.held("rendered")
    fan = app.sent("render")[-1]
    app.page.locator("#chart-pedigree").check()
    assert app.sent("render")[-1] == fan
    app.release("root-metadata")
    await_horizon(app, 13)
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("custom")
    expect(app.page.locator("#pedigree-generations")).to_have_value("1.5")
    assert app.sent("render")[-1] == fan
    app.release("rendered")
    app.pdf_ready()
    expect(app.page.locator("#pdf-summary")).to_contain_text("fan chart, 6 generations")
    assert float(app.pdf().pages[0].mediabox.width) == 792


def test_failed_replacement_revalidates_current_horizon_once(app):
    app.start()
    app.upload(chain(11))
    app.select()
    await_horizon(app, 13)
    app.change("#pedigree-generation-choice", 3)
    before = app.sent("render")[-1]
    app.hold("error")
    app.hold("root-metadata")
    app.page.locator("#file").set_input_files(
        {
            "name": "empty.ged",
            "mimeType": "application/octet-stream",
            "buffer": b"0 HEAD\n0 TRLR",
        }
    )
    app.held("error")
    app.page.locator("#large-print").check()
    assert app.sent("render")[-1] == before
    app.release("error")
    app.held("root-metadata")
    assert app.sent("render")[-1] == before
    metadata = app.sent("root-metadata")[-1]
    assert metadata["treeVersion"] == 1
    replies = len(app.replies("rendered"))
    app.release("root-metadata")
    app.wait_render(replies)
    app.pdf_ready()
    latest = app.sent("render")[-1]
    assert latest["seq"] == before["seq"] + 2
    assert latest["settings"]["generations"] == 9
    assert len(app.sent("render")) == 3
    await_horizon(app, 11)


def test_cyclic_print_depth_clamps_without_resurrecting_old_ordinal(app):
    app.start()
    app.upload((ROOT / "tests/fixtures/cycle.ged").read_bytes())
    app.select()
    await_horizon(app, 7)
    assert choices(app) == ["All generations", "4", "7", "Custom…"]
    app.change("#pedigree-generation-choice", 1)
    before = app.sent("render")[-1]["seq"]
    app.change("#large-print", True)
    await_horizon(app, 3)
    assert choices(app) == ["All generations", "3", "Custom…"]
    latest = app.sent("render")[-1]
    assert latest["seq"] == before + 1
    assert latest["settings"]["generations"] == 3
    expect(app.page.locator("#pedigree-generation-choice")).to_have_value("0")
    app.change("#large-print", False)
    await_horizon(app, 7)
    assert app.sent("render")[-1]["settings"]["generations"] == 4
    app.assert_one_page()


def test_same_root_stale_parent_and_print_metadata_remain_gated(app):
    app.start()
    app.upload(parent_chain())
    app.select()
    await_horizon(app, 13)
    app.change("#pedigree-generation-choice", 3)
    app.hold("root-metadata")
    app.page.locator("#large-print").check()
    app.held("root-metadata")
    large_birth = app.sent("root-metadata")[-1]
    app.page.locator("#more-options summary").click()
    app.page.locator("#adoptive-parents").check()
    app.held("root-metadata", 2)
    large_adoptive = app.sent("root-metadata")[-1]
    app.page.locator("#large-print").uncheck()
    app.held("root-metadata", 3)
    normal_adoptive = app.sent("root-metadata")[-1]
    before = app.sent("render")[-1]
    app.release_one("root-metadata", large_birth["seq"])
    app.release_one("root-metadata", large_adoptive["seq"])
    assert app.sent("render")[-1] == before
    expect(
        app.page.locator("#pedigree-generation-choice option[value='3']")
    ).to_be_disabled()
    app.release_one("root-metadata", normal_adoptive["seq"])
    await_horizon(app, 4)
    app.pdf_ready()
    latest = app.sent("render")[-1]
    assert latest["seq"] == before["seq"] + 3
    assert latest["settings"]["generations"] == 4
    assert latest["settings"]["large_print"] is False
    assert latest["settings"]["adoptive_parents"] is True
    assert len(app.sent("render")) == 3
    app.release("root-metadata")

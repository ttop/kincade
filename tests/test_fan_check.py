"""The checks on a fan supplied by a caller. All names are invented."""

import pytest

from kincade.fan import Fan, FanCell, LegendEntry, check_fan


@pytest.mark.parametrize("generations", [1, 8, True, "6", 6.0])
def test_generations_must_be_an_integer_from_two_to_seven(generations):
    with pytest.raises(ValueError) as error:
        check_fan(Fan(generations, [FanCell(1)]))
    assert "generations" in str(error.value)
    assert repr(generations) in str(error.value)


@pytest.mark.parametrize("slot", [0, 8, -1, "2", 2.0, True])
def test_a_slot_must_be_an_integer_inside_the_fan(slot):
    with pytest.raises(ValueError) as error:
        check_fan(Fan(3, [FanCell(1), FanCell(slot)]))
    assert "slot" in str(error.value)
    assert repr(slot) in str(error.value)


def test_a_slot_cannot_appear_twice():
    with pytest.raises(ValueError, match=r"slot.*1.*(twice|duplicate)"):
        check_fan(Fan(3, [FanCell(1), FanCell(1)]))


def test_an_ancestor_needs_its_child_cell():
    with pytest.raises(ValueError, match=r"slot.*2.*child.*1"):
        check_fan(Fan(3, [FanCell(2)]))


def test_an_ancestor_cannot_be_above_an_empty_child():
    with pytest.raises(ValueError, match=r"slot.*4.*child.*2.*empty"):
        check_fan(Fan(3, [FanCell(1), FanCell(2, empty=True), FanCell(4)]))


@pytest.mark.parametrize("fill", ["red", "#abc", "#gggggg", "#123456\n", "123456"])
def test_a_cell_fill_must_be_a_six_digit_hex_color(fill):
    with pytest.raises(ValueError) as error:
        check_fan(Fan(2, [FanCell(1, fill=fill)]))
    assert "fill" in str(error.value)
    assert repr(fill) in str(error.value)


def test_an_empty_cells_fill_is_checked_too():
    with pytest.raises(ValueError, match=r"fill.*red"):
        check_fan(Fan(2, [FanCell(1), FanCell(2, empty=True, fill="red")]))


def test_a_legend_color_must_be_a_six_digit_hex_color():
    with pytest.raises(ValueError, match=r"legend.*color.*red"):
        check_fan(Fan(2, [FanCell(1)], [LegendEntry("Doe", "red", 1)]))


def test_a_highlight_slot_needs_a_cell():
    with pytest.raises(ValueError, match=r"highlight.*2"):
        check_fan(Fan(2, [FanCell(1)], highlight={2}))


@pytest.mark.parametrize("generations", range(2, 8))
def test_a_valid_fan_of_every_size_passes(generations):
    fan = Fan(
        generations,
        [
            FanCell(slot, given="Jane", surname="Doe")
            for slot in range(1, 2**generations)
        ],
        [LegendEntry("Doe", None, 1)],
        highlight={1},
    )
    check_fan(fan)


def test_a_fan_with_only_the_center_passes():
    check_fan(Fan(7, [FanCell(1)]))


def test_uppercase_hex_and_unfilled_cells_and_legend_entries_pass():
    check_fan(
        Fan(
            2,
            [FanCell(2, fill=None), FanCell(1, fill="#CDDFF4"), FanCell(3, empty=True)],
            [LegendEntry("Doe", "#AABBCC", 2), LegendEntry("Unknown", None, 1)],
            highlight={3},
        )
    )


def test_fans_do_not_share_their_default_legend_or_highlight():
    first, second = Fan(2, [FanCell(1)]), Fan(2, [FanCell(1)])
    first.legend.append(LegendEntry("Doe", None, 1))
    first.highlight.add(1)
    assert second.legend == []
    assert second.highlight == set()

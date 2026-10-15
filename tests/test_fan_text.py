"""Fan names, candidates, ring geometry and PDF text fitting."""

import math
from itertools import pairwise

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from kincade.fan import (
    Candidate,
    FanCell,
    cell_angles,
    fan_radius,
    full_name,
    mark_text,
    middle_angle,
    name_lines,
    ring_of,
    ring_radii,
    text_candidates,
    with_initials,
)


def test_candidates_keep_all_six_stages_in_order():
    cell = FanCell(
        1,
        title="Rev.",
        given="Frederick Augustus",
        surname="Strickland",
        suffix="Jr.",
        years="1820–1891",
    )
    assert text_candidates(cell) == [
        Candidate(
            ("Rev. Frederick Augustus Strickland, Jr.", "1820–1891"), False, False
        ),
        Candidate(
            ("Rev. Frederick Augustus", "Strickland, Jr.", "1820–1891"), False, False
        ),
        Candidate(
            ("Rev. Frederick Augustus Strickland, Jr.", "1820–1891"), True, False
        ),
        Candidate(
            ("Rev. Frederick Augustus", "Strickland, Jr.", "1820–1891"), True, False
        ),
        Candidate(("Rev. Frederick A. Strickland, Jr.", "1820–1891"), True, False),
        Candidate(("Rev. Frederick A.", "Strickland, Jr.", "1820–1891"), True, False),
        Candidate(("Rev. Frederick Augustus Strickland, Jr.",), True, False),
        Candidate(("Rev. Frederick Augustus", "Strickland, Jr."), True, False),
        Candidate(("Rev. Frederick A. Strickland, Jr.",), True, False),
        Candidate(("Rev. Frederick A.", "Strickland, Jr."), True, False),
        Candidate(("Rev. Frederick A.", "Strickland, Jr."), True, True),
        Candidate(("Strickland, Jr.",), True, True),
    ]


def test_no_years_removes_empty_lines_and_repeated_stages():
    assert text_candidates(FanCell(1, given="Jane Ann", surname="Doe")) == [
        Candidate(("Jane Ann Doe",), False, False),
        Candidate(("Jane Ann", "Doe"), False, False),
        Candidate(("Jane Ann Doe",), True, False),
        Candidate(("Jane Ann", "Doe"), True, False),
        Candidate(("Jane A. Doe",), True, False),
        Candidate(("Jane A.", "Doe"), True, False),
        Candidate(("Jane A.", "Doe"), True, True),
        Candidate(("Doe",), True, True),
    ]


def test_a_single_given_name_has_no_separate_initial_stages():
    assert text_candidates(
        FanCell(1, given="Jane", surname="Doe", years="1820–1891")
    ) == [
        Candidate(("Jane Doe", "1820–1891"), False, False),
        Candidate(("Jane", "Doe", "1820–1891"), False, False),
        Candidate(("Jane Doe", "1820–1891"), True, False),
        Candidate(("Jane", "Doe", "1820–1891"), True, False),
        Candidate(("Jane Doe",), True, False),
        Candidate(("Jane", "Doe"), True, False),
        Candidate(("Jane", "Doe"), True, True),
        Candidate(("Doe",), True, True),
    ]


@pytest.mark.parametrize("parts", [{"surname": "Doe"}, {"given": "Doe"}])
def test_one_name_part_leaves_one_candidate_per_set_of_flags(parts):
    assert text_candidates(FanCell(1, **parts)) == [
        Candidate(("Doe",), False, False),
        Candidate(("Doe",), True, False),
        Candidate(("Doe",), True, True),
    ]


def test_given_names_only_still_offer_initials():
    assert text_candidates(FanCell(1, given="Jane Ann")) == [
        Candidate(("Jane Ann",), False, False),
        Candidate(("Jane Ann",), True, False),
        Candidate(("Jane A.",), True, False),
        Candidate(("Jane A.",), True, True),
    ]


def test_years_without_a_name_remain_a_candidate():
    assert text_candidates(FanCell(1, years="1820–1891")) == [
        Candidate(("1820–1891",), False, False),
        Candidate(("1820–1891",), True, False),
    ]


@pytest.mark.parametrize(
    "cell", [FanCell(1), FanCell(1, empty=True, given="Jane", years="1820–1891")]
)
def test_empty_or_nameless_undated_cells_have_no_candidates(cell):
    assert text_candidates(cell) == []


@pytest.mark.parametrize(
    "given,expected",
    [
        ("", ""),
        ("Frederick", "Frederick"),
        ("Frederick Augustus", "Frederick A."),
        ("Frederick Augustus Bartholomew", "Frederick A. B."),
        ("Jane 123 ---", "Jane 123 ---"),
        ("Jane 'Ann Élodie", "Jane A. É."),
        ("  Jane\tAnn  ", "Jane A."),
    ],
)
def test_initials_keep_the_first_name_and_letterless_parts(given, expected):
    assert with_initials(given) == expected


@pytest.mark.parametrize("suffix", ["Jr.", ", Jr."])
def test_full_name_keeps_case_and_uses_one_comma_before_the_suffix(suffix):
    cell = FanCell(1, title=" Rev. ", given="Jane  Ann", surname=" Doe ", suffix=suffix)
    assert full_name(cell) == "Rev. Jane Ann Doe, Jr."
    assert name_lines(cell) == ("Rev. Jane Ann", "Doe, Jr.")
    assert name_lines(cell, initials=True) == ("Rev. Jane A.", "Doe, Jr.")


def test_a_suffix_with_no_surname_stays_with_the_given_name_in_the_full_name():
    cell = FanCell(1, given="Jane", suffix="Jr.")
    assert full_name(cell) == "Jane, Jr."
    assert name_lines(cell) == ("Jane", "Jr.")


@pytest.mark.parametrize(
    "copies,expected", [(-1, ""), (0, ""), (1, ""), (2, "×2"), (3, "×3")]
)
def test_repeat_marks_start_at_two_copies(copies, expected):
    assert mark_text(copies) == expected


@pytest.mark.parametrize(
    "slot,ring,angles,middle",
    [
        (1, 0, (210, -30), 90),
        (2, 1, (210, 90), 150),
        (3, 1, (90, -30), 30),
        (4, 2, (210, 150), 180),
        (7, 2, (30, -30), 0),
        (64, 6, (210, 206.25), 208.125),
        (127, 6, (-26.25, -30), -28.125),
    ],
)
def test_slots_follow_the_fathers_left_and_mothers_right_angles(
    slot, ring, angles, middle
):
    assert ring_of(slot) == ring
    assert cell_angles(slot) == angles
    assert middle_angle(slot) == middle


@pytest.mark.parametrize(
    "ring,radii",
    [
        (0, (0, 125)),
        (1, (125, 213)),
        (2, (213, 300)),
        (3, (300, 425)),
        (4, (425, 585)),
        (5, (585, 775)),
        (6, (775, 1000)),
    ],
)
def test_ring_radii_follow_the_depth_table(ring, radii):
    assert ring_radii(ring) == radii


@pytest.mark.parametrize(
    "generations,radius", [(2, 213), (3, 300), (4, 425), (5, 585), (6, 775), (7, 1000)]
)
def test_the_fan_radius_ends_at_the_requested_generation(generations, radius):
    assert fan_radius(generations) == radius


# PDF fitting uses the same candidates with the font set's measured widths.


@pytest.fixture
def fan_geometry():
    from kincade.fan import Fan
    from kincade.fanpdf import FanOptions, page_layout
    from kincade.lang import load_strings
    from kincade.pdf import BASE14

    return page_layout(Fan(7, []), FanOptions(), load_strings(), BASE14)


def fitted(cell, geometry, ellipsis="…"):
    from kincade.fanpdf import fit_cell
    from kincade.pdf import BASE14

    return fit_cell(cell, geometry, BASE14, ellipsis)


def test_short_parent_name_keeps_the_first_candidate(fan_geometry):
    lines = fitted(
        FanCell(2, given="Jane", surname="Doe", years="1820–1891"), fan_geometry
    )
    assert [line.text for line in lines] == ["Jane Doe", "1820–1891"]
    assert all(line.scale == 1 for line in lines)


def test_long_ring_three_name_splits_before_squeezing(fan_geometry):
    lines = fitted(
        FanCell(10, given="Jane Annabelle", surname="Doe", years="1820–1891"),
        fan_geometry,
    )
    assert [line.text for line in lines] == ["Jane Annabelle", "Doe", "1820–1891"]
    assert all(line.scale == 1 for line in lines)


def test_a_line_just_over_its_room_is_squeezed(fan_geometry):
    from kincade.pdf import SQUEEZE

    lines = fitted(FanCell(10, given="WWWWWWWWI", years="1820–1891"), fan_geometry)
    assert [line.text for line in lines] == ["WWWWWWWWI", "1820–1891"]
    assert SQUEEZE <= lines[0].scale < 1


def test_outer_ring_uses_initials_before_losing_years(fan_geometry):
    lines = fitted(
        FanCell(
            64, given="Frederick Augustus", surname="Strickland", years="1820–1891"
        ),
        fan_geometry,
    )
    assert [line.text for line in lines] == ["Frederick A. Strickland", "1820–1891"]


def test_outer_ring_loses_years_before_cutting_names(fan_geometry):
    lines = fitted(
        FanCell(
            64,
            given="Frederick Augustus Bartholomew",
            surname="Strickland",
            suffix="Jr.",
            years="1820–1891",
        ),
        fan_geometry,
    )
    assert [line.text for line in lines] == ["Frederick A. B.", "Strickland, Jr."]


@pytest.mark.parametrize("ellipsis", ["…", "~"])
def test_the_last_candidate_uses_the_language_ellipsis(fan_geometry, ellipsis):
    lines = fitted(
        FanCell(
            64,
            given="Frederick Augustus",
            surname="Inventedlongsurname" * 5,
            years="1820–1891",
        ),
        fan_geometry,
        ellipsis,
    )
    assert lines[-1].text.endswith(ellipsis)
    assert all("1820" not in line.text for line in lines)


def test_a_cell_with_no_room_for_even_an_ellipsis_draws_nothing(fan_geometry):
    from dataclasses import replace

    # The depth and angle remain fixed while this cell's type consumes its room.
    geometry = replace(fan_geometry, units=fan_geometry.units, text_sizes=(10000,) * 7)
    assert fitted(FanCell(64, surname="Doe"), geometry) is None


def test_a_copy_mark_takes_room_before_the_name(fan_geometry):
    from dataclasses import replace

    cell = FanCell(
        64,
        given="Frederick Augustus Bartholomew",
        surname="Strickland",
        years="1820–1891",
    )
    plain = fitted(cell, fan_geometry)
    marked = fitted(replace(cell, copies=2), fan_geometry)
    assert [line.text for line in plain] == ["Frederick A. B. Strickland", "1820–1891"]
    assert [line.text for line in marked] == ["Frederick A. B.", "Strickland"]


def test_every_slot_has_consistent_arc_or_upright_radial_direction():
    from kincade.fanpdf import text_direction

    for slot in range(1, 128):
        ring, middle = ring_of(slot), middle_angle(slot)
        expected = (
            "level"
            if ring == 0
            else "clockwise"
            if ring <= 3
            else ("inward" if middle > 90 else "outward")
        )
        assert text_direction(slot) == expected
    assert [text_direction(s) for s in (4, 7, 8, 15, 16, 31)] == [
        "clockwise",
        "clockwise",
        "clockwise",
        "clockwise",
        "inward",
        "outward",
    ]


@pytest.fixture(scope="module")
def drawn_fan_cells():
    from kincade.fan import Fan
    from kincade.fanpdf import FanOptions, page_layout, render_fan
    from kincade.lang import load_strings
    from kincade.pdf import BASE14

    from conftest import TODAY
    from pdfread import text_matrix_objects

    fan = Fan(7, [FanCell(slot, given=f"Slot{slot:03}") for slot in range(1, 128)])
    opts = FanOptions(
        fonts="base14", compress=False, today=TODAY, title="Invented fan", footer=False
    )
    layout = page_layout(fan, opts, load_strings(), BASE14)
    objects = text_matrix_objects(render_fan(fan, opts))
    cells = {}
    for obj in objects:
        text = "".join(run.text for run in obj)
        if text.startswith("Slot"):
            assert text not in cells
            cells[text] = obj
    assert set(cells) == {f"Slot{slot:03}" for slot in range(1, 128)}
    return layout, cells


def assert_arc_line_reading_frame(runs, layout, slot, direction, font=None):
    from kincade.pdf import BASE14

    font = font or BASE14.sans
    assert direction in ("clockwise", "counterclockwise")
    ring = ring_of(slot)
    inner, outer = (radius * layout.units for radius in ring_radii(ring))
    cx, cy = layout.center
    count = 2**ring
    middle = math.radians(210 - (slot - count + 0.5) * 240 / count)
    ray = (math.cos(middle), math.sin(middle))
    sign = -1 if direction == "clockwise" else 1
    previous = None
    for run in runs:
        assert len(run.text) == 1
        a, b, c, d, x, y = run.matrix
        advance = stringWidth(run.text, font, run.size) * run.scale
        # Tm locates the glyph's start; its advance midpoint lies on the arc.
        dx, dy = x + advance / 2 * a - cx, y + advance / 2 * b - cy
        radius = math.hypot(dx, dy)
        assert inner < radius < outer
        radial = (dx / radius, dy / radius)
        tangent = (-sign * radial[1], sign * radial[0])
        up = (-sign * radial[0], -sign * radial[1])
        assert (a, b, c, d) == pytest.approx((*tangent, *up), abs=1e-5)
        angle_from_middle = math.atan2(
            ray[0] * radial[1] - ray[1] * radial[0],
            ray[0] * radial[0] + ray[1] * radial[1],
        )
        assert abs(angle_from_middle) < math.radians(120 / count)
        if previous is not None:
            # The signed cross product handles glyphs that straddle 180 degrees.
            assert sign * (previous[0] * radial[1] - previous[1] * radial[0]) > 0
        previous = radial


@pytest.mark.parametrize("slot", range(1, 128))
def test_every_slot_draws_text_turned_in_its_direction(drawn_fan_cells, slot):
    from kincade.fanpdf import text_direction
    from kincade.pdf import BASE14

    layout, cells = drawn_fan_cells
    runs = cells[f"Slot{slot:03}"]
    direction = text_direction(slot)
    ring = ring_of(slot)
    inner, outer = (radius * layout.units for radius in ring_radii(ring))
    cx, cy = layout.center
    if direction == "level":
        assert len(runs) == 1
        a, b, c, d, x, y = runs[0].matrix
        assert (a, b, c, d) == pytest.approx((1, 0, 0, 1))
        assert math.hypot(x - cx, y - cy) < outer
        return

    # The 240-degree fan splits equally from 210 degrees toward -30 degrees.
    count = 2**ring
    middle = math.radians(210 - (slot - count + 0.5) * 240 / count)
    ray = (math.cos(middle), math.sin(middle))
    if direction in ("outward", "inward"):
        assert len(runs) == 1
        a, b, c, d, x, y = runs[0].matrix
        sign = 1 if direction == "outward" else -1
        baseline = (sign * ray[0], sign * ray[1])
        assert (a, b, c, d) == pytest.approx(
            (*baseline, -baseline[1], baseline[0]), abs=1e-5
        )
        width = stringWidth(runs[0].text, BASE14.sans, runs[0].size) * runs[0].scale
        dx, dy = x + width / 2 * a - cx, y + width / 2 * b - cy
        assert inner < dx * ray[0] + dy * ray[1] < outer
        return

    assert len(runs) == len(f"Slot{slot:03}")
    assert_arc_line_reading_frame(runs, layout, slot, direction)


@pytest.mark.parametrize("generations", range(4, 8))
@pytest.mark.parametrize(
    "slot,given", [(8, "Albert"), (9, "Jane"), (14, "Peter"), (15, "Catherine")]
)
@pytest.mark.parametrize("multiline", [False, True])
def test_ring_three_end_labels_follow_neighboring_arcs(
    generations, slot, given, multiline
):
    from kincade.fan import Fan
    from kincade.fanpdf import FanOptions, page_layout, render_fan
    from kincade.lang import load_strings
    from kincade.pdf import BASE14

    from conftest import TODAY
    from pdfread import text_matrix_objects

    # Reversing either terminal arc must fail on the actual glyph frames, not
    # just the direction classifier. The named neighbors are clockwise controls.
    cell = FanCell(
        slot,
        given=given,
        surname="Doe" if multiline else "",
        years="1820–1891" if multiline else "",
        copies=2 if multiline else 1,
    )
    opts = FanOptions(
        fonts="base14", compress=False, today=TODAY, title="Arc labels", footer=False
    )
    cells = [cell]
    ancestor = slot // 2
    while ancestor:
        cells.append(FanCell(ancestor))
        ancestor //= 2
    fan = Fan(generations, cells)
    layout = page_layout(fan, opts, load_strings(), BASE14)
    objects = [
        obj
        for obj in text_matrix_objects(render_fan(fan, opts))
        if "".join(run.text for run in obj) != "Arc labels"
    ]
    expected = [f"{given} Doe", "1820–1891", "×2"] if multiline else [given]
    assert ["".join(run.text for run in obj) for obj in objects] == expected
    radii = []
    cx, cy = layout.center
    inner, outer = (r * layout.units for r in (300, 425))
    middle = math.radians({8: 195, 9: 165, 14: 15, 15: -15}[slot])
    for obj in objects:
        font = BASE14.bold if "".join(run.text for run in obj) == "×2" else BASE14.sans
        assert_arc_line_reading_frame(obj, layout, slot, "clockwise", font)
        for run in obj:
            a, b, c, d, x, y = run.matrix
            width = stringWidth(run.text, font, run.size) * run.scale
            # The advance box, including full type height, stays in the wedge
            # and ring; these checks also protect mark clearance and fitting.
            from reportlab.pdfbase.pdfmetrics import getAscentDescent

            ascent, descent = getAscentDescent(font, run.size)
            for along in (0, width):
                for up in (descent, ascent):
                    dx = x + along * a + up * c - cx
                    dy = y + along * b + up * d - cy
                    assert inner < math.hypot(dx, dy) < outer
                    angle = math.atan2(dy, dx) - middle
                    angle = (angle + math.pi) % (2 * math.pi) - math.pi
                    assert abs(angle) < math.radians(15)
        run = obj[0]
        radii.append(math.hypot(run.matrix[4] - cx, run.matrix[5] - cy))
    if multiline:
        assert radii[2] > radii[0] > radii[1]  # copy mark, name, years


@pytest.mark.parametrize(
    "slot,outer_first", [(8, True), (9, True), (10, True), (14, True), (15, True)]
)
def test_arc_line_order_follows_reading_direction(fan_geometry, slot, outer_first):
    lines = fitted(
        FanCell(slot, given="Jane", surname="Doe", years="1820–1891"), fan_geometry
    )
    assert (lines[0].radius > lines[1].radius) == outer_first


@pytest.mark.parametrize("given", ["Jane", "Jane Annabelle"])
@pytest.mark.parametrize(
    "slot,direction,split",
    [
        (1, "level", True),
        (2, "clockwise", False),
        (3, "clockwise", False),
        (4, "clockwise", False),
        (7, "clockwise", False),
        (8, "clockwise", True),
        (10, "clockwise", True),
        (13, "clockwise", True),
        (15, "clockwise", True),
        (16, "inward", True),
        (23, "inward", True),
        (24, "outward", True),
        (31, "outward", True),
        (32, "inward", True),
        (47, "inward", True),
        (48, "outward", True),
        (63, "outward", True),
        (64, "inward", False),
        (95, "inward", False),
        (96, "outward", False),
        (127, "outward", False),
    ],
)
def test_fan_draws_lines_in_reading_order(slot, direction, split, given):
    from kincade.fan import Fan
    from kincade.fanpdf import FanOptions, page_layout, render_fan
    from kincade.lang import load_strings
    from kincade.pdf import BASE14

    from conftest import TODAY
    from pdfread import text_matrix_objects

    cells = [FanCell(slot, given=given, surname="Doe", years="1820–1891")]
    ancestor = slot // 2
    while ancestor:
        cells.append(FanCell(ancestor))
        ancestor //= 2
    fan = Fan(7, cells)
    opts = FanOptions(
        fonts="base14", compress=False, today=TODAY, title="Invented fan", footer=False
    )
    layout = page_layout(fan, opts, load_strings(), BASE14)
    objects = [
        obj
        for obj in text_matrix_objects(render_fan(fan, opts))
        if "".join(run.text for run in obj) != "Invented fan"
    ]
    # Rings 1–2 and 6 keep two lines at their default text sizes.
    expected = (
        (given, "Doe", "1820–1891")
        if split and given == "Jane Annabelle"
        else (f"{given} Doe", "1820–1891")
    )
    assert tuple("".join(run.text for run in obj) for obj in objects) == expected

    cx, cy = layout.center
    count = 2 ** (slot.bit_length() - 1)
    middle = math.radians(210 - (slot - count + 0.5) * 240 / count)
    up = (
        (0, 1)
        if direction == "level"
        else (math.sin(middle), -math.cos(middle))
        if direction == "inward"
        else (-math.sin(middle), math.cos(middle))
    )
    positions = []
    for obj in objects:
        run = obj[0]
        a, b, _, _, x, y = run.matrix
        if direction in ("clockwise", "counterclockwise"):
            assert_arc_line_reading_frame(obj, layout, slot, direction)
            advance = stringWidth(run.text, BASE14.sans, run.size) * run.scale
            # The glyph's advance midpoint lies on its baseline arc.
            radius = math.hypot(x + advance / 2 * a - cx, y + advance / 2 * b - cy)
            positions.append(radius if direction == "clockwise" else -radius)
        else:
            # Projection onto the reading frame's up axis gives top-to-bottom order.
            positions.append((x - cx) * up[0] + (y - cy) * up[1])
    assert all(first > second for first, second in pairwise(positions)), (
        expected,
        positions,
    )


def test_letter_seven_generation_type_has_the_specified_size(fan_geometry):
    center = fitted(FanCell(1, surname="Doe"), fan_geometry)[0]
    outer = fitted(FanCell(64, surname="Doe"), fan_geometry)[0]
    assert center.size == pytest.approx(9, abs=0.3)
    assert outer.size == pytest.approx(6.6, abs=0.3)


@pytest.mark.parametrize("kern", [None, -0.1, -10])
def test_character_advances_use_the_same_kerning_decision_as_width(monkeypatch, kern):
    import kincade.pdf as pdf

    if kern is not None:
        monkeypatch.setitem(pdf._KERNING, "Helvetica", lambda a, b: kern)
    advances = pdf.char_advances("Jane Doe", "Helvetica", 10)
    assert len(advances) == 8
    assert sum(advances) == pytest.approx(pdf.text_width("Jane Doe", "Helvetica", 10))
    assert pdf.char_advances("", "Helvetica", 10) == []

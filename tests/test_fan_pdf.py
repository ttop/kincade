"""The fan's one-page PDF: text, geometry, inks, legend and validation."""

import math
import re
from copy import deepcopy

import pytest

from kincade import (
    Fan,
    FanCell,
    FanOptions,
    LegendEntry,
    Person,
    Tree,
    plan_fan,
    render_fan,
)
from kincade.cli import fan_summary
from kincade.fanpdf import page_layout
from kincade.lang import load_strings
from kincade.pdf import BASE14

from conftest import TODAY
from pdfread import count_pages, first_page, runs, text_objects


def full_fan(generations=7):
    return Fan(
        generations,
        [
            FanCell(
                slot, given="Jane", surname="Doe", years="1820–1891", fill="#cddff4"
            )
            for slot in range(1, 2**generations)
        ],
        name="Jane Doe",
    )


def options(**kwargs):
    return FanOptions(today=TODAY, fonts="base14", compress=False, **kwargs)


def render(fan=None, **kwargs):
    return render_fan(fan if fan is not None else full_fan(), options(**kwargs))


def test_title_names_years_footer_and_title_metadata():
    pdf = render()
    texts = [text for text, _ in text_objects(pdf)]
    assert "Jane Doe — Fan chart" in texts
    assert "Jane Doe" in texts
    assert "1820–1891" in texts
    assert "Created 10 Oct 2026 using Kincade" in texts
    assert b"/Title (Jane Doe \\204 Fan chart)" in pdf
    assert count_pages(pdf) == 1
    assert pdf.startswith(b"%PDF")


def test_overrides_no_footer_and_german_title():
    texts = [t for t, _ in text_objects(render(title="My fan", footer="My footer"))]
    assert "My fan" in texts and "My footer" in texts
    assert not any(
        t.startswith("Created") for t, _ in text_objects(render(footer=False))
    )
    assert "Jane Doe — Fächerahnentafel" in [
        t for t, _ in text_objects(render(lang="de"))
    ]


def test_title_and_footer_are_fitted_with_the_custom_ellipsis():
    pdf = render(title="T" * 400, footer="F" * 400, lang={"ellipsis": "~"})
    for run in runs(pdf):
        if run.text.startswith(("T", "F")):
            assert run.text.endswith("~")
            assert run.x >= 36 - 0.01 and run.right() <= 756 + 0.01


@pytest.mark.parametrize(
    "paper,width,height",
    [
        ("letter", 792, 612),
        ("a4", 841.89, 595.28),
        ("tabloid", 1224, 792),
        ("a3", 1190.55, 841.89),
    ],
)
def test_landscape_paper_dimensions(paper, width, height):
    pdf = render(paper=paper)
    media = re.search(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
    assert tuple(map(float, media.groups())) == (width, height)


@pytest.mark.parametrize("ink", ["color", "grayscale", "bw"])
def test_each_ink_draws_its_fills_outlines_and_legend(ink):
    fan = full_fan(2)
    fan.legend = [LegendEntry("North", "#cddff4", 3)]
    pdf = render(fan, ink=ink)
    stream = first_page(pdf)
    texts = [t for t, _ in text_objects(pdf)]
    if ink == "bw":
        assert not re.search(rb"(?<!\S)(?:f\*?|B\*?)(?!\S)", stream)
        assert "North (3)" not in texts
        assert b"0 0 0 RG" in stream
    else:
        assert b".803922 .87451 .956863 rg" in stream
        assert re.search(rb"\bB\*?\b", stream)
        assert "North (3)" in texts
        assert b".25 .25 .25 RG" in first_page(render(full_fan(2), ink=ink))


def test_empty_cells_have_a_dashed_outline_and_no_fill_or_text():
    pdf = render(
        Fan(2, [FanCell(1), FanCell(2, empty=True, given="Hidden", fill="#202020")])
    )
    stream = first_page(pdf)
    assert re.search(rb"\[[\d. ]+\] 0 d", stream)
    assert not re.search(rb"(?<!\S)(?:f\*?|B\*?)(?!\S)", stream)
    assert "Hidden" not in [t for t, _ in text_objects(pdf)]


def cell_drawings(pdf):
    """Saved graphics states with a cell outline, its path and paint operator."""
    return re.findall(
        rb"\bq\s+([\d. ]+ RG)\s+([\d.]+ w)\s+(.*?)\s+Q\b",
        first_page(pdf),
        re.DOTALL,
    )


def assert_blank_outlines(drawings, count):
    blanks = [drawing for drawing in drawings if b"[2 2] 0 d" in drawing[2]]
    assert len(blanks) == count
    assert len({path for _, _, path in blanks}) == count
    for stroke, width, path in blanks:
        assert stroke == b".5 .5 .5 RG"
        assert width == b".5 w"
        assert re.search(rb"\bh\s+S$", path)
        assert len(re.findall(rb"(?<!\S)m(?!\S)", path)) == 1
        assert not re.search(rb"(?<!\S)(?:f\*?|B\*?|rg|BT)(?!\S)", path)


@pytest.mark.parametrize("generations", range(2, 8))
def test_planned_missing_parents_and_all_earlier_ancestors_have_outlines(generations):
    fan = plan_fan(
        Tree({"jane": Person("jane", given="Jane", surname="Doe")}),
        "jane",
        generations=generations,
    )
    before = deepcopy(fan)
    summary = fan_summary(fan)
    pdf = render(fan)
    drawings = cell_drawings(pdf)
    assert len(drawings) == 2**generations - 1
    assert_blank_outlines(drawings, 2**generations - 2)
    assert count_pages(pdf) == 1
    assert [t for t, _ in text_objects(pdf) if t] == [
        "Jane DOE — Fan chart",
        "Created 10 Oct 2026 using Kincade",
        "Jane DOE",
    ]
    assert fan == before
    assert fan_summary(fan) == summary
    assert [(cell.slot, cell.empty) for cell in fan.cells] == [
        (1, False),
        (2, True),
        (3, True),
    ]


@pytest.mark.parametrize("ink", ["color", "grayscale", "bw"])
def test_sparse_supplied_fan_outlines_missing_positions_without_changing_people(ink):
    # Deliberately unordered: an explicit empty parent precedes a filled person.
    fan = Fan(
        3,
        [
            FanCell(3, empty=True, given="Hidden", fill="#202020"),
            FanCell(1, given="Jane", fill="#202020"),
            FanCell(2, given="John", fill="#202020"),
        ],
        legend=[LegendEntry("Family", "#202020", 2)],
        highlight={2},
        name="Jane",
    )
    before = deepcopy(fan)
    pdf = render(fan, ink=ink)
    drawings = cell_drawings(pdf)
    assert len(drawings) == 7
    assert_blank_outlines(drawings, 5)
    known = [drawing for drawing in drawings if b" 0 d" not in drawing[2]]
    assert len(known) == 2
    if ink == "color":
        assert all(path.rstrip().endswith(b"B*") for _, _, path in known)
        assert all(stroke == b".25 .25 .25 RG" for stroke, _, _ in known)
    elif ink == "grayscale":
        assert known[0][0] == b".8 .8 .8 RG"
        assert known[0][2].rstrip().endswith(b"S")
        assert known[1][0] == b".25 .25 .25 RG"
        assert known[1][2].rstrip().endswith(b"B*")
    else:
        assert [width for _, width, _ in known] == [b".5 w", b"1 w"]
        assert all(stroke == b"0 0 0 RG" for stroke, _, _ in known)
        assert all(path.rstrip().endswith(b"S") for _, _, path in known)
    texts = text_objects(pdf)
    assert "Hidden" not in [t for t, _ in texts]
    assert ("Jane", (0, 0, 0)) in texts
    assert ("John", (0, 0, 0) if ink == "bw" else (1, 1, 1)) in texts
    assert ("Family (2)" in [t for t, _ in texts]) == (ink != "bw")
    assert fan == before
    assert count_pages(pdf) == 1


@pytest.mark.parametrize("generations", [2, 7])
def test_full_known_fan_has_no_extra_or_dashed_cell_outlines(generations):
    drawings = cell_drawings(render(full_fan(generations)))
    assert len(drawings) == 2**generations - 1
    assert not any(b" 0 d" in path for _, _, path in drawings)


def test_legend_order_counts_and_swatch_colors():
    fan = full_fan()
    fan.legend = [
        LegendEntry("North", "#ff0000", 2),
        LegendEntry("South", "#00ff00", 3),
        LegendEntry("Unknown", None, 4),
    ]
    pdf = render(fan)
    assert [
        t
        for t, _ in text_objects(pdf)
        if t in {"North (2)", "South (3)", "Unknown (4)"}
    ] == ["North (2)", "South (3)", "Unknown (4)"]
    assert b"1 0 0 rg" in first_page(pdf) and b"0 1 0 rg" in first_page(pdf)
    assert not any("North" in t for t, _ in text_objects(render()))


@pytest.mark.parametrize("generations", [2, 7])
def test_long_legend_is_whole_and_clear_of_the_fan_footer_and_page_edges(generations):
    fan = full_fan(generations)
    fan.legend = [
        LegendEntry(f"Invented location number {i:02d}", "#cddff4", i)
        for i in range(30)
    ]
    opts = options()
    layout = page_layout(fan, opts, load_strings(), BASE14)
    pdf = render_fan(fan, opts)
    texts = [t for t, _ in text_objects(pdf)]
    labels = [f"{entry.label} ({entry.count})" for entry in fan.legend]
    assert [t for t in texts if t in labels] == labels
    assert len(layout.legend) == 30
    cx, cy = layout.center
    disc = 125 * layout.units
    lowest = cy - max(layout.radius / 2, disc)
    drawn = {run.text: run for run in runs(pdf) if run.text in labels}
    for box in layout.legend:
        assert box.text in drawn and "…" not in box.text
        assert 36 <= box.x and box.x + box.width <= layout.width - 36
        assert layout.region_bottom <= box.y
        assert box.y + box.height < cy - disc
        if box.y + box.height > lowest:
            depth = cy - box.y - box.height
            assert (
                max(abs(box.x - cx), abs(box.x + box.width - cx))
                <= depth * math.sqrt(3) - 6
            )
        run = drawn[box.text]
        baseline = layout.height - run.y
        assert box.y <= baseline <= box.y + box.height
        assert box.x <= run.x and run.right() <= box.x + box.width + 0.01
        assert baseline > 36 + 8


def test_two_generation_fan_keeps_every_path_point_between_title_and_footer():
    fan, opts = full_fan(2), options()
    layout = page_layout(fan, opts, load_strings(), BASE14)
    stream = first_page(render_fan(fan, opts))
    # The center disc is the lowest point, below the parents' 30-degree ends.
    assert layout.center[1] - 125 * layout.units == pytest.approx(layout.region_bottom)
    points = re.findall(rb"(-?[\d.]+) (-?[\d.]+) [ml]\b", stream)
    curves = re.findall(
        rb"(-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) c\b",
        stream,
    )
    points += [(curve[i], curve[i + 1]) for curve in curves for i in range(0, 6, 2)]
    assert points
    for x, y in points:
        assert 36 - 0.01 <= float(x) <= layout.width - 36 + 0.01
        assert layout.region_bottom - 0.01 <= float(y) <= layout.region_top + 0.01


@pytest.mark.parametrize("ink", ["color", "grayscale"])
def test_text_contrast_uses_the_fill_after_fading(ink):
    fan = Fan(
        2,
        [
            FanCell(1, given="Jane Doe", fill="#202020"),
            FanCell(2, given="John Doe", fill="#202020"),
        ],
    )
    assert ("Jane Doe", (1, 1, 1)) in text_objects(render(fan, ink=ink))
    fan.highlight = {2}
    texts = text_objects(render(fan, ink=ink))
    assert ("Jane Doe", (0, 0, 0)) in texts
    assert ("John Doe", (1, 1, 1)) in texts
    if ink == "grayscale":
        # Only the highlighted parent's path is filled.
        assert (
            len(re.findall(rb"(?<!\S)B\*?(?!\S)", first_page(render(fan, ink=ink))))
            == 1
        )


def test_bw_highlight_has_twice_the_outline_width():
    fan = full_fan(2)
    fan.highlight = {1}
    stream = first_page(render(fan, ink="bw"))
    widths = [float(w) for w in re.findall(rb"([\d.]+) w", stream)]
    assert 0.5 in widths and 1.0 in widths
    assert all(color == (0, 0, 0) for _, color in text_objects(render(fan, ink="bw")))


def test_repeat_marks_draw_on_both_copies():
    fan = full_fan(3)
    fan.cells[3].copies = fan.cells[6].copies = 2
    assert [t for t, _ in text_objects(render(fan))].count("×2") == 2


def test_render_checks_the_fan_before_options_or_drawing():
    with pytest.raises(ValueError, match="generations"):
        render(Fan(1, []), paper="bad")


@pytest.mark.parametrize(
    "kwargs,field", [({"ink": "bad"}, "ink"), ({"paper": "bad"}, "paper")]
)
def test_bad_options_name_the_field(kwargs, field):
    with pytest.raises(ValueError, match=field):
        render(**kwargs)


def test_positional_options_match_the_caller_contract():
    opts = FanOptions("grayscale", "a3", "de")
    assert (opts.ink, opts.paper, opts.lang) == ("grayscale", "a3", "de")


@pytest.mark.parametrize("generations", range(2, 8))
@pytest.mark.parametrize("ink", ["color", "grayscale", "bw"])
def test_every_generation_and_ink_is_one_page(generations, ink):
    assert count_pages(render(full_fan(generations), ink=ink)) == 1


def test_legend_that_cannot_fit_names_the_entry_count():
    fan = full_fan()
    fan.legend = [LegendEntry("W" * 1000, None, 1)]
    with pytest.raises(ValueError, match=r"1.*legend|legend.*1"):
        render(fan)


def test_text_objects_join_arc_glyphs_and_restore_saved_colors():
    from kincade.pdf import draw_text, new_canvas

    buf, c = new_canvas(792, 612, False, BASE14)
    c.setFillColorRGB(1, 0, 0)
    c.saveState()
    c.setFillGray(0.5)
    draw_text(c, 40, 40, "Gray (inside)", BASE14.sans, 9)
    c.restoreState()
    draw_text(c, 40, 60, "Red", BASE14.sans, 9)
    c.showPage()
    c.save()
    assert ("Gray (inside)", (0.5, 0.5, 0.5)) in text_objects(buf.getvalue())
    assert ("Red", (1, 0, 0)) in text_objects(buf.getvalue())
    # The parent's arc has many glyph Tj operators but one joined line.
    assert ("Jane Doe", (0, 0, 0)) in text_objects(render(full_fan(2)))


def test_text_matrices_follow_nested_canvas_transforms_and_restore_state():
    from kincade.pdf import draw_text, new_canvas

    from pdfread import text_matrix_objects

    buf, c = new_canvas(792, 612, False, BASE14)
    c.saveState()
    c.translate(100, 200)
    c.saveState()
    c.rotate(90)
    c.translate(10, 20)
    t = c.beginText()
    t.setFont(BASE14.sans, 9)
    t.setHorizScale(80)
    t.setTextTransform(0, -1, 1, 0, 3, 4)
    t.textOut("Turn (q Q cm Tm) \\")
    t.setHorizScale(100)
    c.drawText(t)
    c.saveState()
    c.translate(5, 6)
    draw_text(c, 1, 2, "Nested", BASE14.sans, 9)
    c.restoreState()
    draw_text(c, 1, 2, "Rotated", BASE14.sans, 9)
    c.restoreState()
    draw_text(c, 1, 2, "Translated", BASE14.sans, 9)
    c.restoreState()
    draw_text(c, 1, 2, "Plain", BASE14.sans, 9)
    c.showPage()
    c.save()

    objects = text_matrix_objects(buf.getvalue())
    assert ["".join(run.text for run in obj) for obj in objects] == [
        "Turn (q Q cm Tm) \\",
        "Nested",
        "Rotated",
        "Translated",
        "Plain",
    ]
    expected = [
        (1, 0, 0, 1, 76, 213),
        (0, 1, -1, 0, 72, 216),
        (0, 1, -1, 0, 78, 211),
        (1, 0, 0, 1, 101, 202),
        (1, 0, 0, 1, 1, 2),
    ]
    for obj, matrix in zip(objects, expected, strict=True):
        assert len(obj) == 1
        assert obj[0].matrix == pytest.approx(matrix)
        assert obj[0].size == 9
    assert [obj[0].scale for obj in objects] == [0.8, 1, 1, 1, 1]


def test_annular_sectors_have_one_connected_boundary_and_leave_the_disc_clear():
    # A second move within a sector closes each arc separately, making diagonals
    # across the center disc instead of joining the inner and outer arc ends.
    stream = first_page(render(full_fan(3), ink="bw"))
    paths = re.findall(rb"\bn\s+(.*?)\s+S(?=\s)", stream, re.DOTALL)
    assert len(paths) == 7
    assert all(len(re.findall(rb"(?<!\S)m(?!\S)", path)) == 1 for path in paths)
    assert all(path.rstrip().endswith(b"h") for path in paths[1:])


def test_metadata_keeps_the_complete_title_when_the_page_title_is_cut():
    title = "Invented family chart " * 30
    pdf = render(title=title)
    assert b"/Title (" + title.encode() + b")" in pdf
    assert any(text.endswith("…") for text, _ in text_objects(pdf))


def test_custom_language_ellipsis_reaches_the_cut_cell_text():
    fan = full_fan()
    fan.cells[63].given = "Frederick Augustus"
    fan.cells[63].surname = "Inventedlongsurname" * 5
    texts = [text for text, _ in text_objects(render(fan, lang={"ellipsis": "~"}))]
    assert any(text.startswith("Invented") and text.endswith("~") for text in texts)
    assert not any("…" in text for text in texts)


def test_supplied_fontset_controls_the_drawn_faces_and_cleaning():
    from kincade.pdf import FontSet

    fonts = FontSet(sans="Times-Roman", bold="Times-Bold", supports=str.isascii)
    fan = Fan(2, [FanCell(1, given="Zoë Doe")], name="Zoë Doe")
    opts = options()
    opts.fonts = fonts
    pdf = render_fan(fan, opts)
    assert ("Zoe Doe", (0, 0, 0)) in text_objects(pdf)
    assert any(run.font == "Times-Roman" and run.text == "Zoe Doe" for run in runs(pdf))
    assert any(run.font == "Times-Bold" for run in runs(pdf))

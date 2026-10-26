"""The fan chart: seating ancestors from a tree, years, privacy, inks, legend, text
fitting and direction, and the one-page PDF it draws."""

import math
import re
from copy import deepcopy
from dataclasses import replace
from datetime import date
from itertools import pairwise

import pytest
from reportlab.pdfbase.pdfmetrics import getAscentDescent, stringWidth

from kincade.cli import fan_people
from kincade.fan import (
    Candidate,
    Fan,
    FanCell,
    LegendEntry,
    check_fan,
    ring_of,
    ring_radii,
    text_candidates,
)
from kincade.fanpdf import (
    FAN_PAPER,
    FanOptions,
    fit_cell,
    page_layout,
    render_fan,
    text_direction,
)
from kincade.fanplan import plan_fan
from kincade.gedcom import read_gedcom
from kincade.lang import LangError, load_strings
from kincade.model import Date, Day, Event, Family, ParentLink, Person, Tree
from kincade.pdf import BASE14

from conftest import FIX, TODAY, full_pedigree, ged
from pdfread import _text, count_pages, runs, streams, text_matrix_objects


def root_years(person, **options):
    """The root's written years, for a one-person tree."""
    return plan_fan(Tree({person.id: person}), person.id, **options).cells[0].years


def colored_texts(pdf, page=0):
    """Each BT … ET object's joined Tj text and RGB fill color, in drawing order."""
    token = re.compile(
        rb"\((?P<text>(?:\\.|[^\\)])*)\)\s*Tj"
        rb"|(?P<rgb>[-\d.]+\s+[-\d.]+\s+[-\d.]+)\s+rg\b"
        rb"|(?P<gray>[-\d.]+)\s+g\b"
        rb"|(?<!\S)(?P<op>q|Q|BT|ET)(?!\S)",
        re.DOTALL,
    )
    color, stack, joined, out = (0, 0, 0), [], [], []
    for match in token.finditer(streams(pdf)[page]):
        if match["text"] is not None:
            joined.append(_text(match["text"]))
        elif match["rgb"]:
            color = tuple(map(float, match["rgb"].split()))
        elif match["gray"]:
            gray = float(match["gray"])
            color = (gray, gray, gray)
        elif match["op"] == b"q":
            stack.append(color)
        elif match["op"] == b"Q":
            color = stack.pop()
        elif match["op"] == b"BT":
            joined = []
        elif match["op"] == b"ET":
            out.append(("".join(joined), color))
    return out


def full_fan(generations=7):
    """Every slot filled with the same invented person, for drawing checks that do not
    care which ancestors are known."""
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


def fan_options(**kwargs):
    return FanOptions(today=TODAY, fonts="base14", compress=False, **kwargs)


def render(fan=None, **kwargs):
    return render_fan(fan if fan is not None else full_fan(), fan_options(**kwargs))


def cell_drawings(pdf):
    """Saved graphics states with a cell outline, its path and paint operator."""
    return re.findall(
        rb"\bq\s+([\d. ]+ RG)\s+([\d.]+ w)\s+(.*?)\s+Q\b", streams(pdf)[0], re.DOTALL
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


@pytest.fixture
def fan_geometry():
    """The seven-generation letter-size layout the fit tests measure against."""
    return page_layout(Fan(7, []), FanOptions(), load_strings(), BASE14)


@pytest.fixture(scope="module")
def drawn_fan_cells():
    """A seven-generation fan with one named cell per slot, drawn once; its text
    matrices, keyed by cell name, and the layout they were drawn against."""
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
            assert sign * (previous[0] * radial[1] - previous[1] * radial[0]) > 0
        previous = radial


def test_plan_fan_of_the_fixtures():
    """plan_fan on several invented and fixture trees: full seating, a sparse family, a
    step-parent, a shared-ancestor collapse and a self-ancestor cycle."""
    # Every generation known: slots 1 to 63 in order; the root keeps its prefix and
    # suffix, and the father is in slot 2.
    tree = full_pedigree(7)
    root = tree.people["I1"]
    root.prefix, root.given, root.surname, root.suffix = (
        "Rev.",
        "Jane Ann",
        "Doe",
        "Jr.",
    )
    fan = plan_fan(tree, "I1")
    assert fan.generations == 6 and len(fan.cells) == 63
    assert [cell.slot for cell in fan.cells] == list(range(1, 64))
    assert (
        fan.cells[0].title,
        fan.cells[0].given,
        fan.cells[0].surname,
        fan.cells[0].suffix,
    ) == ("Rev.", "Jane Ann", "DOE", "Jr.")
    assert fan.cells[1].slot == 2 and fan.cells[1].given == "Person2"

    # A sparse family seats only known people and their immediately missing parents;
    # unknown grandparents add no deeper cells.
    sparse = Tree(
        {
            "jane": Person(
                "jane", given="Jane", surname="Doe", parents=[ParentLink("f1")]
            ),
            "john": Person("john", given="John", surname="Doe"),
        },
        {"f1": Family("f1", "john", "", children=["jane"])},
    )
    sparse_fan = plan_fan(sparse, "jane", generations=7)
    assert [(c.slot, c.given, c.empty) for c in sparse_fan.cells] == [
        (1, "Jane", False),
        (2, "John", False),
        (3, "", True),
        (4, "", True),
        (5, "", True),
    ]
    check_fan(sparse_fan)

    # A step-parent's cell is empty even when their own ancestors are known.
    step_tree = full_pedigree(4)
    step_tree.people["I1"].parents[0].father = "step"
    step_fan = plan_fan(step_tree, "I1", generations=3)
    assert [(c.slot, c.empty) for c in step_fan.cells] == [
        (1, False),
        (2, True),
        (3, False),
        (6, False),
        (7, False),
    ]

    # collapse.ged: a shared ancestor seats a copy on each path, but fan_people
    # counts the distinct person once.
    collapse = read_gedcom(FIX / "collapse.ged")
    collapse_fan = plan_fan(collapse, "I1", generations=4)
    assert [(c.slot, c.copies) for c in collapse_fan.cells if c.given == "Lou"] == [
        (4, 2),
        (6, 2),
    ]
    assert fan_people(collapse_fan) == 8

    # cycle.ged: a person who is their own ancestor still stops at the requested ring.
    cyclic = read_gedcom(FIX / "cycle.ged")
    cyclic_fan = plan_fan(cyclic, "I1", generations=7)
    assert cyclic_fan.generations == 7
    assert max(c.slot for c in cyclic_fan.cells) == 65
    assert all(c.slot < 2**7 for c in cyclic_fan.cells)


def test_plan_fan_refuses_bad_arguments():
    with pytest.raises(KeyError, match="absent"):
        plan_fan(Tree(), "absent")
    for generations in (1, 8, True, "6", 6.0):
        with pytest.raises(ValueError) as error:
            plan_fan(Tree({"jane": Person("jane")}), "jane", generations=generations)
        assert "generations" in str(error.value), generations
        assert repr(generations) in str(error.value), generations
    for ink in ("gray", "", "COLOR"):
        with pytest.raises(ValueError) as error:
            plan_fan(Tree({"jane": Person("jane")}), "jane", ink=ink)
        assert "ink" in str(error.value), ink
        assert repr(ink) in str(error.value), ink
    for lang in ("zz", {"years": {"about": "{year}"}}):
        with pytest.raises(LangError):
            plan_fan(Tree({"jane": Person("jane")}), "jane", lang=lang)


FAN_YEAR_CASES = {
    "born_and_died": [
        (
            Person(
                "jane",
                birth=Event(Date("exact", Day(1820))),
                death=Event(Date("exact", Day(1891))),
            ),
            "1820–1891",
            "1820–1891",
        ),
    ],
    "born_abt": [
        (
            Person("jane", birth=Event(Date("about", Day(1820)))),
            "abt 1820–",
            "* um 1820",
        ),
    ],
    "double_year": [
        (
            Person("jane", birth=Event(Date("exact", Day(1730, dual_year=1731)))),
            "1730/31–",
            "* 1730/31",
        ),
    ],
    "death_year_and_undated_death": [
        (
            Person("jane", death=Event(Date("exact", Day(1891)))),
            "–1891",
            "† 1891",
        ),
        (Person("jane", death=Event()), "–Deceased", "–verstorben"),
    ],
    "christening_and_burial_standins": [
        (
            Person("jane", christenings=[Event(Date("exact", Day(1852)))]),
            "chr 1852–",
            "get. 1852–",
        ),
        (
            Person(
                "jane",
                birth=Event(Date("about", Day(1820))),
                burials=[Event(Date("exact", Day(1871)))],
            ),
            "abt 1820–bur 1871",
            "um 1820–begr. 1871",
        ),
    ],
}


@pytest.mark.parametrize("name", list(FAN_YEAR_CASES))
def test_fan_years(name):
    """Fan years fill the language's lifespan, born_only and died_only templates, in
    both English and German."""
    for person, en, de in FAN_YEAR_CASES[name]:
        assert root_years(person) == en, (name, en)
        assert root_years(person, lang="de") == de, (name, de)
    if name == "christening_and_burial_standins":
        # event_standins=False ignores the stand-in years.
        bare = Person("jane", christenings=[Event(Date("exact", Day(1852)))])
        assert root_years(bare, event_standins=False) == ""
        assert root_years(bare, event_standins=False, lang="de") == ""


def test_plan_fan_options():
    """exclude_private, adoptive_parents, ink and preserve_case, each checked on a
    small tree."""
    # exclude_private hides names and years and follows Person.living, using the
    # unlimited pedigree estimate even for a two-generation fan.
    for living, hidden in ((None, True), (True, True), (False, False)):
        person = Person(
            "jane",
            given="Jane",
            surname="Doe",
            birth=Event(Date("exact", Day(date.today().year - 20))),
            living=living,
        )
        tree = Tree({"jane": person})
        shown = plan_fan(tree, "jane").cells[0]
        private = plan_fan(tree, "jane", exclude_private=True).cells[0]
        assert private.given == ("Living" if hidden else "Jane"), living
        assert private.surname == ("" if hidden else "DOE"), living
        assert private.years == ("" if hidden else shown.years), living
        assert shown.years != "", living

    override = Person(
        "jane",
        birth=Event(Date("exact", Day(1820))),
        death=Event(Date("exact", Day(1891))),
        living=True,
    )
    assert root_years(override, exclude_private=True) == ""

    unlimited = full_pedigree(4)
    unlimited.families["F3"].mother = "I2"
    unlimited.people["I6"].birth = Event(Date("exact", Day(1800)))
    unlimited.people["I6"].parents = [ParentLink("older")]
    unlimited.families["older"] = Family("older", "I2", "")
    unlimited.people["I2"].birth = Event(Date("from", Day(1700)))
    unlimited_fan = plan_fan(unlimited, "I1", generations=2, exclude_private=True)
    assert unlimited_fan.cells[1].years == "aft 1700–"

    # adoptive_parents selects the adoptive family instead of the birth family.
    adopt_tree = Tree(
        {
            "jane": Person(
                "jane",
                given="Jane",
                parents=[
                    ParentLink("adopted", "adopted", "adopted"),
                    ParentLink("birth"),
                ],
            ),
            "john": Person("john", given="John"),
            "june": Person("june", given="June"),
            "jack": Person("jack", given="Jack"),
            "joan": Person("joan", given="Joan"),
        },
        {
            "birth": Family("birth", "john", "june"),
            "adopted": Family("adopted", "jack", "joan"),
        },
    )
    assert [c.given for c in plan_fan(adopt_tree, "jane", generations=2).cells] == [
        "Jane",
        "John",
        "June",
    ]
    assert [
        c.given
        for c in plan_fan(
            adopt_tree, "jane", generations=2, adoptive_parents=True
        ).cells
    ] == ["Jane", "Jack", "Joan"]

    # Ink colors the center, the sides and each grandparent line; bw has no fills.
    ink_tree = full_pedigree(4)
    by_ink = {
        "color": [
            "#f7f8fa",
            "#e1e7ef",
            "#f1e3e8",
            "#cddff4",
            "#d3ecd9",
            "#f6e3bf",
            "#f5d2dd",
        ],
        "grayscale": [None, None, None, "#c8c8c8", "#a6a6a6", "#e4e4e4", "#b8b8b8"],
        "bw": [None] * 7,
    }
    for ink, expected in by_ink.items():
        fan = plan_fan(ink_tree, "I1", generations=4, ink=ink)
        assert [c.fill for c in fan.cells[:7]] == expected, ink
    assert all(
        c.fill is None
        for c in plan_fan(full_pedigree(7), "I1", generations=7, ink="bw").cells
    )

    # preserve_case reaches the cells, the fan name and the drawn metadata, without
    # mutating the tree.
    case_tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Alice /McClure/", "1 DEAT Y"))
    original = deepcopy(case_tree)
    for preserve, surname in ((False, "McCLURE"), (True, "McClure")):
        fan = plan_fan(case_tree, "I1", preserve_case=preserve)
        assert fan.cells[0].surname == surname, preserve
        assert fan.name == f"Alice {surname}", preserve
        pdf = render_fan(fan, FanOptions(fonts="base14", compress=False))
        strings = [text for text, _ in colored_texts(pdf)]
        assert fan.name in strings, preserve
        assert f"{fan.name} — Fan chart" in strings, preserve
        assert fan.name in _text(pdf), preserve
    assert case_tree == original


@pytest.mark.parametrize(
    "paper,generations,ink",
    [
        ("letter", 2, "color"),
        ("a4", 4, "grayscale"),
        ("tabloid", 6, "bw"),
        ("a3", 7, "color"),
    ],
)
def test_render_fan_pages(pedigree, paper, generations, ink):
    """One landscape page, every path point inside the margins, a legend that fits
    whole, and the title and metadata."""
    fan = plan_fan(pedigree, "I1", generations=generations, ink=ink)
    fan.legend = [
        LegendEntry(f"Invented location number {i:02d}", "#cddff4", i)
        for i in range(30)
    ]
    opts = fan_options(paper=paper, ink=ink)
    layout = page_layout(fan, opts, load_strings(), BASE14)
    pdf = render_fan(fan, opts)

    assert count_pages(pdf) == 1
    width, height = FAN_PAPER[paper]
    media = re.search(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
    assert tuple(map(float, media.groups())) == (width, height)

    stream = streams(pdf)[0]
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

    texts = [t for t, _ in colored_texts(pdf)]
    labels = [f"{entry.label} ({entry.count})" for entry in fan.legend]
    if ink == "bw":
        # bw draws no legend at all.
        assert not any(t in labels for t in texts)
        assert layout.legend == ()
    else:
        assert [t for t in texts if t in labels] == labels
        assert len(layout.legend) == 30
        cx, cy = layout.center
        disc = 125 * layout.units
        lowest = cy - max(layout.radius / 2, disc)
        drawn_runs = {run.text: run for run in runs(pdf) if run.text in labels}
        for box in layout.legend:
            assert box.text in drawn_runs and "…" not in box.text, box.text
            assert 36 <= box.x and box.x + box.width <= layout.width - 36, box.text
            assert layout.region_bottom <= box.y, box.text
            assert box.y + box.height < cy - disc, box.text
            if box.y + box.height > lowest:
                depth = cy - box.y - box.height
                assert (
                    max(abs(box.x - cx), abs(box.x + box.width - cx))
                    <= depth * math.sqrt(3) - 6
                ), box.text
            run = drawn_runs[box.text]
            baseline = layout.height - run.y
            assert box.y <= baseline <= box.y + box.height, box.text
            assert box.x <= run.x and run.right() <= box.x + box.width + 0.01, box.text

    assert "Jane ASHFORD — Fan chart" in texts

    long_title = "Invented family chart " * 30
    cut_pdf = render_fan(fan, replace(opts, title=long_title))
    assert (b"/Title (" + long_title.encode() + b")") in cut_pdf
    assert any(text.endswith("…") for text, _ in colored_texts(cut_pdf))


def test_every_position_is_outlined():
    """A full known fan has no dashed outlines; planned missing ancestors and a
    caller-supplied sparse fan get dashed outlines at the right positions."""
    for generations in (2, 7):
        pdf = render(full_fan(generations))
        drawings = cell_drawings(pdf)
        assert len(drawings) == 2**generations - 1, generations
        assert not any(b" 0 d" in path for _, _, path in drawings), generations

    for generations in range(2, 8):
        fan = plan_fan(
            Tree({"jane": Person("jane", given="Jane", surname="Doe")}),
            "jane",
            generations=generations,
        )
        before = deepcopy(fan)
        pdf = render(fan)
        drawings = cell_drawings(pdf)
        assert len(drawings) == 2**generations - 1, generations
        assert_blank_outlines(drawings, 2**generations - 2)
        assert [t for t, _ in colored_texts(pdf) if t] == [
            "Jane DOE — Fan chart",
            "Created 10 Oct 2026 using Kincade",
            "Jane DOE",
        ], generations
        assert fan == before, generations

    sparse = Fan(
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
    before = deepcopy(sparse)
    for ink in ("color", "grayscale", "bw"):
        pdf = render(sparse, ink=ink)
        drawings = cell_drawings(pdf)
        assert len(drawings) == 7, ink
        assert_blank_outlines(drawings, 5)
        known = [drawing for drawing in drawings if b" 0 d" not in drawing[2]]
        assert len(known) == 2, ink
        texts = colored_texts(pdf)
        assert "Hidden" not in [t for t, _ in texts], ink
        assert ("Jane", (0, 0, 0)) in texts, ink
        assert ("John", (0, 0, 0) if ink == "bw" else (1, 1, 1)) in texts, ink
        assert ("Family (2)" in [t for t, _ in texts]) == (ink != "bw"), ink
    assert sparse == before


def test_legend_highlight_and_contrast():
    """Legend order, counts and colors; the bw highlight's doubled outline; text
    contrast after fading; and a legend that will not fit."""
    fan = full_fan()
    fan.legend = [
        LegendEntry("North", "#ff0000", 2),
        LegendEntry("South", "#00ff00", 3),
        LegendEntry("Unknown", None, 4),
    ]
    pdf = render(fan)
    texts = colored_texts(pdf)
    assert [t for t, _ in texts if t in {"North (2)", "South (3)", "Unknown (4)"}] == [
        "North (2)",
        "South (3)",
        "Unknown (4)",
    ]
    stream = streams(pdf)[0]
    assert b"1 0 0 rg" in stream and b"0 1 0 rg" in stream
    assert not any("North" in t for t, _ in colored_texts(render()))

    highlighted = full_fan(2)
    highlighted.highlight = {1}
    bw_stream = streams(render(highlighted, ink="bw"))[0]
    widths = [float(w) for w in re.findall(rb"([\d.]+) w", bw_stream)]
    assert 0.5 in widths and 1.0 in widths
    assert all(
        color == (0, 0, 0) for _, color in colored_texts(render(highlighted, ink="bw"))
    )

    for ink in ("color", "grayscale"):
        contrast = Fan(
            2,
            [
                FanCell(1, given="Jane Doe", fill="#202020"),
                FanCell(2, given="John Doe", fill="#202020"),
            ],
        )
        assert ("Jane Doe", (1, 1, 1)) in colored_texts(render(contrast, ink=ink)), ink
        contrast.highlight = {2}
        texts = colored_texts(render(contrast, ink=ink))
        assert ("Jane Doe", (0, 0, 0)) in texts, ink
        assert ("John Doe", (1, 1, 1)) in texts, ink
        if ink == "grayscale":
            stream = streams(render(contrast, ink=ink))[0]
            assert len(re.findall(rb"(?<!\S)B\*?(?!\S)", stream)) == 1

    overflow = full_fan()
    overflow.legend = [LegendEntry("W" * 1000, None, 1)]
    with pytest.raises(ValueError, match=r"1.*legend|legend.*1"):
        render(overflow)


def test_render_fan_checks_the_fan_first():
    """check_fan's errors reach the caller before any drawing, and bad FanOptions name
    their field."""
    cases = [
        (Fan(8, [FanCell(1)]), "generations"),
        (Fan(3, [FanCell(1), FanCell(0)]), "slot"),
        (Fan(3, [FanCell(1), FanCell(64)]), "slot"),
        (Fan(3, [FanCell(1), FanCell(1)]), "slot"),
        (Fan(3, [FanCell(1), FanCell(2, empty=True), FanCell(4)]), "child"),
        (Fan(2, [FanCell(1, fill="red")]), "fill"),
        (Fan(2, [FanCell(1)], [LegendEntry("Doe", "red", 1)]), "legend"),
        (Fan(2, [FanCell(1)], highlight={2}), "highlight"),
    ]
    for fan, field in cases:
        with pytest.raises(ValueError, match=field) as error:
            render(fan)
        assert field in str(error.value), field

    with pytest.raises(ValueError, match="generations"):
        render(Fan(1, []), paper="bad")

    for kwargs, field in (({"ink": "bad"}, "ink"), ({"paper": "bad"}, "paper")):
        with pytest.raises(ValueError, match=field):
            render(**kwargs)


def test_every_slot_draws_its_text_in_its_direction(drawn_fan_cells):
    """Every slot of a seven-generation fan draws level, radial or arc text matrices
    matching its ring and direction; ring-3 end labels follow the neighboring arcs, and
    lines are drawn in reading order."""
    layout, cells = drawn_fan_cells
    for slot in range(1, 128):
        slot_runs = cells[f"Slot{slot:03}"]
        direction = text_direction(slot)
        ring = ring_of(slot)
        inner, outer = (radius * layout.units for radius in ring_radii(ring))
        cx, cy = layout.center
        if direction == "level":
            assert len(slot_runs) == 1, slot
            a, b, c, d, x, y = slot_runs[0].matrix
            assert (a, b, c, d) == pytest.approx((1, 0, 0, 1)), slot
            assert math.hypot(x - cx, y - cy) < outer, slot
            continue
        count = 2**ring
        middle = math.radians(210 - (slot - count + 0.5) * 240 / count)
        ray = (math.cos(middle), math.sin(middle))
        if direction in ("outward", "inward"):
            assert len(slot_runs) == 1, slot
            a, b, c, d, x, y = slot_runs[0].matrix
            sign = 1 if direction == "outward" else -1
            baseline = (sign * ray[0], sign * ray[1])
            assert (a, b, c, d) == pytest.approx(
                (*baseline, -baseline[1], baseline[0]), abs=1e-5
            ), slot
            width = (
                stringWidth(slot_runs[0].text, BASE14.sans, slot_runs[0].size)
                * slot_runs[0].scale
            )
            dx, dy = x + width / 2 * a - cx, y + width / 2 * b - cy
            assert inner < dx * ray[0] + dy * ray[1] < outer, slot
            continue
        assert len(slot_runs) == len(f"Slot{slot:03}"), slot
        assert_arc_line_reading_frame(slot_runs, layout, slot, direction)

    for generations in range(4, 8):
        for slot, given in (
            (8, "Albert"),
            (9, "Jane"),
            (14, "Peter"),
            (15, "Catherine"),
        ):
            for multiline in (False, True):
                cell = FanCell(
                    slot,
                    given=given,
                    surname="Doe" if multiline else "",
                    years="1820–1891" if multiline else "",
                    copies=2 if multiline else 1,
                )
                opts = fan_options(title="Arc labels", footer=False)
                label_cells = [cell]
                ancestor = slot // 2
                while ancestor:
                    label_cells.append(FanCell(ancestor))
                    ancestor //= 2
                fan = Fan(generations, label_cells)
                label_layout = page_layout(fan, opts, load_strings(), BASE14)
                objects = [
                    obj
                    for obj in text_matrix_objects(render_fan(fan, opts))
                    if "".join(run.text for run in obj) != "Arc labels"
                ]
                expected = [f"{given} Doe", "1820–1891", "×2"] if multiline else [given]
                label = (generations, slot, multiline)
                assert [
                    "".join(run.text for run in obj) for obj in objects
                ] == expected, label
                radii = []
                cx, cy = label_layout.center
                inner, outer = (r * label_layout.units for r in (300, 425))
                middle = math.radians({8: 195, 9: 165, 14: 15, 15: -15}[slot])
                for obj in objects:
                    font = (
                        BASE14.bold
                        if "".join(run.text for run in obj) == "×2"
                        else BASE14.sans
                    )
                    assert_arc_line_reading_frame(
                        obj, label_layout, slot, "clockwise", font
                    )
                    for run in obj:
                        a, b, c, d, x, y = run.matrix
                        width = stringWidth(run.text, font, run.size) * run.scale
                        ascent, descent = getAscentDescent(font, run.size)
                        for along in (0, width):
                            for up in (descent, ascent):
                                dx = x + along * a + up * c - cx
                                dy = y + along * b + up * d - cy
                                assert inner < math.hypot(dx, dy) < outer, label
                                angle = math.atan2(dy, dx) - middle
                                angle = (angle + math.pi) % (2 * math.pi) - math.pi
                                assert abs(angle) < math.radians(15), label
                    run = obj[0]
                    radii.append(math.hypot(run.matrix[4] - cx, run.matrix[5] - cy))
                if multiline:
                    assert radii[2] > radii[0] > radii[1], label

    for given in ("Jane", "Jane Annabelle"):
        for slot, direction, split in (
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
        ):
            order_cells = [FanCell(slot, given=given, surname="Doe", years="1820–1891")]
            ancestor = slot // 2
            while ancestor:
                order_cells.append(FanCell(ancestor))
                ancestor //= 2
            fan = Fan(7, order_cells)
            opts = fan_options(title="Invented fan", footer=False)
            order_layout = page_layout(fan, opts, load_strings(), BASE14)
            objects = [
                obj
                for obj in text_matrix_objects(render_fan(fan, opts))
                if "".join(run.text for run in obj) != "Invented fan"
            ]
            expected = (
                (given, "Doe", "1820–1891")
                if split and given == "Jane Annabelle"
                else (f"{given} Doe", "1820–1891")
            )
            label = (given, slot)
            assert (
                tuple("".join(run.text for run in obj) for obj in objects) == expected
            ), label
            cx, cy = order_layout.center
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
                    assert_arc_line_reading_frame(obj, order_layout, slot, direction)
                    advance = stringWidth(run.text, BASE14.sans, run.size) * run.scale
                    radius = math.hypot(
                        x + advance / 2 * a - cx, y + advance / 2 * b - cy
                    )
                    positions.append(radius if direction == "clockwise" else -radius)
                else:
                    positions.append((x - cx) * up[0] + (y - cy) * up[1])
            assert all(first > second for first, second in pairwise(positions)), label


def test_cell_text_gives_way_in_order(fan_geometry):
    """The six candidate stages, in the order fitting tries them, and how fitting gives
    way in the outer ring, with a language ellipsis, a copy mark and the type size."""
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

    def fitted(cell, ellipsis="…"):
        return fit_cell(cell, fan_geometry, BASE14, ellipsis)

    initials = fitted(
        FanCell(64, given="Frederick Augustus", surname="Strickland", years="1820–1891")
    )
    assert [line.text for line in initials] == ["Frederick A. Strickland", "1820–1891"]
    cut = fitted(
        FanCell(
            64,
            given="Frederick Augustus Bartholomew",
            surname="Strickland",
            suffix="Jr.",
            years="1820–1891",
        )
    )
    assert [line.text for line in cut] == ["Frederick A. B.", "Strickland, Jr."]

    for ellipsis in ("…", "~"):
        long_name = fitted(
            FanCell(
                64,
                given="Frederick Augustus",
                surname="Inventedlongsurname" * 5,
                years="1820–1891",
            ),
            ellipsis,
        )
        assert long_name[-1].text.endswith(ellipsis), ellipsis
        assert all("1820" not in line.text for line in long_name), ellipsis
    tight = replace(fan_geometry, text_sizes=(10000,) * 7)
    assert fit_cell(FanCell(64, surname="Doe"), tight, BASE14, "…") is None

    marked_cell = FanCell(
        64,
        given="Frederick Augustus Bartholomew",
        surname="Strickland",
        years="1820–1891",
    )
    plain = fitted(marked_cell)
    marked = fitted(replace(marked_cell, copies=2))
    assert [line.text for line in plain] == ["Frederick A. B. Strickland", "1820–1891"]
    assert [line.text for line in marked] == ["Frederick A. B.", "Strickland"]

    center = fitted(FanCell(1, surname="Doe"))[0]
    outer = fitted(FanCell(64, surname="Doe"))[0]
    assert center.size == pytest.approx(9, abs=0.3)
    assert outer.size == pytest.approx(6.6, abs=0.3)


def test_fan_title_footer_and_language():
    """The default footer, footer=False, an override, German title and year words, and
    a custom title and footer fitted with a custom ellipsis."""
    pdf = render()
    texts = [t for t, _ in colored_texts(pdf)]
    assert "Jane Doe — Fan chart" in texts
    assert "Created 10 Oct 2026 using Kincade" in texts

    overridden = [
        t for t, _ in colored_texts(render(title="My fan", footer="My footer"))
    ]
    assert "My fan" in overridden and "My footer" in overridden
    assert not any(
        t.startswith("Created") for t, _ in colored_texts(render(footer=False))
    )
    assert "Fächerahnentafel — Jane Doe" in [
        t for t, _ in colored_texts(render(lang="de"))
    ]

    custom = render(title="T" * 400, footer="F" * 400, lang={"ellipsis": "~"})
    cut_runs = [run for run in runs(custom) if run.text.startswith(("T", "F"))]
    assert cut_runs  # the long title and footer are actually drawn and cut
    for run in cut_runs:
        assert run.text.endswith("~"), run.text
        assert run.x >= 36 - 0.01 and run.right() <= 756 + 0.01, run.text

"""The fan a caller supplies: its cells, legend, checks, ring geometry and text
candidates. This module imports nothing of Kincade's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import NamedTuple

RING_DEPTHS = (125, 88, 87, 125, 160, 190, 225)  # ring 0: the center's radius
RING_TEXT_SIZES = (27, 26, 25, 23, 21.5, 20.5, 19.5)  # same units as the depths
SPAN = 240  # degrees the fan opens, centered on straight up
FATHER_EDGE = 210  # degrees counterclockwise from 3 o'clock: the fan's left end

_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass
class FanCell:
    """One Ahnentafel slot, with its name parts, written years, fill and copy count."""

    slot: int
    empty: bool = False
    title: str = ""
    given: str = ""
    surname: str = ""
    suffix: str = ""
    years: str = ""
    fill: str | None = None
    copies: int = 1


@dataclass
class LegendEntry:
    """A legend label, swatch color (None for an outline) and count, in display order."""

    label: str
    color: str | None
    count: int


@dataclass
class Fan:
    """Everything the family contributes to a fan page, counting the center as 1."""

    generations: int
    cells: list[FanCell]
    legend: list[LegendEntry] = field(default_factory=list)
    highlight: set[int] = field(default_factory=set)
    name: str = ""


def check_fan(fan: Fan) -> None:
    """Refuse invalid generations, slots, child links, colors or highlight slots.
    Each ValueError names the field and value that cannot be drawn.
    """
    if type(fan.generations) is not int or not 2 <= fan.generations <= 7:
        raise ValueError(
            f"generations must be an integer from 2 to 7, not {fan.generations!r}"
        )
    cells: dict[int, FanCell] = {}
    for cell in fan.cells:
        if type(cell.slot) is not int or not 1 <= cell.slot < 2**fan.generations:
            raise ValueError(
                f"slot must be an integer from 1 to {2**fan.generations - 1}, not {cell.slot!r}"
            )
        if cell.slot in cells:
            raise ValueError(f"slot {cell.slot!r} is given twice")
        cells[cell.slot] = cell
        _check_color(f"slot {cell.slot!r} fill", cell.fill)
    for cell in fan.cells:
        if cell.slot == 1:
            continue
        child_slot = cell.slot // 2
        child = cells.get(child_slot)
        if child is None or child.empty:
            problem = "missing" if child is None else "empty"
            raise ValueError(
                f"slot {cell.slot!r} has child slot {child_slot!r} {problem}"
            )
    for entry in fan.legend:
        _check_color(f"legend {entry.label!r} color", entry.color)
    for slot in fan.highlight:
        if slot not in cells:
            raise ValueError(f"highlight slot {slot!r} has no cell")


def _check_color(field: str, color: object) -> None:
    if color is not None and (
        not isinstance(color, str) or not _COLOR.fullmatch(color)
    ):
        raise ValueError(f"{field} must be #rrggbb or None, not {color!r}")


def ring_of(slot: int) -> int:
    """The zero-based ring of a slot: the center is ring 0, the parents ring 1."""
    return slot.bit_length() - 1


def ring_radii(ring: int) -> tuple[int, int]:
    """The ring's (inner, outer) radii in units of the seven-generation radius."""
    inner = sum(RING_DEPTHS[:ring])
    return inner, inner + RING_DEPTHS[ring]


def fan_radius(generations: int) -> int:
    """The outer radius of a fan, with the center counted as generation 1."""
    return ring_radii(generations - 1)[1]


def cell_angles(slot: int) -> tuple[float, float]:
    """(Start, end) degrees from 3 o'clock, start counterclockwise of end.
    Every ring spans 240 degrees, with the father's side on the left.
    """
    n = 2 ** ring_of(slot)
    start = FATHER_EDGE - SPAN * (slot - n) / n
    return start, start - SPAN / n


def middle_angle(slot: int) -> float:
    """The cell's middle angle in degrees counterclockwise from 3 o'clock."""
    start, end = cell_angles(slot)
    return (start + end) / 2


def _with_suffix(name: str, suffix: str) -> str:
    suffix = " ".join(suffix.split())
    if not name or not suffix:
        return name or suffix
    return name + suffix if suffix.startswith(",") else f"{name}, {suffix}"


def full_name(cell: FanCell) -> str:
    """Title, given names and surname, single-spaced, then a comma and suffix.
    A suffix that starts with a comma keeps its own. Name case stays as supplied.
    """
    name = " ".join(f"{cell.title} {cell.given} {cell.surname}".split())
    return _with_suffix(name, cell.suffix)


def name_lines(cell: FanCell, initials: bool = False) -> tuple[str, str]:
    """(Title and given names, surname and suffix), with optional given initials."""
    given = with_initials(cell.given) if initials else cell.given
    first = " ".join(f"{cell.title} {given}".split())
    return first, _with_suffix(" ".join(cell.surname.split()), cell.suffix)


def with_initials(given: str) -> str:
    """Keep the first given name and initial each later one at its first letter.
    A name with no letter stays as supplied. Whitespace becomes single spaces.
    """
    names = given.split()
    for i in range(1, len(names)):
        letter = next((ch for ch in names[i] if ch.isalpha()), None)
        if letter is not None:
            names[i] = letter + "."
    return " ".join(names)


def mark_text(copies: int) -> str:
    """The copy mark, such as ×2; no mark for fewer than two copies."""
    return f"×{copies}" if copies >= 2 else ""


class Candidate(NamedTuple):
    """Lines to try in order, with permission to condense or cut each line to fit."""

    lines: tuple[str, ...]
    squeeze: bool
    cut: bool


def text_candidates(cell: FanCell) -> list[Candidate]:
    """Name and year lines, then condensed forms, initials, no years and cut forms.
    Empty lines and exact repeated candidates are omitted, keeping the first.
    Empty cells have no text.
    """
    if cell.empty:
        return []
    name = full_name(cell)
    first, surname = name_lines(cell)
    initial_first, _ = name_lines(cell, initials=True)
    initial_name = full_name(replace(cell, given=with_initials(cell.given)))
    years = cell.years
    forms = [
        Candidate((name, years), False, False),
        Candidate((first, surname, years), False, False),
        Candidate((name, years), True, False),
        Candidate((first, surname, years), True, False),
        Candidate((initial_name, years), True, False),
        Candidate((initial_first, surname, years), True, False),
        Candidate((name,), True, False),
        Candidate((first, surname), True, False),
        Candidate((initial_name,), True, False),
        Candidate((initial_first, surname), True, False),
        Candidate((initial_first, surname), True, True),
        Candidate((surname or initial_first,), True, True),
    ]
    out = []
    for form in forms:
        candidate = Candidate(
            tuple(line for line in form.lines if line),
            form.squeeze,
            form.cut,
        )
        if candidate.lines and candidate not in out:
            out.append(candidate)
    return out

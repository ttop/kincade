"""Plan a fan from a tree: seat ancestors, count copies, write years and color lines.
No drawing; imports the model, chart planning, language and fan data.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

from .charts import (
    birth_source,
    death_source,
    living_checker,
    nobody_living,
    plan_charts,
)
from .fan import Fan, FanCell, full_name, ring_of
from .lang import (
    PLACEHOLDERS,
    SortRules,
    fill,
    fmt_surname,
    format_date,
    load_strings,
)
from .model import Date, Day, Event, Person, Tree

LINE_COLORS: dict[str, dict[str | int, str | None]] = {
    "color": {
        "center": "#f7f8fa",
        "father": "#e1e7ef",
        "mother": "#f1e3e8",
        4: "#cddff4",
        5: "#d3ecd9",
        6: "#f6e3bf",
        7: "#f5d2dd",
    },
    "grayscale": {
        "center": None,
        "father": None,
        "mother": None,
        4: "#c8c8c8",
        5: "#a6a6a6",
        6: "#e4e4e4",
        7: "#b8b8b8",
    },
}

_YEAR_WORDS = {
    "about": "about",
    "before": "before",
    "to": "before",
    "after": "after",
    "from": "after",
    "between": "between",
    "from_to": "between",
}
_TEXT_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")


def _year_text(value: Date | None, strings: Mapping[str, Any]) -> str:
    """The first structured year with its word, else a four-digit text year.
    A double year keeps both readings; an unknown year gives no text.
    """
    if value is None or value.year_unknown:
        return ""
    for day in (value.start, value.end):
        if day is not None and day.year is not None:
            year = format_date(
                Date("exact", Day(day.year, dual_year=day.dual_year)), strings
            )
            word = _YEAR_WORDS.get(value.form, "about" if value.quality else "")
            return (
                fill(strings["years"][word], PLACEHOLDERS[f"years.{word}"], {"y": year})
                if word
                else year
            )
    match = _TEXT_YEAR.search(value.text)
    return match.group() if match else ""


def _event_years(event: Event, label: str, strings: Mapping[str, Any]) -> str:
    year = _year_text(event.date, strings)
    if year and label not in ("birth", "death"):
        return fill(
            strings["years"][label], PLACEHOLDERS[f"years.{label}"], {"y": year}
        )
    return year


def _years(person: Person, event_standins: bool, strings: Mapping[str, Any]) -> str:
    birth, birth_label = birth_source(person, event_standins)
    death, death_label = death_source(person, event_standins)
    born = _event_years(birth, birth_label, strings)
    died = _event_years(death, death_label, strings)
    # born_only and died_only are for a birth or death year; a stand-in or the deceased
    # word alone fills lifespan, with the other side empty
    key = (
        "born_only"
        if born and not died and birth_label == "birth"
        else "died_only"
        if died and not born and death_label == "death"
        else "lifespan"
    )
    if not died and (
        person.death is not None or death_label in ("burial", "cremation")
    ):
        died = strings["years"]["deceased"]
        key = "lifespan"
    if not (born or died):
        return ""
    return fill(
        strings["years"][key],
        PLACEHOLDERS[f"years.{key}"],
        {"born": born, "died": died},
    )


def _line_color(slot: int, ink: str) -> str | None:
    if ink == "bw":
        return None
    ring = ring_of(slot)
    key: str | int
    if ring == 0:
        key = "center"
    elif ring == 1:
        key = "father" if slot == 2 else "mother"
    else:
        key = slot >> (ring - 2)
    return LINE_COLORS[ink][key]


def plan_fan(
    tree: Tree,
    root: str,
    *,
    generations: int = 6,
    exclude_private: bool = False,
    adoptive_parents: bool = False,
    event_standins: bool = True,
    ink: str = "color",
    lang: str | Mapping[str, Any] | None = None,
    preserve_case: bool = False,
) -> Fan:
    """Seat ancestors breadth-first through 2 to 7 generations, counting the root as 1.
    Missing and step parents are empty cells with no ancestors above them. Every path
    seats its own copy, even in a loop. Privacy replaces living names and hides years, using
    the unlimited pedigree estimate. Surnames are uppercase unless preserve_case
    keeps their recorded case. Ink chooses fills by grandparent line.
    """
    if root not in tree.people:
        raise KeyError(root)
    if type(generations) is not int or not 2 <= generations <= 7:
        raise ValueError(
            f"generations must be an integer from 2 to 7, not {generations!r}"
        )
    if ink not in ("color", "grayscale", "bw"):
        raise ValueError(f"ink must be color, grayscale or bw, not {ink!r}")
    strings = (
        load_strings(None, lang) if isinstance(lang, Mapping) else load_strings(lang)
    )
    prefer = "adoptive" if adoptive_parents else "birth"
    is_living = (
        living_checker(
            tree, plan_charts(tree, root, None, prefer, False), date.today().year
        )
        if exclude_private
        else nobody_living
    )
    seats: list[tuple[int, str | None]] = [(1, root)]
    for slot, pid in seats:
        if pid is not None and ring_of(slot) < generations - 1:
            father, mother = tree.parent_ids(pid, prefer)
            seats.extend(((2 * slot, father), (2 * slot + 1, mother)))
    copies = Counter(pid for _, pid in seats if pid is not None)
    rules = SortRules(strings["sort"])
    cells = []
    for slot, pid in seats:
        if pid is None:
            cells.append(FanCell(slot, empty=True))
            continue
        person = tree.people[pid]
        hide = is_living(pid)
        cells.append(
            FanCell(
                slot,
                title="" if hide else person.prefix,
                given=strings["living_name"] if hide else person.given,
                surname=""
                if hide
                else fmt_surname(person.surname, preserve_case, rules),
                suffix="" if hide else person.suffix,
                years="" if hide else _years(person, event_standins, strings),
                fill=_line_color(slot, ink),
                copies=copies[pid],
            )
        )
    return Fan(generations, cells, name=full_name(cells[0]))

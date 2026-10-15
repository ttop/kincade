"""Plain-Python tree, search and PDF operations for the browser worker."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Literal, cast

from kincade import FanOptions, Options, Tree, plan_fan, read_gedcom, render_fan
from kincade.charts import box_generation, living_checker, nobody_living, plan_charts
from kincade.cli import (
    default_fan_output_name,
    default_output_name,
    fan_summary,
    find_people,
    output_root_name,
    pedigree_summary,
    person_line,
)
from kincade.fanpdf import FAN_PAPER
from kincade.lang import DEFAULT_STRINGS, display_name, format_date
from kincade.pdf import BASE14, PAPER_SIZES, load_fontset, render_with_counts

PAGE_OPTIONS: dict[str, frozenset[str]] = {
    "pedigree": frozenset(
        {
            "generations",
            "exclude_private",
            "adoptive_parents",
            "event_standins",
            "empty_boxes",
            "show_ids",
            "shorten_places",
            "index",
            "page_numbers",
            "footer",
            "title",
            "paper",
            "large_print",
            "preserve_case",
            "shadow",
            "root_family",
        }
    ),
    "fan": frozenset(
        {
            "generations",
            "exclude_private",
            "adoptive_parents",
            "event_standins",
            "preserve_case",
            "ink",
            "paper",
            "title",
            "footer",
        }
    ),
}


class Session:
    """The successfully opened tree and the fonts used for its PDFs."""

    def __init__(self) -> None:
        self.tree: Tree | None = None
        self.fonts = BASE14
        self.preview: dict[str, int | float] | None = None
        self._pedigree_depths: dict[tuple[str, bool, bool], int] = {}

    def load_fonts(self, directory: str | Path) -> Literal["embedded", "base14"]:
        """Use all four embedded faces from this directory, or the built-in faces."""
        fonts, _missing = load_fontset([Path(directory)])
        self.fonts = fonts if fonts is not None else BASE14
        return "embedded" if fonts is not None else "base14"

    def open(self, data: bytes) -> int:
        """Replace the tree only after reading a file containing people."""
        tree = read_gedcom(data)
        if not tree.people:
            raise ValueError("GEDCOM file has no people")
        self.tree = tree
        self._pedigree_depths.clear()
        return len(tree.people)

    def pedigree_depth(
        self, root_id: str, adoptive_parents: bool, large_print: bool
    ) -> int:
        """Full known occupied depth in the renderer's cycle-safe chart plan."""
        tree = self.tree
        if tree is None:
            raise ValueError("Open a GEDCOM file first")
        if root_id not in tree.people:
            raise ValueError(f"Unknown root record ID {root_id!r}")
        key = (root_id, adoptive_parents, large_print)
        if key not in self._pedigree_depths:
            charts = plan_charts(
                tree,
                root_id,
                None,
                "adoptive" if adoptive_parents else "birth",
                large_print,
            )
            self._pedigree_depths[key] = max(
                chart.offset + box_generation(pos)
                for chart in charts
                for pos, person_id in chart.slots.items()
                if person_id in tree.people
            )
        return self._pedigree_depths[key]

    def root_families(
        self, root_id: str, exclude_private: bool = False, preserve_case: bool = False
    ) -> list[dict[str, str]]:
        """Root-partner families, with privacy-safe spouse and marriage labels."""
        tree = self.tree
        if tree is None:
            raise ValueError("Open a GEDCOM file first")
        root = tree.people.get(root_id)
        if root is None:
            raise ValueError(f"Unknown root record ID {root_id!r}")
        living = (
            living_checker(tree, [], datetime.date.today().year)
            if exclude_private
            else nobody_living
        )
        # Prefer FAMS order; still offer actual unions lacking a reciprocal link.
        families = dict.fromkeys(root.families + list(tree.families))
        choices = []
        for family_id in families:
            family = tree.families.get(family_id)
            if family is None or root_id not in (family.father, family.mother):
                continue
            spouse_id = family.mother if family.father == root_id else family.father
            spouse = tree.people.get(spouse_id)
            name = (
                DEFAULT_STRINGS["living_name"]
                if living(spouse_id)
                else display_name(spouse, preserve_case)
                if spouse
                else ""
            )
            parts = [family_id, name or "Unknown spouse"]
            if family.marriage and not (living(root_id) or living(spouse_id)):
                for key, value in (
                    ("marriage", format_date(family.marriage.date)),
                    ("marriage_place", family.marriage.place),
                ):
                    if value:
                        parts.append(f"{DEFAULT_STRINGS['labels'][key]} {value}")
            choices.append({"id": family_id, "label": " · ".join(parts)})
        return choices

    def search(
        self, text: str, exclude_private: bool, standins: bool, limit: int = 200
    ) -> tuple[int, list[list[str]]]:
        """Find people in file order, returning the full count and limited rows."""
        tree = self.tree
        if tree is None:
            raise ValueError("Open a GEDCOM file first")
        people = find_people(tree, text) if text else list(tree.people.values())
        living = (
            living_checker(tree, [], datetime.date.today().year)
            if exclude_private
            else nobody_living
        )
        rows = [
            person_line(person, living, standins, living_name=None).split("\t")
            for person in people
        ]
        return len(rows), rows[:limit]

    def render(
        self, root_id: str, chart: str, settings: dict[str, object]
    ) -> tuple[bytes, str, str]:
        """Render one chart with supplied page settings and library defaults."""
        tree = self.tree
        if tree is None:
            raise ValueError("Open a GEDCOM file first")
        if chart not in PAGE_OPTIONS:
            raise ValueError(f"Unknown chart {chart!r}")
        unknown = settings.keys() - PAGE_OPTIONS[chart]
        if unknown:
            raise ValueError(f"Unknown {chart} settings: {', '.join(sorted(unknown))}")
        if root_id not in tree.people:
            raise ValueError(f"Unknown root record ID {root_id!r}")
        if "generations" in settings:
            generations = settings["generations"]
            if chart == "pedigree":
                if generations is not None and (
                    type(generations) is not int or generations < 1
                ):
                    raise ValueError(
                        "Pedigree generations must be None or an integer of at least 1"
                    )
            elif type(generations) is not int or not 2 <= generations <= 7:
                raise ValueError("Fan generations must be an integer from 2 to 7")

        # The worker sends JSON values. Each chart accepts heterogeneous keyword
        # types; generations and the allowed names are checked above.
        supplied = cast(dict[str, Any], settings)
        if chart == "pedigree":
            options = Options(**supplied, fonts=self.fonts)
            rendered = render_with_counts(tree, root_id, options)
            result = (
                rendered.pdf,
                default_output_name(
                    output_root_name(
                        tree,
                        root_id,
                        exclude_private=options.exclude_private,
                        adoptive_parents=options.adoptive_parents,
                        large_print=options.large_print,
                    )
                ),
                pedigree_summary(rendered),
            )
            width, height = PAPER_SIZES[options.paper]
            self.preview = {"pages": rendered.pages, "width": width, "height": height}
            return result

        planning = {
            key: value
            for key, value in supplied.items()
            if key
            in {
                "generations",
                "exclude_private",
                "adoptive_parents",
                "event_standins",
                "preserve_case",
            }
        }
        drawing = {
            key: value
            for key, value in supplied.items()
            if key in {"paper", "title", "footer"}
        }
        ink = supplied.get("ink", "color")
        fan = plan_fan(tree, root_id, **planning, ink=ink)
        fan_options = FanOptions(**drawing, ink=ink, fonts=self.fonts)
        pdf = render_fan(fan, fan_options)
        filename = default_fan_output_name(
            output_root_name(
                tree,
                root_id,
                exclude_private=supplied.get("exclude_private", False),
                adoptive_parents=supplied.get("adoptive_parents", False),
            )
        )
        result = pdf, filename, fan_summary(fan)
        width, height = FAN_PAPER[fan_options.paper]
        self.preview = {"pages": 1, "width": width, "height": height}
        return result

"""The family tree in memory: plain dataclasses with no GEDCOM, file or drawing code in
them. Another program can build a Tree from its own data and hand it to the library.
This module imports nothing of Kincade's.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def strip_controls(text: str) -> str:
    """Remove non-whitespace control characters, keeping word separators as supplied."""
    return "".join(
        ch for ch in text if ch.isspace() or unicodedata.category(ch) != "Cc"
    )


def squash(text: str | None) -> str:
    """`text` with each run of whitespace made one space and none at either end.

    None gives "". Shared here so readers and formatters use the same whitespace
    rule without importing one another.
    """
    return " ".join((text or "").split())


DATE_FORMS = (
    "exact",
    "about",
    "before",
    "after",
    "between",
    "from",
    "to",
    "from_to",
    "text",
)
RANGE_FORMS = ("between", "from_to")  # the forms with two ends
DATE_QUALITIES = ("", "estimated", "calculated")
# How a child is related to one parent: birth (the parent is the child's birth parent),
# adopted (an adoptive parent), foster, step (a step-parent: never drawn on a pedigree
# chart, which shows ancestors) or other (any other tie, such as sealing or sponsorship)
RELATIONSHIPS = ("birth", "adopted", "foster", "step", "other")


def _check(what: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        choices = ", ".join(repr(a) for a in allowed)
        raise ValueError(f"{what} must be one of {choices}, not {value!r}")


@dataclass
class Day:
    """One calendar date, as far as it is known. Any part may be missing: a year
    alone, a month and year, a day and month with no year, a month alone or a day
    alone. A year is 1 to 9999, a day 1 to 31.
    """

    year: int | None = None
    month: int | None = None  # 1 to 12
    day: int | None = None  # 1 to 31
    # For a double date such as 1731/32 (the year changed in March in England until
    # 1752): `year` is the old-style year, 1731, and `dual_year` the new-style year,
    # 1732, always year + 1. Estimates read the new-style year.
    dual_year: int | None = None

    def __post_init__(self) -> None:
        if self.month is not None and not 1 <= self.month <= 12:
            raise ValueError(f"Day.month must be 1 to 12, not {self.month!r}")
        if self.day is not None and not 1 <= self.day <= 31:
            raise ValueError(f"Day.day must be 1 to 31, not {self.day!r}")
        for name in ("year", "dual_year"):
            value = getattr(self, name)
            if value is not None and not 1 <= value <= 9999:
                raise ValueError(f"Day.{name} must be 1 to 9999, not {value!r}")
        if self.dual_year is not None and (
            self.year is None or self.dual_year != self.year + 1
        ):
            raise ValueError(
                f"Day.dual_year must be the year after Day.year, not {self.dual_year!r} "
                f"with year {self.year!r}"
            )


@dataclass
class Date:
    """A date as a person wrote it, in structure. `form` says how `start` and `end`
    read:

        exact     start
        about     start (a few years either way)
        before, after, from, to    start (from and to: one end of a period)
        between   start and end (a range: between two dates)
        from_to   start and end (a period)
        text      no structure: only `text`

    `quality` "estimated" or "calculated" says how the date was reached (it adds to any
    form). `text`, when it is set, is what is printed in place of the structure: a date
    phrase such as "Hebrew New Year", or text that could not be read as a date. The
    estimate of who may be living reads the structure and any recognized whole-text
    shape (see text_date). A date with no structure has only its text shape to read.

    `year_unknown` marks a date that was recorded but whose year cannot be read: it is
    written in a calendar the reader cannot convert (Hebrew, French Republican, ...), so
    the numbers in `start`, `end` and `text` are not years of the Gregorian calendar, or
    it is an interpreted date that the reader could not read at all. The estimate of who
    may be living then takes the date to allow any year up to today, whatever the
    structure, the text or a dated descendant says, and the index shows no year for it.
    The GEDCOM reader stores the written date in `text` so it prints as recorded.

    A date that contradicts itself is refused when it is made (ValueError): `between`
    and `from_to` need both `start` and `end`, no other form takes an `end`, and `text`
    needs text.
    """

    form: str
    start: Day | None = None
    end: Day | None = None  # the second date of "between" and "from_to"
    quality: str = ""
    text: str = ""
    year_unknown: bool = False

    def __post_init__(self) -> None:
        _check("Date.form", self.form, DATE_FORMS)
        _check("Date.quality", self.quality, DATE_QUALITIES)
        if self.form in RANGE_FORMS:
            if self.start is None or self.end is None:
                raise ValueError(f"Date.form {self.form!r} needs both start and end")
        elif self.end is not None:
            raise ValueError(
                f"Date.end belongs to the forms 'between' and 'from_to', not {self.form!r}"
            )
        if self.form == "text" and not self.text:
            raise ValueError("Date.form 'text' needs text")


_TEXT_APPROX = re.compile(
    r"(c\.?|ca\.?|circa|abt\.?|about|approx\.?|est\.?|cal\.?)\s*([0-9]{3,4})",
    re.IGNORECASE,
)
_TEXT_DECADE = re.compile(r"([0-9]{2,3}0)['’]?s", re.IGNORECASE)
_TEXT_RANGE = re.compile(
    r"([0-9]{3,4})(?:\s*[-–]\s*|\s+to\s+)([0-9]{3,4})", re.IGNORECASE
)
_TEXT_BETWEEN = re.compile(
    r"(?:bet\.?|between)\s+([0-9]{3,4})\s+and\s+([0-9]{3,4})", re.IGNORECASE
)
_TEXT_FROM_TO = re.compile(r"from\s+([0-9]{3,4})\s+to\s+([0-9]{3,4})", re.IGNORECASE)
_TEXT_MONTHS = {
    spelling: number
    for number, name in enumerate(
        [
            "JANUARY",
            "FEBRUARY",
            "MARCH",
            "APRIL",
            "MAY",
            "JUNE",
            "JULY",
            "AUGUST",
            "SEPTEMBER",
            "OCTOBER",
            "NOVEMBER",
            "DECEMBER",
        ],
        1,
    )
    for spelling in (name, name[:3])
}
_TEXT_DAY = (
    r"(?:(?:([0-9]{1,2})\s+)?(" + "|".join(_TEXT_MONTHS) + r")\.?\s+)?"
    r"([0-9]{3,4})"
)
_TEXT_EXACT = re.compile(_TEXT_DAY, re.IGNORECASE)
_TEXT_BOUND = re.compile(
    r"(bef\.?|before|aft\.?|after|by|since|from|to)\s+" + _TEXT_DAY,
    re.IGNORECASE,
)
_TEXT_DOUBLE = re.compile(r"([0-9]{3,4})/([0-9]{1,2})")
_TEXT_NUMERIC = re.compile(
    r"(?:([0-9]{4})[./-][0-9]{1,2}[./-][0-9]{1,2}|"
    r"[0-9]{1,2}[./-][0-9]{1,2}[./-]([0-9]{4}))"
)


def text_date(text: str) -> Date | None:
    """The reading of a recognized whole-text date shape, or None. Matches use the
    entire trimmed text, case-insensitively. Years are positive, with three or four
    digits except in all-number dates, which need four. The shapes shared by the index,
    sort, privacy and --find are:

    - A plain year, month and year, or day, month and year: 1900, MAY 1900, 12 MAY 1900.
      An exact date.
    - c, ca, circa, abt, about, approx, est or cal + year, with optional space and an
      optional period on abbreviations: c1900, c. 1900, approx. 1900, cal 1920. About,
      estimated or calculated, allowing ten years later.
    - A decade ending in 0 + s, 's or ’s: 1920s, 1920S, 1920's, 1920’s. 1920..1929.
    - Two years separated by a hyphen, en dash or "to": 1765-1767, 1765–1767,
      1765 to 1767. Spaces around a dash are optional. A bounded range.
    - bet or between year and year; from year to year: bet 1890 and 1900,
      between 1890 and 1900, from 1900 to 1910. A bounded range or period.
    - bef, before, aft, after, by, since, from or to + year or [day] month year:
      by Dec 1879, from 1900, to 1910, bef. 1879, after 12 DEC 1879. Abbreviations may
      have a period. Before/by/to bounds the year; after is strict; since/from is
      inclusive and open-ended.
    - A double year with the next year's last one or two digits: 1731/32, 1731/2. The
      first year is shown; the following year bounds it.
    - An all-number date with a four-digit year first or last and /, . or - separators:
      12/05/1900, 12.5.1900, 1900-05-12, 1900/05/12. The other two numbers have one or
      two digits. Only the year is read; day and month are not interpreted.

    Wherever a shape takes a month, it accepts JAN..DEC or the full English name
    January..December, in any case, with an optional period. Days are 1..31.

    The returned Date has structure and no display text. Unrecognized text supplies no
    year; callers keep its written text for display."""
    text = text.strip()
    if m := _TEXT_EXACT.fullmatch(text):
        year, day = int(m[3]), int(m[1]) if m[1] else None
        if year and (day is None or 1 <= day <= 31):
            month = _TEXT_MONTHS[m[2].upper()] if m[2] else None
            return Date("exact", Day(year, month, day))
    elif m := _TEXT_APPROX.fullmatch(text):
        if year := int(m[2]):
            quality = {"est": "estimated", "cal": "calculated"}.get(
                m[1].lower().rstrip("."), ""
            )
            return Date("exact" if quality else "about", Day(year), quality=quality)
    elif m := _TEXT_DECADE.fullmatch(text):
        if year := int(m[1]):
            return Date("between", Day(year), Day(year + 9))
    elif m := _TEXT_RANGE.fullmatch(text):
        first, last = int(m[1]), int(m[2])
        if first and last:
            return Date("between", Day(first), Day(last))
    elif m := (_TEXT_BETWEEN.fullmatch(text) or _TEXT_FROM_TO.fullmatch(text)):
        first, last = int(m[1]), int(m[2])
        if first and last:
            form = "between" if m.re is _TEXT_BETWEEN else "from_to"
            return Date(form, Day(first), Day(last))
    elif m := _TEXT_BOUND.fullmatch(text):
        year, day = int(m[4]), int(m[2]) if m[2] else None
        if year and (day is None or 1 <= day <= 31):
            word = m[1].lower().rstrip(".")
            form = {
                "aft": "after",
                "after": "after",
                "since": "from",
                "from": "from",
                "to": "to",
            }.get(word, "before")
            month = _TEXT_MONTHS[m[3].upper()] if m[3] else None
            return Date(form, Day(year, month, day))
    elif m := _TEXT_DOUBLE.fullmatch(text):
        year = int(m[1])
        if 0 < year < 9999 and int(m[2]) == (year + 1) % 10 ** len(m[2]):
            return Date("exact", Day(year, dual_year=year + 1))
    elif (m := _TEXT_NUMERIC.fullmatch(text)) and (year := int(m[1] or m[2])):
        return Date("exact", Day(year))
    return None


@dataclass
class Event:
    """A date and place for one event; either may be missing."""

    date: Date | None = None
    place: str = ""  # already joined, e.g. "Eugene, Lane County, Oregon, USA"

    def filled(self) -> bool:
        """Has a date or a place (a record that exists but is empty, such as "1 BIRT Y",
        does not).
        """
        return self.date is not None or bool(self.place)


@dataclass
class ParentLink:
    """Membership in the family a person was born or taken into as a child, and their
    relationship to each parent. `father` is the relationship to Family.father and
    `mother` the one to Family.mother; each is one of RELATIONSHIPS. A child can be a
    birth child of one parent and a stepchild of the other, or adopted by one and a
    birth child of the other. Both are "birth" unless said otherwise.
    """

    family: str  # Family.id
    father: str = "birth"  # the child's relationship to the family's father
    mother: str = "birth"  # ... and to its mother

    def __post_init__(self) -> None:
        _check("ParentLink.father", self.father, RELATIONSHIPS)
        _check("ParentLink.mother", self.mother, RELATIONSHIPS)


@dataclass
class Person:
    """A person's name, events and family links, keyed by their record ID."""

    id: str
    given: str = ""
    surname: str = ""
    prefix: str = ""
    suffix: str = ""
    birth: Event | None = None  # None: no birth record
    death: Event | None = None  # an Event with no date still means "died"
    # Stand-ins for a missing birth or death (see birth_source and death_source). Every
    # record is kept, in source order; christenings are the christening records, then
    # the baptism records. A cremation is not a burial.
    christenings: list[Event] = field(default_factory=list)
    burials: list[Event] = field(default_factory=list)
    cremations: list[Event] = field(default_factory=list)
    parents: list[ParentLink] = field(default_factory=list)  # in source order
    # the families where the person is a parent, in order
    families: list[str] = field(default_factory=list)
    # True or False replaces Kincade's estimate of whether this person may be living
    # (see living_checker), for this person only; None keeps the estimate. It only
    # matters when private details are hidden (exclude_private).
    living: bool | None = None


@dataclass
class Family:
    """Parents, their marriage and their children, linked by record IDs."""

    id: str
    father: str = ""
    mother: str = ""
    marriage: Event | None = None
    children: list[str] = field(default_factory=list)


# Options.adoptive_parents False or True; plan_charts takes the word
PARENT_MODES = ("birth", "adoptive")


def check_parents(parents: str) -> None:
    """Validate the parent selection mode: birth or adoptive."""
    if parents not in PARENT_MODES:
        raise ValueError(
            f"parents must be one of {', '.join(PARENT_MODES)}, not {parents!r}"
        )


@dataclass
class Tree:
    """People and families indexed by their record IDs."""

    people: dict[str, Person] = field(default_factory=dict)
    families: dict[str, Family] = field(default_factory=dict)

    def _parents_drawn(self, pid: str, prefer: str) -> tuple[Family, ParentLink] | None:
        """The parent family to draw for a person and the person's link to it (see
        parent_family).
        """
        check_parents(prefer)
        person = self.people.get(pid)
        # each family the child belongs to, in source order, with that link
        links = [
            (self.families[link.family], link)
            for link in (person.parents if person else [])
            if link.family in self.families
        ]
        if prefer == "adoptive":
            for kind in ("adopted", "foster"):
                for family, link in links:
                    if kind in (link.father, link.mother):
                        return family, link

        def rank(item: tuple[Family, ParentLink]) -> tuple[int, int]:
            pair = (item[1].father, item[1].mother)
            # most birth parents first, then fewest step-parents
            return -pair.count("birth"), pair.count("step")

        # the first of the best: min keeps the earlier of equals
        return min(links, key=rank) if links else None

    def parent_family(self, pid: str, prefer: str = "birth") -> Family | None:
        """The parent family to draw for `pid`. Links to missing families are skipped.
        Rank links by most birth relationships, then fewest step relationships,
        then source order. A step-parent is never drawn.

        With prefer="adoptive", choose the first link with an adopted relationship,
        else the first with a foster relationship, else use the birth ranking.
        """
        drawn = self._parents_drawn(pid, prefer)
        return drawn[0] if drawn else None

    def parents_union(self, pid: str, prefer: str = "birth") -> Family | None:
        """The family whose marriage is the marriage of the parents drawn for a person:
        the one parent_family chooses, unless one of its parents is the person's
        step-parent. That union is not the parents drawn (the step-parent is never
        drawn), so there is none: None. None, too, when the person has no parent family.
        """
        drawn = self._parents_drawn(pid, prefer)
        return (
            drawn[0]
            if drawn and "step" not in (drawn[1].father, drawn[1].mother)
            else None
        )

    def parent_relationship(self, pid: str, prefer: str = "birth") -> str:
        """The relationship that the note after the person's name reports: "adopted",
        "foster", or "birth" for no note. It comes from the parents of the family
        parent_family chooses that are drawn (see parent_ids). If any of them is adopted
        it is "adopted", else "foster" if any is foster, else "birth": so an adopted
        parent beside a birth parent gives "adopted", and birth or other parents, with
        any step-parent left out, give "birth". When nobody is drawn, the family's
        non-step relationships speak instead. "birth" when there is no family.
        """
        drawn = self._parents_drawn(pid, prefer)
        if not drawn:
            return "birth"
        family, link = drawn
        parents = ((family.father, link.father), (family.mother, link.mother))
        words = [
            word for parent, word in parents if word != "step" and parent in self.people
        ]
        words = words or [word for _, word in parents if word != "step"]
        return next((word for word in ("adopted", "foster") if word in words), "birth")

    def is_birth_parent(self, parent: str, child: str) -> bool:
        """Whether `parent` is a parent of `child` by birth: a family of the child's
        that names `parent` as father (and the child is a birth child of its father) or
        as mother (and of its mother), whichever family is drawn. Each parent counts on
        their own: Mary can be the child's birth mother when the stepfather beside her
        is not a birth parent.
        """
        person = self.people.get(child)
        for link in person.parents if person else []:
            family = self.families.get(link.family)
            if family and (
                (parent == family.father and link.father == "birth")
                or (parent == family.mother and link.mother == "birth")
            ):
                return True
        return False

    def parent_ids(
        self, pid: str, prefer: str = "birth"
    ) -> tuple[str | None, str | None]:
        """(father, mother) ids to draw; None where unknown, absent from the tree, or
        the child's step-parent (which is never drawn: that box stays empty, like the
        box of any unknown ancestor).
        """
        drawn = self._parents_drawn(pid, prefer)
        if not drawn:
            return None, None
        family, link = drawn
        return (
            family.father
            if link.father != "step" and family.father in self.people
            else None,
            family.mother
            if link.mother != "step" and family.mother in self.people
            else None,
        )

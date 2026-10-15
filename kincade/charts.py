"""Chart planning and privacy: the Ahnentafel positions and continuation charts of a
pedigree, which of a person's parent families is drawn, the stand-in events for a
missing birth or death, and the estimate of who may be living. Pure logic over the
model; no drawing. Imports only the model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .model import Date, Day, Event, Person, Tree, check_parents, text_date

# --------------------------------------------------------------------------
# Chart planning
# --------------------------------------------------------------------------


NORMAL_DEPTH = 4  # generations per chart page in normal print
LARGE_DEPTH = 3  # generations per chart page in large print


@dataclass
class Chart:
    number: int
    # Ahnentafel position 1..15 -> person id
    # (None = unknown, a step-parent, or not drawn)
    slots: dict[int, str | None]
    # (chart, position) where this chart's box 1 sits
    origin: tuple[int, int] | None = None
    # last-generation position (8..15, 4..7) -> chart
    continuations: dict[int, int] = field(default_factory=dict)
    # Generations above box 1; chart 1 has offset 0.
    offset: int = 0
    # positions drawn on this chart (see plan_charts)
    drawn: frozenset[int] = frozenset(range(1, 16))
    # generations on the chart: 4 (boxes 1-15), or 3 (boxes 1-7) in large print
    depth: int = NORMAL_DEPTH
    # The person just below box 1 on the chart this one continues (the child whose
    # parents box 1 was drawn as), None for chart 1. Box 1 shows the marriage of that
    # child's parents, as its box there did (or, for a step-parent's, none).
    via: str | None = None
    # The parents mode the chart was planned with: "birth" or "adoptive" (plan_charts)
    parents: str = "birth"


def box_generation(pos: int) -> int:
    """Generation of an Ahnentafel position within its chart: 1 for box 1, 2 for 2-3, 3
    for 4-7, 4 for 8-15.
    """
    return pos.bit_length()


def page_depth(large_print: bool = False) -> int:
    """Generations on a chart page: 4, or 3 in large print."""
    return LARGE_DEPTH if large_print else NORMAL_DEPTH


def _chart(
    tree: Tree,
    number: int,
    pid: str,
    offset: int,
    origin: tuple[int, int] | None,
    generations: int | None,
    parents: str,
    depth: int,
    via: str | None = None,
) -> Chart:
    """A chart whose box 1 is `pid`, `depth` generations deep. Positions beyond the
    generation limit are not drawn: their slots stay None, as do the positions past the
    chart's last generation. `via` is the person below `pid` on the chart it continues.
    """
    drawn = frozenset(
        p
        for p in range(1, 2**depth)
        if generations is None or offset + box_generation(p) <= generations
    )
    slots: dict[int, str | None] = dict.fromkeys(range(1, 16))
    slots[1] = pid
    for p in range(1, 2 ** (depth - 1)):
        if child := slots[p]:
            slots[2 * p], slots[2 * p + 1] = tree.parent_ids(child, parents)
    return Chart(
        number,
        {p: slots[p] if p in drawn else None for p in slots},
        origin,
        offset=offset,
        drawn=drawn,
        depth=depth,
        via=via,
        parents=parents,
    )


def plan_charts(
    tree: Tree,
    root_id: str,
    generations: int | None = None,
    parents: str = "birth",
    large_print: bool = False,
) -> list[Chart]:
    """Breadth-first chart numbering. Cycle-safe: a person roots at most one chart.

    `generations` counts the root as generation 1; None means every known ancestor.
    Boxes in a deeper generation are not drawn at all. A box 8-15 person with a known
    parent gets a continuation chart only if that parent is within the limit. The
    continuation chart's box 1 is that person, so its offset is the box's generation
    minus 1, and the chart remembers the child below that box (`Chart.via`) so that box
    1 can show the marriage that box showed.

    `parents` chooses each person's parent family (Tree.parent_family): "birth"
    (default) or "adoptive". A step-parent is never placed in a box: that slot stays
    None, like an unknown ancestor, and has no continuation chart. Each chart records
    the mode (Chart.parents): draw them with the matching Options.adoptive_parents.

    With large_print a chart is three generations deep (boxes 1-7) instead of four
    (boxes 1-15): the continuation charts start from boxes 4-7, and each continuation
    level adds two generations instead of three. Draw them with
    Options(large_print=True).
    """
    check_parents(parents)
    depth = page_depth(large_print)
    if root_id not in tree.people:
        raise KeyError(root_id)
    if generations is not None and generations < 1:
        raise ValueError(f"generations must be at least 1, not {generations}")
    charts = [_chart(tree, 1, root_id, 0, None, generations, parents, depth)]
    roots = {root_id: 1}
    for chart in charts:  # the list grows while we walk it, which is the BFS queue
        for pos in range(2 ** (depth - 1), 2**depth):  # the chart's last generation
            pid = chart.slots[pos]
            if not pid or not any(tree.parent_ids(pid, parents)):
                continue
            # generation of this box in the whole pedigree
            gen = chart.offset + box_generation(pos)
            if pid not in roots and (generations is None or gen + 1 <= generations):
                roots[pid] = len(charts) + 1
                charts.append(
                    _chart(
                        tree,
                        roots[pid],
                        pid,
                        gen - 1,
                        (chart.number, pos),
                        generations,
                        parents,
                        depth,
                        via=chart.slots[pos // 2],
                    )
                )
            if pid in roots:
                chart.continuations[pos] = roots[pid]
    return charts


# --------------------------------------------------------------------------
# Stand-in events
# --------------------------------------------------------------------------


def birth_source(p: Person, fallback: bool = True) -> tuple[Event, str]:
    """The event that gives a person's birth lines, and the label key for it ("birth" or
    "christening").

    The person's birth, when it has a date or place. Otherwise, with fallback, the first
    filled event in Person.christenings (christenings before baptisms). With neither,
    the empty birth event prints birth labels without values.
    """
    if p.birth and p.birth.filled():
        return p.birth, "birth"
    if fallback and (
        christening := next((e for e in p.christenings if e.filled()), None)
    ):
        return christening, "christening"
    return p.birth or Event(), "birth"


def death_source(p: Person, fallback: bool = True) -> tuple[Event, str]:
    """The event that gives a person's death lines, and the label key for it ("death",
    "burial" or "cremation").

    The person's death, when it has a date or place. Otherwise, with fallback, the first
    filled event in Person.burials, else Person.cremations. With neither, the empty
    death event prints death labels without values.
    """
    if p.death and p.death.filled():
        return p.death, "death"
    if fallback:
        if burial := next((e for e in p.burials if e.filled()), None):
            return burial, "burial"
        if cremation := next((e for e in p.cremations if e.filled()), None):
            return cremation, "cremation"
    return p.death or Event(), "death"


# --------------------------------------------------------------------------
# Birth years from dates
# --------------------------------------------------------------------------

ABOUT_MARGIN = 10  # years allowed beyond an approximate birth date
GENERATION_YEARS = 25  # minimum age difference along a birth-parent link
LIVING_YEARS = 100  # a birth later than this many years ago may mean living


def _years_in(text: str) -> list[int]:
    """The years of a recognized text shape, using the later year of a double date."""
    reading = text_date(text)
    return [*_years_of(reading.start), *_years_of(reading.end)] if reading else []


def _years_of(day: Day | None) -> list[int]:
    """The year a date names, for an estimate: the new-style year of a double date. A
    Day holds a year of 1 to 9999 (Day checks it), so it is read as it is.
    """
    if day is None or day.year is None:
        return []
    return [day.dual_year if day.dual_year is not None else day.year]


def _is_open(date: Date) -> bool:
    """Whether a date has an open-ended after or from form."""
    return date.form == "after" or (date.form == "from" and date.end is None)


def _birth_reading(date: Date) -> Date:
    """An explicit open form or structure, else the recognized shape of date text."""
    if not _is_open(date) and date.start is None and date.end is None:
        return text_date(date.text) or date
    return date


def open_birth(date: Date | None) -> tuple[bool, int | None]:
    """(True, floor) for an open-ended birth: "after x" (strictly after x: floor x + 1),
    or "from x" with no end (floor x). x is the latest year the date names; the floor is
    None if it names none. (False, None) for anything else, an open-ended date whose
    year is unknown (Date.year_unknown) included: it has no x to start from.
    """
    if date is None or date.year_unknown:
        return False, None
    date = _birth_reading(date)
    if not _is_open(date):
        return False, None
    years = [*_years_of(date.start), *_years_of(date.end), *_years_in(date.text)]
    if not years:
        return True, None
    return True, max(years) + (1 if date.form == "after" else 0)


def latest_birth_year(date: Date | None, this_year: int) -> int | None:
    """The latest year a (possibly vague) birth date allows: the conservative reading
    for privacy.

    between a and b / from a to b -> the later end; before or to x -> x; after x and an
    open from x -> this year (the privacy estimate may refine these, see
    `_birth_estimates`); about x, or an estimated or calculated one -> x + 10; an exact
    date -> its year (a double date, 1731/32, its new-style year). Free text is read
    through model.text_date's recognized whole-text shapes using the same rules. An
    interpreted date with a phrase -> the later of the structure's latest year and the
    recognized text shape's latest year. A date whose year is unknown
    (Date.year_unknown, such as a calendar the reader cannot convert) -> this year. None
    for no date or no recognized year; the privacy estimate counts a recorded birth date
    with no year as this year (see `_own_birth_year`). A christening uses the same date
    reading to bound a missing birth date, regardless of display options.
    """
    if date is None:
        return None
    if date.year_unknown or _is_open(date):
        return this_year
    own = [*_years_of(date.start), *_years_of(date.end)]
    margin = ABOUT_MARGIN if date.form == "about" or date.quality else 0
    text = text_date(date.text)
    if text is not None and not own and margin:
        text = replace(text, quality=date.quality or "estimated")
    named = latest_birth_year(text, this_year)
    if own:
        return max(max(own) + margin, named) if named is not None else max(own) + margin
    return named


# --------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------


def _christening_bound(p: Person, this_year: int) -> int | None:
    """The latest birth year a christening or baptism allows: the earliest of their
    latest years (a birth comes before every christening), each read as
    latest_birth_year reads a date. A christening whose date gives no year bounds
    nothing; when none gives one and one is dated, the birth may be as late as this
    year. None if none of them is dated.
    """
    dated = [e.date for e in p.christenings if e.date is not None]
    years = [
        y for date in dated if (y := latest_birth_year(date, this_year)) is not None
    ]
    return min(years) if years else this_year if dated else None


def _own_birth_year(p: Person, this_year: int) -> int | None:
    """The latest birth year a person's own records allow, for the privacy estimate:
    the year their BIRT date allows (latest_birth_year). A BIRT date that is recorded
    but gives no year (a calendar Kincade cannot convert, a phrase or text with no year
    in it, a day and month alone) is not the same as no date: the person may have been
    born as late as this year, and no christening or descendant's birth overrides it.
    With no BIRT date, the christening bound, regardless of display options. None
    when neither gives a year."""
    date = p.birth.date if p.birth else None
    if date is not None:
        own = latest_birth_year(date, this_year)
        return this_year if own is None else own
    return _christening_bound(p, this_year)


def _birth_estimates(tree: Tree, charts: list[Chart], this_year: int) -> dict[str, int]:
    """Estimated birth year of everyone in the pedigree, for the privacy rule.

    A person's own BIRT year wins, and so does a BIRT date that gives no year (see
    `_own_birth_year`: this year). Otherwise the estimate is the latest (most
    conservative: most likely living) of "descendant's birth year - 25 per generation"
    over every dated descendant in the pedigree, found by a breadth-first walk down the
    child edges implied by the charts. People are nodes, so a chart's box 1 is the same
    node as its origin box (no extra generation) and pedigree collapse or data loops
    simply add paths (a visited set keeps loops finite). Years are the latest possible
    ones (`latest_birth_year`), so vague dates err toward "living".

    An open-ended birth ('AFT x', 'FROM x') is not a year of its own: it takes the
    descendant estimate, but never earlier than its floor, which is x + 1 for 'AFT x'
    (strictly after x) and x for an open 'FROM x' (see `open_birth`). With no dated
    descendant it stays "possibly born today", and so does one that names no x.

    A person with no birth date but a christening or baptism takes that year as the
    latest possible birth (see `_christening_bound`), regardless of display options, in
    place of the descendant estimate. A descendant's birth year is read the same way
    (`_own_birth_year`), so a descendant whose BIRT date gives no year counts as born
    this year.

    Only birth links carry an age: a parent is at least about 25 years older than their
    child, but an adopted, foster, step, sealing or other parent can be any age, as
    adoption can come years after the birth. So the walk follows a chart's parent-child
    edge only where `Tree.is_birth_parent` says the parent is the child's birth parent,
    in any parents mode, and it says so per parent: in a family where the child is a
    birth child of the mother and adopted by the father, her age can come from the
    child's birth and his cannot. A parent reached only by other links, and everyone
    above them, has no estimate from below."""
    children: dict[str, set[str]] = {}
    for chart in charts:
        for pos, pid in chart.slots.items():
            child = chart.slots.get(pos // 2) if pos > 1 else None
            if pid and child and child != pid and tree.is_birth_parent(pid, child):
                children.setdefault(pid, set()).add(child)

    def from_descendants(pid: str) -> int | None:
        best, seen, level, gens = None, {pid}, [pid], 0
        while level:
            gens += 1
            following = []
            for parent in level:
                for child in children.get(parent, ()):
                    if child not in seen:
                        seen.add(child)
                        following.append(child)
                        year = _own_birth_year(tree.people[child], this_year)
                        if year is not None:
                            guess = year - GENERATION_YEARS * gens
                            best = guess if best is None else max(best, guess)
            level = following
        return best

    def estimate(pid: str) -> int | None:
        person = tree.people[pid]
        opened, floor = open_birth(person.birth.date if person.birth else None)
        if opened and floor is None:
            # open-ended from a year it does not name:
            # a descendant's birth cannot place it
            return this_year
        if not opened and (own := _own_birth_year(person, this_year)) is not None:
            return own
        best = from_descendants(pid)
        if not opened:
            return best
        if best is None:
            # open-ended with nothing dated below it: possibly born today
            return this_year
        assert floor is not None  # an open-ended birth with no floor returned above
        return max(floor, best)

    result = {}
    for chart in charts:
        for pid in chart.slots.values():
            if pid and pid not in result and (year := estimate(pid)) is not None:
                result[pid] = year
    return result


def living_checker(
    tree: Tree, charts: list[Chart], this_year: int
) -> Callable[[str | None], bool]:
    """Whether a person may be living. A person's explicit `living` verdict wins.
    Otherwise a death, burial or cremation record means not living. A christening
    bounds a missing birth date, regardless of display options (see _birth_estimates).
    A recorded birth date with no year counts as this year and takes precedence over
    christenings and descendant estimates, so the person may be living."""
    estimates = _birth_estimates(tree, charts, this_year)

    def is_living(pid: str | None) -> bool:
        p = tree.people.get(pid or "")
        if not p:
            return False
        if p.living is not None:  # the caller's verdict, for this person only
            return p.living
        if p.death is not None or p.burials or p.cremations:
            return False
        year = estimates[p.id] if p.id in estimates else _own_birth_year(p, this_year)
        # nothing known and no death record: assume living
        return year is None or year > this_year - LIVING_YEARS

    return is_living


def nobody_living(pid: str | None) -> bool:
    """The living check when privacy is off."""
    return False

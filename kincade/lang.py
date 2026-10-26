"""Language: every string the PDF prints, the language files, template filling, date and
name formatting, and the index sort rules. DEFAULT_STRINGS is the English wording; a
language file (kincade/lang/*.toml, ~/.config/kincade/lang/, or any .toml path) and the
strings argument override it (load_strings). Imports only the model.
"""

from __future__ import annotations

import copy
import os
import re
import tomllib
import unicodedata
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .model import Date, Day, Person, squash, text_date

# English short names
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

DEFAULT_STRINGS: dict[str, Any] = {
    "title": "Cascading Pedigree",
    "living_name": "Living",
    "fan_title": "{name} — Fan chart",
    "meta_title": "{title} — {name}",  # the PDF's Title metadata (not drawn)
    "footer": "Created {date} using Kincade",
    # the footer of the blank chart (--blank), which has no date
    "footer_blank": "Created using Kincade",
    # a full date: the footer's date and GEDCOM dates that have a day
    "date_format": "{day} {month} {year}",
    # the first day of a month in a date, where a language writes it apart (1er)
    "day_one": "1",
    "chart_label": "Chart {n}",
    "continuation": "Number 1 on this chart is the same as number {pos} on chart {chart}.",
    # chart 1's line when it has continuation charts ("" for none): the continuation
    # line's place and style
    "chart_note": "Ancestry continues on the chart numbered in the last column.",
    "ellipsis": "…",
    # bottom left of every page, on the footer's line
    "page_number": "Page {page} of {pages}",
    # a box's record ID (--show-ids): the person's id, such as I12 in a GEDCOM file
    "record_id": "[{id}]",
    "months": {"short": list(MONTHS)},
    "index": {
        "title": "Index",
        "born": "b. {birth}",
        "died": "d. {death}",
        "joiner": " – ",
        "years": "({years})",
        "christened": "chr. {birth}",
        "buried": "bur. {death}",
        "cremated": "crem. {death}",
        "legend": "The numbers after each name indicate the chart number and box number. 6-1 is box 1 on chart 6.",
    },
    # Relationship note from Tree.parent_relationship, in either parents mode.
    # Uses available non-step parents, or the link's non-step relationships when
    # neither parent is available. Birth and other relationships give no note.
    "relationship": {"adopted": "(adopted)", "foster": "(foster)"},
    "labels": {
        "birth": "b.",
        "birth_place": "bp.",
        "spouse": "spouse:",
        "marriage": "m.",
        "marriage_place": "mp.",
        "death": "d.",
        "death_place": "dp.",
        "christening": "chr.",
        "christening_place": "chrp.",
        "burial": "bur.",
        "burial_place": "burp.",
        "cremation": "crem.",
        "cremation_place": "cremp.",
    },
    "dates": {
        "about": "abt",
        "estimated": "est",
        "calculated": "cal",
        "before": "bef",
        "after": "aft",
        "from": "from",
        "to": "to",
        "range": "-",
    },
    "years": {
        "christening": "chr {y}",
        "burial": "bur {y}",
        "cremation": "crem {y}",
        "deceased": "Deceased",
        "about": "abt {y}",
        "before": "bef {y}",
        "after": "aft {y}",
        "between": "bet {y}",
    },
    # The name index order. The English defaults sort alphabetically.
    "sort": {"expand": {}, "after_z": [], "ignore_particles": [], "mc_as_mac": False},
}

# The placeholders each leaf of DEFAULT_STRINGS may use
# (a test keeps this in step with DEFAULT_STRINGS)
PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "title": (),
    "living_name": (),
    "fan_title": ("name",),
    "meta_title": ("title", "name"),
    "footer": ("date",),
    "footer_blank": (),
    "date_format": ("day", "month", "year"),
    "day_one": (),
    "chart_label": ("n",),
    "continuation": ("pos", "chart"),
    "chart_note": (),
    "ellipsis": (),
    "page_number": ("page", "pages"),
    "record_id": ("id",),
    "months.short": (),
    "index.title": (),
    "index.born": ("birth",),
    "index.died": ("death",),
    "index.joiner": (),
    "index.years": ("years",),
    "index.christened": ("birth",),
    "index.buried": ("death",),
    "index.cremated": ("death",),
    "index.legend": (),
    **{f"relationship.{key}": () for key in DEFAULT_STRINGS["relationship"]},
    **{f"labels.{key}": () for key in DEFAULT_STRINGS["labels"]},
    **{f"dates.{key}": () for key in DEFAULT_STRINGS["dates"]},
    **{
        f"years.{key}": () if key == "deceased" else ("y",)
        for key in DEFAULT_STRINGS["years"]
    },
    "sort.expand": (),
    "sort.after_z": (),
    "sort.ignore_particles": (),
    "sort.mc_as_mac": (),
}

# A template field is {name}, where name is one of the placeholders its key
# allows; {{ and }} are literal braces. Nothing else in braces is allowed
# (see fill), so a language file cannot format, convert or index a value.
_TEMPLATE_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")


def fill(template: str, allowed: tuple[str, ...], values: Mapping[str, Any]) -> str:
    """`template` with each {name} replaced by str(values[name]), for the names in
    `allowed`; {{ and }} give literal braces. Anything else in braces (a format spec, a
    conversion, attribute or index access, an unknown or empty name) and any unpaired
    brace raises ValueError saying what is wrong. A substituted value is never read as a
    template.
    """
    out, pos = [], 0
    for m in _TEMPLATE_TOKEN.finditer(template):
        out.append(template[pos : m.start()])
        pos = m.end()
        token, name = m.group(0), m.group(1)
        if token in ("{{", "}}"):
            out.append(token[0])
        elif name is None:
            raise ValueError(
                "has a brace that is not paired; write {{ or }} for a literal brace"
            )
        elif name in allowed:
            out.append(str(values[name]))
        else:
            names = (
                ", ".join("{" + allowed_name + "}" for allowed_name in allowed)
                or "none"
            )
            raise ValueError(
                f"uses {{{name}}}, which is not a plain placeholder for this text; "
                f"the placeholders here are {names}"
            )
    out.append(template[pos:])
    return "".join(out)


# the bundled language files (package data), beside this module
LANG_DIR = Path(__file__).resolve().parent / "lang"


def _user_lang_dir() -> Path | None:
    """The per-user language folder, or None where no home folder can be found (as in
    some containers): then there is none. It is found only when a lookup needs it, so
    kincade imports, and a bundled language loads, without a home folder."""
    try:
        return Path.home() / ".config" / "kincade" / "lang"
    except RuntimeError:  # Path.home() with no HOME and no account entry
        return None


class LangError(ValueError):
    """A language file or a strings argument that cannot be used. The message says what
    is wrong.
    """


class KincadeWarning(UserWarning):
    """A recoverable library condition, such as ignored wording or font fallback."""


def expand_home(text: str) -> str:
    """`text` with a leading ~ (or ~user) replaced by that home folder. A ~user with no
    such account is a ValueError.
    """
    if not text.startswith("~"):
        return text
    expanded = os.path.expanduser(text)
    if expanded.startswith("~"):
        raise ValueError(f"cannot find the home folder of {text.split('/')[0]}")
    return expanded


def lang_path(value: str) -> Path:
    """The file for a language VALUE: a name is looked up as <name>.toml in LANG_DIR,
    then in the per-user folder ~/.config/kincade/lang (if there is a home folder); a
    value that ends in .toml or contains a path separator is a path, used as given (~
    expanded). A NUL character, an unknown ~user, or a name the file system cannot look
    up (too long, say) is a LangError.
    """
    if "\x00" in value:
        raise LangError(f"language {value!r} cannot contain a NUL character")
    if value.endswith(".toml") or re.search(r"[\\/]", value):
        try:
            return Path(expand_home(value))
        except ValueError as e:
            raise LangError(f"cannot use language file {value!r}: {e}") from None
    if _is_lang_file(LANG_DIR, value):
        return LANG_DIR / f"{value}.toml"
    user = _user_lang_dir()
    if user is None:
        raise LangError(f"no language file {value}.toml in {LANG_DIR}")
    if _is_lang_file(user, value):
        return user / f"{value}.toml"
    raise LangError(f"no language file {value}.toml in {LANG_DIR} or {user}")


def _is_lang_file(folder: Path, value: str) -> bool:
    """Whether `folder` holds <value>.toml. A name the file system cannot look up is a
    LangError."""
    try:
        return (folder / f"{value}.toml").is_file()
    # e.g. a name longer than the file system allows
    except (OSError, ValueError) as e:
        raise LangError(
            f"cannot look for language file {value}.toml in {folder}: "
            f"{getattr(e, 'strerror', None) or e}"
        ) from None


def _check_text(source: str, path: str, text: str, allowed: tuple[str, ...]) -> None:
    """A plain text has no placeholders, so no braces. A template may use only its own
    placeholders, each as a plain {name}: fill tries the template out, so an unknown
    name, a format spec or a broken brace is a LangError here, at load time, and names
    the key.
    """
    if not allowed:
        if "{" in text or "}" in text:
            raise LangError(
                f"{source}: {path} takes no placeholders, so it cannot contain braces"
            )
        return
    try:
        fill(text, allowed, dict.fromkeys(allowed, ""))
    except ValueError as e:
        raise LangError(f"{source}: {path} {e}") from None


def _check_leaf(source: str, path: str, value: Any, default: Any) -> Any:
    if isinstance(default, list):
        if not (
            isinstance(value, list)
            and len(value) == len(default)
            and all(isinstance(v, str) for v in value)
        ):
            raise LangError(
                f"{source}: {path} must be a list of {len(default)} strings"
            )
        for name in value:
            _check_text(source, path, name, ())
        return list(value)
    if not isinstance(value, str):
        raise LangError(f"{source}: {path} must be a string")
    if path == "ellipsis" and not 1 <= len(value) <= 3:
        raise LangError(
            f"{source}: ellipsis must be 1 to 3 characters, not {len(value)}"
        )
    _check_text(source, path, value, PLACEHOLDERS[path])
    return value


def _sort_text(text: str) -> str:
    """Text as the index sort reads it: casefolded, and NFC so that decomposed accents
    (macOS) match composed ones.
    """
    return unicodedata.normalize("NFC", text.casefold())


def _letters_digits_and_spaces(text: str) -> str:
    """The sort key without punctuation: every character that is not a letter or digit
    is dropped, other whitespace becomes a space, and runs of spaces collapse to one
    (with none at either end). "[HARTLEY] DAWSON" files as "hartley dawson", "O'Brien"
    as "obrien", "St. John" as "st john". Applied before the [sort] settings, so the "~"
    of an expansion and the after_z sentinels are not dropped.
    """
    kept = "".join(ch if ch.isalnum() else " " if ch.isspace() else "" for ch in text)
    return squash(kept)


# The [sort] settings. Their types differ from the template texts, so each has its own
# check, which returns the value in the form SortRules reads. `expand` adds to the table
# below it (a key of the same text is replaced); the two lists replace the list below.


def _check_mc_as_mac(source: str, path: str, value: Any, base: Any) -> bool:
    if not isinstance(value, bool):
        raise LangError(f"{source}: {path} must be true or false")
    return value


def _check_expand(source: str, path: str, value: Any, base: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise LangError(
            f'{source}: {path} must be a table of text = replacement, such as ñ = "n~"'
        )
    out = dict(base)
    for key, replacement in value.items():
        if not isinstance(key, str) or not key.strip():
            raise LangError(f"{source}: {path} keys must be non-empty text")
        if not isinstance(replacement, str):
            raise LangError(f"{source}: {path}[{key!r}] must be a string")
        out[_sort_text(key)] = _sort_text(replacement)
    return out


def _check_after_z(source: str, path: str, value: Any, base: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise LangError(
            f'{source}: {path} must be a list of single letters, such as ["å", "ä", "ö"]'
        )
    letters = []
    for item in value:
        letter = _sort_text(item)
        if len(letter) != 1:
            raise LangError(
                f"{source}: {path} item {item!r} must be a single character"
            )
        letters.append(letter)
    if len(set(letters)) != len(letters):
        raise LangError(f"{source}: {path} lists a letter more than once")
    return letters


# the apostrophes an elided particle may end with, read as the first
_APOSTROPHES = str.maketrans("’ʼ", "''")


def _check_ignore_particles(source: str, path: str, value: Any, base: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise LangError(
            f'{source}: {path} must be a list of words, such as ["van", "der"]'
        )
    words = []
    for item in value:
        if item.split() != [item]:
            raise LangError(
                f"{source}: {path} item {item!r} must be one word (no spaces)"
            )
        word = _sort_text(item).translate(_APOSTROPHES)
        if "'" in word[:-1] or word == "'":
            raise LangError(
                f"{source}: {path} item {item!r} may have an apostrophe only at "
                "its end, after the particle, as in d’"
            )
        words.append(word)
    return words


_SORT_CHECKS = {
    "sort.expand": _check_expand,
    "sort.after_z": _check_after_z,
    "sort.ignore_particles": _check_ignore_particles,
    "sort.mc_as_mac": _check_mc_as_mac,
}


def _layer(
    base: dict[str, Any],
    over: Mapping[str, Any],
    source: str,
    notes: list[str],
    prefix: str = "",
) -> dict[str, Any]:
    """`base` with the values of `over` laid on top. Unknown keys are noted and ignored;
    a value must match the type of the English value it replaces (and, for a text, its
    placeholders).
    """
    out = dict(base)
    for key, value in over.items():
        path = f"{prefix}{key}"
        if key not in base:
            notes.append(f"{source}: unknown key {path!r} ignored")
        elif path in _SORT_CHECKS:
            out[key] = _SORT_CHECKS[path](source, path, value, base[key])
        elif isinstance(base[key], dict):
            if not isinstance(value, Mapping):
                raise LangError(f"{source}: {path} must be a table")
            out[key] = _layer(base[key], value, source, notes, f"{path}.")
        else:
            out[key] = _check_leaf(source, path, value, base[key])
    return out


def load_strings(
    lang: str | None = None, strings: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The strings a render uses: the English DEFAULT_STRINGS, then the language file
    `lang` (a name or a path, see lang_path), then `strings` (a partial or complete
    override). Each layer replaces the values it supplies. Each unknown key emits
    a KincadeWarning and is ignored. A value of the wrong type or a placeholder that
    is not allowed there raises LangError.
    """
    notes: list[str] = []
    resolved = copy.deepcopy(DEFAULT_STRINGS)
    if lang is not None:
        path = lang_path(lang)
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except OSError as e:
            raise LangError(
                f"cannot read language file {path}: {e.strerror or e}"
            ) from None
        # TOML errors, bad UTF-8, and a number too long for tomllib (all ValueErrors)
        except ValueError as e:
            raise LangError(
                f"language file {path} is not valid TOML: {squash(str(e))}"
            ) from None
        resolved = _layer(resolved, data, f"language file {path}", notes)
    if strings:
        resolved = _layer(resolved, strings, "strings", notes)
    for note in notes:
        warnings.warn(note, KincadeWarning, stacklevel=2)
    return resolved


def map_leaves(node: Any, fn: Callable[[str], str]) -> Any:
    """A copy of a strings dict with fn applied to each string leaf, including list
    items. Keys and non-string values, such as mc_as_mac, are copied as given."""
    if isinstance(node, dict):
        return {key: map_leaves(value, fn) for key, value in node.items()}
    if isinstance(node, list):
        return [fn(value) if isinstance(value, str) else value for value in node]
    return fn(node) if isinstance(node, str) else node


# --------------------------------------------------------------------------
# Display formatting
# --------------------------------------------------------------------------


def is_placeholder_surname(surname: str) -> bool:
    """'(UNKNOWN)', 'Unknown', 'UNK', 'NN', 'N.N.', '?', '___' and the like: no real
    surname to sort by.
    """
    core = surname.strip().strip("()[]{} \t").strip().casefold()
    return (
        not core
        or core in {"unknown", "unk", "nn", "n.n", "n.n."}
        or bool(re.fullmatch(r"[?_\-.*]+", core))
    )


def fmt_surname(surname: str, preserve_case: bool = False) -> str:
    s = surname.strip()
    if preserve_case:
        return s
    return "Mc" + s[2:].upper() if s.startswith("Mc") else s.upper()


def _with_suffix(name: str, suffix: str) -> str:
    suffix = squash(suffix)
    if not suffix:
        return name
    # ", Jr." hugs the name
    return name + suffix if suffix.startswith(",") else f"{name} {suffix}".strip()


def display_name(p: Person, preserve_case: bool = False) -> str:
    """Single-spaced name; uppercase the surname unless preserve_case is set."""
    return _with_suffix(
        squash(f"{p.prefix} {p.given} {fmt_surname(p.surname, preserve_case)}"),
        p.suffix,
    )


def _day_text(day: Day, strings: Mapping[str, Any]) -> str:
    """One date as text: the month in the language's short name, the 1st as day_one, a
    full date (day, month and year) laid out by the date_format template, a double year
    as 1731/32. A date with parts missing prints what it has, day month year.
    """
    year = ""
    if day.year is not None:
        year = (
            f"{day.year}/{day.dual_year % 100:02d}"
            if day.dual_year is not None
            else str(day.year)
        )
    month = strings["months"]["short"][day.month - 1] if day.month else ""
    number = day_number(day.day, strings) if day.day is not None else ""
    if number and month and year:
        return fill(
            strings["date_format"],
            PLACEHOLDERS["date_format"],
            {"day": number, "month": month, "year": year},
        )
    return " ".join(part for part in (number, month, year) if part)


def day_number(day: int, strings: Mapping[str, Any]) -> str:
    """The day of the month as a date prints it: the language's day_one for the 1st
    (French 1er), else the number."""
    return strings["day_one"] if day == 1 else str(day)


def format_date(date: Date | None, strings: Mapping[str, Any] = DEFAULT_STRINGS) -> str:
    """A date as display text in the language of `strings`: the date's own `text` when
    it has one, else its structure in the language's words (abt, est, bef, aft, from,
    to, and the dash between the two ends of a range). "" for no date.
    """
    if date is None:
        return ""
    if date.text:
        return date.text
    words = strings["dates"]
    ends = [_day_text(day, strings) for day in (date.start, date.end) if day]
    if not ends:
        return ""
    keys = [
        date.quality,
        date.form if date.form in ("about", "before", "after", "from", "to") else "",
    ]
    return "".join(words[key] + " " for key in keys if key) + words["range"].join(ends)


def year_of(date: Date | None) -> int | None:
    """The index year: the first structured year as written (the first year of a double
    date), else the first year of a recognized whole-text shape (model.text_date, also
    used by privacy and --find). None for unrecognized text, no year, or a date whose
    year cannot be read (Date.year_unknown)."""
    if date is None or date.year_unknown:
        return None
    for day in (date.start, date.end):
        if day and day.year is not None:
            return day.year
    reading = text_date(date.text)
    return reading.start.year if reading and reading.start else None


def index_name(p: Person, preserve_case: bool = False) -> str:
    """'SURNAME, prefix given suffix' as the index prints a name (the surname alone, or
    the rest alone, if the other is missing). preserve_case keeps recorded case.
    """
    rest = _with_suffix(squash(f"{p.prefix} {p.given}"), p.suffix)
    surname = fmt_surname(p.surname, preserve_case)
    return f"{surname}, {rest}" if surname and rest else surname or rest


# --------------------------------------------------------------------------
# Index sort rules
# --------------------------------------------------------------------------


# the first private-use character: after_z letter i sorts as chr(_AFTER_Z + i)
_AFTER_Z = 0xE000


class SortRules:
    """The [sort] settings of a language as a sort key. fold(text) gives the key of one
    name part.

    Order of operations: casefold and NFC; then, for a surname only, an elided particle
    (one of ignore_particles that ends in an apostrophe, such as d’) is dropped from the
    front; then punctuation is dropped (letters, digits and spaces only); then, for a
    surname only, the other ignore_particles and mc_as_mac; then
    expand (one pass, longest key first, so a replacement is never replaced again);
    then after_z letters become sentinels that sort after z and after the "~" of any
    expansion; and last NFKD accent folding, which drops the combining marks. The
    settings must already be checked (load_strings does that). The text itself is never
    changed; only the key it sorts by.
    """

    def __init__(self, sort: Mapping[str, Any]) -> None:
        # a partial table keeps the English value of what it leaves out
        sort = {**DEFAULT_STRINGS["sort"], **sort}
        particles = sort["ignore_particles"]
        self.particles = frozenset(p for p in particles if not p.endswith("'"))
        # longest first, so "dell'" is tried before "d'"
        self.elided = sorted(
            (p for p in particles if p.endswith("'")), key=len, reverse=True
        )
        self.mc_as_mac = sort["mc_as_mac"]
        self.after_z = {
            letter: chr(_AFTER_Z + i) for i, letter in enumerate(sort["after_z"])
        }
        self.expand = dict(sort["expand"])
        # longest first, so "sch" is tried before "s"
        keys = sorted(self.expand, key=len, reverse=True)
        self._expand_re = re.compile("|".join(map(re.escape, keys))) if keys else None

    def fold(self, text: str, surname: bool = False) -> str:
        s = _sort_text(text)
        if surname and self.elided:
            s = self._skip_elided(s)
        s = _letters_digits_and_spaces(s)
        if surname:
            s = self._skip_particles(s)
            if self.mc_as_mac and s.startswith("mc"):
                s = "mac" + s[2:]
        if self._expand_re is not None:
            s = self._expand_re.sub(lambda m: self.expand[m.group(0)], s)
        if self.after_z:
            s = "".join(self.after_z.get(ch, ch) for ch in s)
        return "".join(
            ch
            for ch in unicodedata.normalize("NFKD", s)
            if not unicodedata.combining(ch)
        )

    def _skip_elided(self, s: str) -> str:
        """Drop an elided particle from the front, if a name is left after it (so
        "d’Artagnan" files as "artagnan", but "D’" stays as it is)."""
        front = s.lstrip().translate(_APOSTROPHES)
        for particle in self.elided:
            rest = front[len(particle) :]
            if front.startswith(particle) and _letters_digits_and_spaces(rest):
                return rest
        return s

    def _skip_particles(self, s: str) -> str:
        """Drop particles from the front, whole words only, but never the last word (so
        "Van" stays "van").
        """
        words = s.split()
        i = 0
        while i < len(words) - 1 and words[i] in self.particles:
            i += 1
        return " ".join(words[i:]) if i else s

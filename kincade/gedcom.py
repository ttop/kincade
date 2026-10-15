"""Reading GEDCOM: everything specific to the format lives here (encodings, lines,
CONC/CONT, the events and names Kincade uses) and nothing past read_gedcom() knows it
was GEDCOM. Imports only the model.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypedDict

from .model import (
    Date,
    Day,
    Event,
    Family,
    ParentLink,
    Person,
    Tree,
    squash,
    strip_controls,
    text_date,
)

# fmt: off
_ANSEL_COMBINING = {  # ANSEL diacritics precede their base letter
    0xE0: "\u0309", 0xE1: "\u0300", 0xE2: "\u0301", 0xE3: "\u0302",
    0xE4: "\u0303", 0xE5: "\u0304", 0xE6: "\u0306", 0xE7: "\u0307",
    0xE8: "\u0308", 0xE9: "\u030c", 0xEA: "\u030a", 0xEB: "\ufe20",
    0xEC: "\ufe21", 0xED: "\u0315", 0xEE: "\u030b", 0xEF: "\u0310",
    0xF0: "\u0327", 0xF1: "\u0328", 0xF2: "\u0323", 0xF3: "\u0324",
    0xF4: "\u0325", 0xF5: "\u0333", 0xF6: "\u0332", 0xF7: "\u0326",
    0xF8: "\u031c", 0xF9: "\u032e", 0xFA: "\ufe22", 0xFB: "\ufe23",
    0xFE: "\u0313",
}
_ANSEL_BASE = {  # ANSEL letters above 0x7F
    0xA1: "\u0141", 0xA2: "\u00d8", 0xA3: "\u0110", 0xA4: "\u00de",
    0xA5: "\u00c6", 0xA6: "\u0152", 0xA7: "\u02b9", 0xA8: "\u00b7",
    0xA9: "\u266d", 0xAA: "\u00ae", 0xAB: "\u00b1", 0xAC: "\u01a0",
    0xAD: "\u01af", 0xAE: "\u02bc", 0xB0: "\u02bb", 0xB1: "\u0142",
    0xB2: "\u00f8", 0xB3: "\u0111", 0xB4: "\u00fe", 0xB5: "\u00e6",
    0xB6: "\u0153", 0xB7: "\u02ba", 0xB8: "\u0131", 0xB9: "\u00a3",
    0xBA: "\u00f0", 0xBC: "\u01a1", 0xBD: "\u01b0", 0xC0: "\u00b0",
    0xC1: "\u2113", 0xC2: "\u2117", 0xC3: "\u00a9", 0xC4: "\u266f",
    0xC5: "\u00bf", 0xC6: "\u00a1", 0xC7: "\u00df", 0xCF: "\u00df",
}
# fmt: on


def _decode_ansel(data: bytes) -> str:
    out, marks = [], ""
    for b in data:
        if b in _ANSEL_COMBINING:
            marks += _ANSEL_COMBINING[b]
            continue
        ch = chr(b) if b < 0x80 else _ANSEL_BASE.get(b, "?")
        out.append(unicodedata.normalize("NFC", ch + marks))
        marks = ""
    return "".join(out)


_CODECS = {
    "ANSI": "cp1252",
    "WINDOWS": "cp1252",
    "WINDOWS-1252": "cp1252",
    "CP1252": "cp1252",
    "IBMPC": "cp437",
    "IBM": "cp437",
    "OEM": "cp437",
    "CP437": "cp437",
}


def _declared_charset(data: bytes) -> str:
    """The CHAR value of the HEAD record (scanned to the next level-0 line),
    upper-cased, or ''.
    """
    head = re.match(rb"\s*0[ \t]+HEAD\b(.*?)(?:[\r\n]\s*0[ \t]|\Z)", data, re.DOTALL)
    m = head and re.search(rb"[\r\n][ \t]*1[ \t]+CHAR[ \t]+(\S+)", head[1])
    return m[1].decode("latin-1").upper() if m else ""


def _decode_gedcom(data: bytes) -> str:
    """Bytes -> text. BOMs and BOM-less UTF-16 first, then the header's CHAR value
    decides: ANSEL, cp1252 (ANSI), cp437 (IBMPC); anything else (UTF-8, ASCII, none,
    GEDCOM 7) is UTF-8, falling back to cp1252.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    # "0 H.." as UTF-16 LE
    if len(data) >= 4 and data[0] and data[2] and not data[1] and not data[3]:
        return data.decode("utf-16-le", "replace")
    # ... and big-endian
    if len(data) >= 4 and not data[0] and not data[2] and data[1] and data[3]:
        return data.decode("utf-16-be", "replace")
    declared = _declared_charset(data)
    if declared == "ANSEL":
        return _decode_ansel(data)
    if declared in _CODECS:  # an explicit legacy code page: never guess UTF-8 for it
        return data.decode(_CODECS[declared], "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


@dataclass
class _Node:
    tag: str
    value: str = ""
    xref: str = ""
    children: list[_Node] = field(default_factory=list)


# levels: 1-2 digits
_LINE = re.compile(
    r"\s*(\d{1,2})[ \t]+(?:(@[^@\s]+@)[ \t]+)?([A-Za-z0-9_]+)(?:[ \t](.*))?$"
)


def _unescape_at(value: str, gedcom7: bool) -> str:
    """GEDCOM 5.5.x doubles every '@' in a line's value; 7.0 only a leading one.
    Pointers have no '@@'.
    """
    if "@@" not in value:
        return value
    if not gedcom7:
        return value.replace("@@", "@")
    return value[1:] if value.startswith("@@") else value


def _parse_records(text: str) -> list[_Node]:
    """Level-0 records with their children; CONC/CONT folded into the parent value.
    A skipped level attaches to the nearest preceding node at a lower level.
    """
    records: list[_Node] = []
    stack: list[tuple[int, _Node]] = []
    # set by HEAD.GEDC.VERS; decides the '@@' rule, applied to every physical line
    gedcom7 = False
    # never str.splitlines (U+2028)
    for raw in re.split(r"\r\n|\r|\n", text.lstrip("\ufeff")):
        m = _LINE.match(strip_controls(raw))
        if not m:
            continue
        level, xref, tag, value = (
            int(m[1]),
            m[2] or "",
            m[3].upper(),
            _unescape_at(m[4] or "", gedcom7),
        )
        if level == 0:
            node = _Node(tag, value, xref)
            stack = [(level, node)]
            records.append(node)
            continue
        if not stack:
            continue
        while stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        if tag == "CONC":
            parent.value += value
        elif tag == "CONT":
            parent.value += "\n" + value
        else:
            node = _Node(tag, value, xref)
            stack.append((level, node))
            parent.children.append(node)
            if tag == "VERS" and parent.tag == "GEDC":
                gedcom7 = value.strip().startswith("7")
    return records


def _first(node: _Node | None, tag: str) -> _Node | None:
    return next((c for c in node.children if c.tag == tag), None) if node else None


def _sub(node: _Node | None, tag: str) -> str:
    child = _first(node, tag)
    return child.value.strip() if child else ""


def _id(xref: str) -> str:
    """A record ID or a pointer to it without the `@` delimiters. The model stores
    record IDs as plain names, so `@I12@` is `I12` in people, families and every
    reference.
    """
    return xref.strip().strip("@")


# --------------------------------------------------------------------------
# Dates: GEDCOM grammar -> model.Date. Non-grammar text keeps its words in Date.text
# and is printed as written; model.text_date owns its recognized date shapes.
# --------------------------------------------------------------------------

# GEDCOM month codes are English, regardless of the output language.
_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC"
_MONTH_CODES = {code: n for n, code in enumerate(_MONTHS.split(), 1)}
_QUALIFIERS = {  # a date qualifier -> (form, quality)
    "ABT": ("about", ""),
    "ABOUT": ("about", ""),
    "CA": ("about", ""),
    "CIRCA": ("about", ""),
    "EST": ("exact", "estimated"),
    "CAL": ("exact", "calculated"),
    "BEF": ("before", ""),
    "BEFORE": ("before", ""),
    "AFT": ("after", ""),
    "AFTER": ("after", ""),
}
# "(a phrase)", or "INT date (a phrase)"
_PHRASE = re.compile(r"(?:INT\s+([^(]*))?\((.*)\)", re.IGNORECASE)
_RANGE = re.compile(r"BET\.?\s+(.+?)\s+(?:AND|-)\s+(.+)", re.IGNORECASE)
_PERIOD = re.compile(r"FROM\s+(.+?)\s+TO\s+(.+)", re.IGNORECASE)
_HALF_PERIOD = re.compile(r"(FROM|TO)\s+(.+)", re.IGNORECASE)
_QUALIFIED = re.compile(r"([A-Za-z]+)\.?\s+(.+)")
_TILDE = re.compile(r"~\s*(.+)")  # the short form of ABT
_CALENDAR = re.compile(
    r"(?:@#D[^@]*@|(?:JULIAN|GREGORIAN|HEBREW|FRENCH_R)\b)\s*(.*)", re.IGNORECASE
)
# A calendar this reader cannot convert, wherever it stands in a text: any escape but
# Julian and Gregorian (@#DHEBREW@, @#DFRENCH R@, @#DROMAN@, @#DUNKNOWN@, @#D@), the
# keyword FRENCH_R, and the keyword HEBREW where a date follows it (a number or a Hebrew
# month code: HEBREW 1 TSH 5650, HEBREW TSH 5650, HEBREW 5650). "Hebrew" is also an
# English word; prose that names it ("Hebrew New Year 1890") is unrecognized date text.
# Julian is within a year of Gregorian and is read as written.
_UNREAD_CALENDAR = re.compile(
    r"@#D(?!(?:JULIAN|GREGORIAN)@)[^@]*@|\bFRENCH_R\b"
    r"|\bHEBREW\s+(?:\d|(?:TSH|CSH|KSL|TVT|SHV|ADR|ADS|NSN|IYR|SVN|TMZ|AAV|ELL)\b)",
    re.IGNORECASE,
)
# A number that cannot be a year of ours, in any date: five digits or more (never
# converted), or year 0.
_UNREAD_NUMBER = re.compile(r"\d{5,}|(?<!\d)0{3,4}(?!\d)")
# a year token, optionally a double year such as 1731/32
_NUMBER = re.compile(r"(\d+)(?:/(\d+))?")


def _year_token(token: str) -> tuple[int, int | None] | None:
    """(year, dual year) of a year as GEDCOM writes it, or None. A year has three or
    four digits (0099 is 99; a shorter number may be an abbreviated 1985, so it is no
    year), and is not 0; a longer one is never converted. A double date must have the
    form 1731/32: the new-style year is the next one, written with its last two digits
    (1699/00 is 1699 and 1700, 9999/00 is no date); anything else is not read.
    """
    m = _NUMBER.fullmatch(token)
    if not m or not 3 <= len(m[1]) <= 4 or not (year := int(m[1])):
        return None
    if m[2] is None:
        return year, None
    return (
        (year, year + 1)
        if len(m[2]) == 2 and int(m[2]) == (year + 1) % 100 and year < 9999
        else None
    )


def _day_number(token: str) -> int | None:
    """A day of the month: one or two digits, 1 to 31. None for anything else, so that
    "45 JAN 1900" is no date and stays text."""
    return (
        int(token)
        if re.fullmatch(r"\d{1,2}", token) and 1 <= int(token) <= 31
        else None
    )


def _day(text: str) -> Day | None:
    """A date with no qualifier: a year, a day alone, a month, a month and year, a day
    and month, or a day, month and year. A calendar escape (@#DJULIAN@) or keyword
    (JULIAN) in front is dropped; the date is shown as written in whatever calendar.
    None for anything else.
    """
    text = text.strip()
    if m := _CALENDAR.fullmatch(text):
        text = m[1]
    tokens = text.split()
    months = [_MONTH_CODES.get(token.upper().rstrip(".")) for token in tokens]
    shape = "".join("M" if month else "N" for month in months)
    if shape == "N":
        if year := _year_token(tokens[0]):
            return Day(year[0], dual_year=year[1])
        day = _day_number(tokens[0])  # a day: BET. 12 - 13 SEP 1987
        return Day(day=day) if day else None
    if shape == "M":
        return Day(month=months[0])
    if shape == "MN":
        year = _year_token(tokens[1])
        return Day(year[0], months[0], dual_year=year[1]) if year else None
    if shape == "NM" and (day := _day_number(tokens[0])):
        return Day(month=months[1], day=day)
    if (
        shape == "NMN"
        and (day := _day_number(tokens[0]))
        and (year := _year_token(tokens[2]))
    ):
        return Day(year[0], months[1], day, year[1])
    return None


def _free(text: str) -> Date:
    """Date text printed as written, with a form from model.text_date's recognized
    whole-text shapes. Unrecognized text has no date reading."""
    reading = text_date(text)
    form = (
        reading.form
        if reading and reading.form in ("about", "before", "after", "from", "to")
        else "text"
    )
    return Date(form, quality=reading.quality if reading else "", text=text)


def _unreadable(date: Date, text: str) -> Date:
    """`date`, marked `year_unknown` if `text`, the words it was read from, has a
    calendar this reader cannot convert (`_UNREAD_CALENDAR`: an escape anywhere in it,
    and the keyword HEBREW only where a date follows it) or a number that is no year of
    ours (see `parse_date`). Such a date keeps `text` as its text, so it prints as
    written: its numbers are no years to print in the structure's form."""
    return (
        replace(date, year_unknown=True, text=date.text or text)
        if _UNREAD_CALENDAR.search(text) or _UNREAD_NUMBER.search(text)
        else date
    )


def parse_date(raw: str | None) -> Date | None:
    """GEDCOM date text -> Date; None for no text. The forms: a date; ABT, EST, CAL,
    BEF, AFT before one (CA, CIRCA and ~ mean ABT); BET a AND b (or a - b); FROM a TO b;
    FROM a; TO b; "(a phrase)", and INT a (a phrase), which prints the phrase and keeps
    a as its structure. Text that none of them describes (a month name not spelled as
    three letters, "1765-1767", a stray word) is returned as free text, printed as
    written.

    A date in a calendar this reader cannot convert (Hebrew, French Republican, any
    escape but Julian and Gregorian) is read and printed as written, in whatever
    calendar, and marked `year_unknown`: the numbers in it are not years of ours. So is
    a date with a number that is no year of ours (five digits or more, or 0), which is
    kept as text, and an INT date whose interpreted date is no structure, since the
    phrase replaces the only reading it had. The keyword HEBREW names the calendar only
    where a date follows it (HEBREW 1 TSH 5650, HEBREW 5650); elsewhere it is the
    English word. Prose such as "(Hebrew New Year 1890)" has no recognized date shape
    (see model.text_date).
    """
    s = squash(raw)
    if not s:
        return None
    if m := _PHRASE.fullmatch(s):
        return _phrased(parse_date(m[1]) if m[1] else None, m[2].strip(), s)
    return _unreadable(_plain(s), s)


def _phrased(base: Date | None, phrase: str, written: str) -> Date:
    """A date printed as its phrase, keeping any interpreted structure. With no base,
    the phrase alone is read by model.text_date's whole-text shapes. An unsupported
    calendar or unreadable year marks that sole reading as `year_unknown`. An empty
    phrase keeps the base. A base with no structure is replaced by the phrase and
    marked `year_unknown`, since its interpreted reading is unavailable."""
    if base is None:
        text = phrase or written
        return _unreadable(_free(text), text)
    if not phrase:
        return base
    return replace(
        base,
        text=phrase,
        year_unknown=base.year_unknown or (base.start is None and base.end is None),
    )


def _plain(s: str) -> Date:
    """The date in `s` (squashed, not empty, no phrase), as parse_date describes."""
    if m := (_RANGE.fullmatch(s) or _PERIOD.fullmatch(s)):
        first, second = _day(m[1]), _day(m[2])
        return (
            Date("between" if m.re is _RANGE else "from_to", first, second)
            if first and second
            else _free(s)
        )
    if m := _HALF_PERIOD.fullmatch(s):
        day = _day(m[2])
        return Date(m[1].lower(), day) if day else _free(s)
    if m := _QUALIFIED.fullmatch(s):
        if (qualifier := _QUALIFIERS.get(m[1].upper())) and (day := _day(m[2])):
            return Date(qualifier[0], day, quality=qualifier[1])
        if qualifier:
            return _free(s)
    elif m := _TILDE.fullmatch(s):
        return Date("about", day) if (day := _day(m[1])) else _free(s)
    return Date("exact", day) if (day := _day(s)) else _free(s)


# --------------------------------------------------------------------------
# Events, names, relationships
# --------------------------------------------------------------------------


def _date(node: _Node | None) -> Date | None:
    """The date of an event's DATE line. GEDCOM 7 may put a PHRASE under it: with an
    empty payload the phrase is the date (`2 DATE` / `3 PHRASE 5 January (year unknown)`
    is the text "5 January (year unknown)", a recorded date with no year to read; `3
    PHRASE AFTER 1900` is the text "AFTER 1900", open-ended as AFT 1900 is); a payload
    that reads as a date keeps its structure for printing and for the estimate, and the
    phrase is not used; a payload that is only text gives way to the phrase, as an INT
    date's reading does.
    """
    if node is None:
        return None
    date, phrase = parse_date(node.value), squash(_sub(node, "PHRASE"))
    if phrase and (date is None or (date.start is None and date.end is None)):
        return _phrased(date, phrase, phrase)
    return date


def _event(node: _Node) -> Event:
    """An event's date and the first line of its place."""
    return Event(_date(_first(node, "DATE")), _sub(node, "PLAC").split("\n")[0].strip())


def _first_event(rec: _Node, tag: str) -> Event | None:
    node = _first(rec, tag)
    return _event(node) if node else None


_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def _tokens(text: str) -> list[str]:
    """Case-folded words with surrounding commas, periods and semicolons removed."""
    return [t for t in (w.strip(",.;").casefold() for w in text.split()) if t]


class _Names(TypedDict):
    given: str
    surname: str
    prefix: str
    suffix: str


def _person_names(node: _Node) -> _Names:
    """Names from the NAME payload (primary); NPFX/NSFX only add what the payload does
    not already carry.
    """
    name = _first(node, "NAME")
    value = name.value if name else ""
    m = re.fullmatch(r"(.*?)/(.*)/(.*)", value, re.DOTALL) or re.fullmatch(
        r"(.*?)/(.*)()", value, re.DOTALL
    )
    given, surname, trailing = (m[1], m[2], m[3]) if m else (value, "", "")
    given, surname, trailing = given.strip(), surname.strip(), trailing.strip()
    given = given or _sub(name, "GIVN")
    surname = surname or _sub(name, "SURN")
    prefix, nsfx = _sub(name, "NPFX"), _sub(name, "NSFX")
    words, want = given.split(), _tokens(prefix)
    if want and [w.strip(",.;").casefold() for w in words[: len(want)]] == want:
        # "Dr. Alice" + NPFX "Dr.": whole leading tokens only (not Nasir/Sir)
        given = " ".join(words[len(want) :])
    braced = re.fullmatch(r"\{(.*)\}", surname)
    if braced:  # braces in the surname field mark a title
        prefix, surname = prefix or braced[1], ""
    # a suffix in the surname field follows the given name
    elif given and surname.casefold() in _SUFFIXES:
        trailing, surname = f"{surname} {trailing}".strip(), ""
    nsfx_tokens = _tokens(nsfx)
    # whole trailing tokens only
    if nsfx and _tokens(trailing)[-len(nsfx_tokens) :] != nsfx_tokens:
        trailing = trailing + ("" if nsfx.startswith(",") else " ") + nsfx
    return {
        "given": given,
        "surname": surname,
        "prefix": prefix,
        "suffix": trailing.strip(),
    }


# lower-case PEDI value -> relationship (to both parents); anything else says nothing
_PEDI_WORDS = {
    "birth": "birth",
    "adopted": "adopted",
    "foster": "foster",
    "other": "other",
    "sealing": "other",
    "step": "step",
    "stepchild": "step",  # nonstandard PEDI value
}
# lower-case _FREL / _MREL value -> relationship (to that parent);
# anything else says nothing
_PARENT_WORDS = {
    "natural": "birth",
    "birth": "birth",
    "adopted": "adopted",
    "step": "step",
    "stepchild": "step",
    "foster": "foster",
    "sponsored": "other",
    "family member": "other",
}


def _relationship_word(text: str) -> str | None:
    """The relationship a PEDI value names, ignoring case and surrounding space: GEDCOM
    5.5.1 has birth, adopted, foster and sealing, 7.0 birth, adopted, foster and other;
    sealing counts as other. Step and stepchild are no standard value but are read as
    step. None when the text says nothing (a blank, or a word that is no PEDI value).
    """
    return _PEDI_WORDS.get(squash(text.casefold()))


def _parent_relationship_word(text: str) -> str | None:
    """The relationship a _FREL or _MREL value names, ignoring case and surrounding
    space: natural or birth, adopted, step or stepchild, foster, sponsored or family
    member (other). None when the text says nothing (unknown, none, a blank, any other
    word).
    """
    return _PARENT_WORDS.get(squash(text.casefold()))


def _first_word(texts: Iterable[str], read: Callable[[str], str | None]) -> str | None:
    """The first of `texts` that `read` understands."""
    return next((word for text in texts if (word := read(text))), None)


def _adopters(rec: _Node) -> dict[str, set[str]]:
    """The parents of each family whom the person's adoption events say adopted them:
    {family: {"HUSB", "WIFE"}}. An event names its family in `2 FAMC` and, under it, the
    adopting parent in `3 ADOP` (HUSB, WIFE or BOTH); BOTH, a missing `3 ADOP` and any
    other text mean both parents.
    """
    out: dict[str, set[str]] = {}
    for event in (c for c in rec.children if c.tag == "ADOP"):
        for famc in (c for c in event.children if c.tag == "FAMC"):
            which = squash(_sub(famc, "ADOP")).upper()
            out.setdefault(_id(famc.value), set()).update(
                {which} if which in ("HUSB", "WIFE") else {"HUSB", "WIFE"}
            )
    return out


def _parent_links(
    rec: _Node, chil_lines: dict[tuple[str, str], list[_Node]]
) -> list[ParentLink]:
    """A person's parent links, one per FAMC line in order. How the person is related to
    the father and to the mother of each family is read, for each parent in turn, from
    the first of these that says: the _FREL or _MREL of a FAMC line naming the family or
    of the family's CHIL line for the person (`chil_lines`), the PEDI under a FAMC
    naming the family (both parents), an adoption event for the family (the parent it
    names, or both); else birth. A value that is not recognized says nothing, so the
    next source speaks.
    """
    famc = [c for c in rec.children if c.tag == "FAMC"]
    adopters = _adopters(rec)
    relationships: dict[str, tuple[str, str]] = {}
    for family in dict.fromkeys(_id(c.value) for c in famc):
        lines = [c for c in famc if _id(c.value) == family]
        # the lines that can carry _FREL and _MREL
        holders = lines + chil_lines.get((family, _id(rec.xref)), [])
        pedi = _first_word((_sub(c, "PEDI") for c in lines), _relationship_word)
        father, mother = (
            _first_word((_sub(c, tag) for c in holders), _parent_relationship_word)
            or pedi
            or ("adopted" if parent in adopters.get(family, ()) else None)
            or "birth"
            for tag, parent in (("_FREL", "HUSB"), ("_MREL", "WIFE"))
        )
        relationships[family] = father, mother
    return [ParentLink(_id(c.value), *relationships[_id(c.value)]) for c in famc]


def _build_tree(records: list[_Node]) -> Tree:
    tree = Tree()
    # (family, child) -> the CHIL lines of the family for that child
    chil_lines: dict[tuple[str, str], list[_Node]] = {}
    for rec in records:
        if rec.tag == "FAM" and rec.xref:
            for c in rec.children:
                if c.tag == "CHIL":
                    chil_lines.setdefault((_id(rec.xref), _id(c.value)), []).append(c)
    for rec in records:
        if rec.tag == "INDI" and rec.xref:
            tree.people[_id(rec.xref)] = Person(
                _id(rec.xref),
                **_person_names(rec),
                birth=_first_event(rec, "BIRT"),
                death=_first_event(rec, "DEAT"),
                christenings=[_event(c) for c in rec.children if c.tag == "CHR"]
                + [_event(c) for c in rec.children if c.tag == "BAPM"],
                burials=[_event(c) for c in rec.children if c.tag == "BURI"],
                cremations=[_event(c) for c in rec.children if c.tag == "CREM"],
                parents=_parent_links(rec, chil_lines),
                families=[_id(c.value) for c in rec.children if c.tag == "FAMS"],
            )
        elif rec.tag == "FAM" and rec.xref:
            tree.families[_id(rec.xref)] = Family(
                id=_id(rec.xref),
                father=_id(_sub(rec, "HUSB")),
                mother=_id(_sub(rec, "WIFE")),
                marriage=_first_event(rec, "MARR"),
                children=[_id(c.value) for c in rec.children if c.tag == "CHIL"],
            )
    return tree


def read_gedcom(source: str | Path | bytes | bytearray) -> Tree:
    """Read a tree from a file path (str or Path) or the file's bytes (bytes or
    bytearray). A str is always a path. The text is NFC-normalized once, here, so names,
    places and every other value hold composed accents (ë, not e and U+0308), whichever
    form the file used.
    """
    data = (
        bytes(source)
        if isinstance(source, (bytes, bytearray))
        else Path(source).read_bytes()
    )
    text = unicodedata.normalize("NFC", _decode_gedcom(data))
    return _build_tree(_parse_records(text))

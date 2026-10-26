"""Drawing: page geometry, fonts and kerning, chart pages and name index pages. render
plans and draws a pedigree; render_pdf draws supplied charts; render_blank draws one
empty chart. Each returns PDF bytes. Imports model, charts, lang and reportlab.
"""

from __future__ import annotations

import datetime
import functools
import hashlib
import io
import os
import struct
import unicodedata
import warnings
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

from reportlab.pdfbase.pdfmetrics import getFont, registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont, TTFontFile
from reportlab.pdfgen import canvas

from .charts import (
    Chart,
    birth_source,
    box_generation,
    death_source,
    living_checker,
    nobody_living,
    page_depth,
    plan_charts,
)
from .lang import (
    DEFAULT_STRINGS,
    PLACEHOLDERS,
    KincadeWarning,
    SortRules,
    day_number,
    display_name,
    fill,
    format_date,
    index_name,
    is_placeholder_surname,
    load_strings,
    map_leaves,
    year_of,
)
from .model import Event, Family, Person, Tree, strip_controls

# --------------------------------------------------------------------------
# Text: cleaning, kerning and fitting
# --------------------------------------------------------------------------


def _cp1252_ok(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def clean(text: str, supports: Callable[[str], bool] = _cp1252_ok) -> str:
    """Make text drawable: remove non-whitespace controls and use standard spaces.
    Keep characters the font set has, else NFKD-strip accents, else '?'.

    `supports` says whether a character has a glyph (default: the cp1252 base fonts).
    """
    out = []
    for ch in strip_controls(text):
        if ch.isspace():
            out.append(" ")
        elif supports(ch):
            out.append(ch)
        else:
            out.extend(
                d if supports(d) else "?"
                for d in unicodedata.normalize("NFKD", ch)
                if not unicodedata.combining(d)
            )
    return "".join(out)


MIN_SCALE = 0.5  # the least horizontal squeeze for a line


# embedded font name -> kern(left, right) in em
_KERNING: dict[str, Callable[[str, str], float]] = {}


def _kerned(
    text: str, font: str, size: float
) -> tuple[float, Callable[[str, str], float] | None]:
    """(advance width, kern function) for one line. Kerning is used only if it keeps the
    line above zero and at least half its unkerned width; otherwise the line is measured
    and drawn unkerned (kern is None).
    """
    plain = stringWidth(text, font, size)
    kern = _KERNING.get(font)
    if kern:
        kerned = plain + size * sum(map(kern, text, text[1:]))
        if kerned > 0 and kerned >= plain / 2:
            return kerned, kern
    return plain, None


def text_width(text: str, font: str, size: float) -> float:
    """Advance width of a line, including the font's kerning pairs."""
    return _kerned(text, font, size)[0]


def char_advances(text: str, font: str, size: float) -> list[float]:
    """Each glyph's advance with its kern to the next, using text_width's decision."""
    _, kern = _kerned(text, font, size)
    return [
        stringWidth(ch, font, size)
        + (kern(ch, text[i + 1]) * size if kern and i + 1 < len(text) else 0)
        for i, ch in enumerate(text)
    ]


def draw_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    font: str,
    size: float,
    scale: float = 1.0,
    right: bool = False,
) -> None:
    """Draw one line at baseline y with kerning and an optional horizontal squeeze (x =
    right edge if `right`).

    The squeeze is clamped to 50-100%: a scale outside that range never reaches the PDF
    (a negative one would mirror the text). Kerned lines are drawn in runs. If the runs
    do not add up to the measured width (or one would start outside it) the line is
    drawn unkerned in one piece instead.
    """
    scale = min(1.0, max(MIN_SCALE, scale))
    width, kern = _kerned(text, font, size)
    measured = width * scale
    if right:
        x -= measured
    runs, cx, start = [], x, 0
    for i in range(1, len(text) + 1):  # runs end at each kerned pair
        k = kern(text[i - 1], text[i]) * size if kern and i < len(text) else 0
        if k or i == len(text):
            runs.append((cx, text[start:i]))
            cx += (stringWidth(text[start:i], font, size) + k) * scale
            start = i
    if abs(cx - (x + measured)) > 0.5 or any(
        not x - 0.5 <= rx <= x + measured + 0.5 for rx, _ in runs
    ):
        runs = [(x, text)]
    t = c.beginText()
    t.setFont(font, size)
    t.setHorizScale(scale * 100)
    for rx, piece in runs:
        t.setTextOrigin(rx, y)
        t.textOut(piece)
    # the squeeze is graphics state: do not leak it into later text
    t.setHorizScale(100)
    c.drawText(t)


def fit(text: str, font: str, size: float, width: float, ellipsis: str = "…") -> str:
    """`text`, or as much of it as fits with the ellipsis (the language's, by default
    '…') at its end: the result is never wider than `width` points. If not even the
    ellipsis fits, the result is "".
    """
    if text_width(text, font, size) <= width:
        return text
    while text:
        candidate = text.rstrip() + ellipsis
        if text_width(candidate, font, size) <= width:
            return candidate
        text = text[:-1]
    return ellipsis if text_width(ellipsis, font, size) <= width else ""


# an overlong line is condensed by up to 7% (kerned width) before it is truncated
SQUEEZE = 0.93


def _squeeze_scale(room: float, width: float) -> float:
    """The horizontal scale that fits a line `width` wide into `room`: 1 if it fits,
    never below 50%.
    """
    return min(1.0, max(MIN_SCALE, room / (width or 1)))


def fit_squeezed(
    text: str, font: str, size: float, width: float, ellipsis: str = "…"
) -> tuple[str, float]:
    """(text, horizontal scale): condense up to 7%, then truncate with the ellipsis. The
    scale stays in 50-100%.
    """
    text = fit(text, font, size, width / SQUEEZE, ellipsis)
    return text, _squeeze_scale(width, text_width(text, font, size))


def fit_squeezed_noted(
    name: str, note: str, font: str, size: float, width: float, ellipsis: str = "…"
) -> tuple[str, float]:
    """fit_squeezed for a name followed by a note ("Anna SMITH (adopted)"). A line that
    has to be cut is cut in the name, so the note stays; only when not even the ellipsis
    fits beside the note is the whole line cut.
    """
    whole = f"{name} {note}" if note else name
    limit = width / SQUEEZE
    if note and text_width(whole, font, size) > limit:
        room = limit - text_width(f" {note}", font, size)
        if room >= text_width(ellipsis, font, size):
            text = f"{fit(name, font, size, room, ellipsis)} {note}"
            return text, _squeeze_scale(width, text_width(text, font, size))
    return fit_squeezed(whole, font, size, width, ellipsis=ellipsis)


# --------------------------------------------------------------------------
# Fonts: embedded TrueType (Helvetica and Times New Roman) or the PDF base-14 fonts
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FontSet:
    """The four faces a page uses: name/header sans, box numbers, detail serif,
    continuation italic.
    """

    sans: str = "Helvetica"
    bold: str = "Helvetica-Bold"
    serif: str = "Times-Roman"
    italic: str = "Times-Italic"
    # does every face have a glyph for this character?
    supports: Callable[[str], bool] = _cp1252_ok
    files: tuple[str, ...] = ()  # TrueType files embedded (empty for the base-14 fonts)

    def clean(self, text: str) -> str:
        return clean(text, self.supports)


BASE14 = FontSet()

# role -> candidates, best first: (file name, PostScript name inside a .ttc or None).
# Matched case-insensitively anywhere under the font directories. Helvetica and Times
# New Roman come first; Arial and Liberation have the same metrics.
FONT_FILES: dict[str, list[tuple[str, str | None]]] = {
    "sans": [
        ("Helvetica.ttc", "Helvetica"),
        ("Arial.ttf", None),
        ("LiberationSans-Regular.ttf", None),
    ],
    "bold": [
        ("Helvetica.ttc", "Helvetica-Bold"),
        ("Arial Bold.ttf", None),
        ("arialbd.ttf", None),
        ("LiberationSans-Bold.ttf", None),
    ],
    "serif": [
        ("Times New Roman.ttf", None),
        ("times.ttf", None),
        ("LiberationSerif-Regular.ttf", None),
    ],
    "italic": [
        ("Times New Roman Italic.ttf", None),
        ("timesi.ttf", None),
        ("LiberationSerif-Italic.ttf", None),
    ],
}


def font_dirs() -> list[Path]:
    """Existing system and user font directories (macOS, Linux, Windows). A folder the
    file system cannot look at (an odd path: too long, a NUL character, no permission)
    is left out, never an error, and so are the user's folders where no home folder can
    be found.
    """
    try:
        home: Path | None = Path.home()
    except RuntimeError:  # no home folder can be found: the system folders alone
        home = None
    # Only on Windows: elsewhere C:\Windows is a relative path,
    # under the working folder.
    windows = (
        [Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "Fonts"]
        if os.name == "nt"
        else []
    )

    def in_home(folder: str) -> list[Path]:
        return [home / folder] if home is not None else []

    dirs = [
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
        *in_home("Library/Fonts"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        *in_home(".fonts"),
        *in_home(".local/share/fonts"),
        *windows,
        *in_home("AppData/Local/Microsoft/Windows/Fonts"),
    ]
    found = []
    for d in dirs:
        try:
            if d.is_dir():
                found.append(d)
        except (OSError, ValueError):
            continue
    return found


def find_font_files(dirs: list[Path] | None = None) -> dict[str, list[Path]]:
    """Lower-cased file name -> paths (directory order) for every font file we might
    use.
    """
    wanted = {name.lower() for cands in FONT_FILES.values() for name, _ in cands}
    found: dict[str, list[Path]] = {}
    for d in font_dirs() if dirs is None else dirs:
        for root, _, files in os.walk(d):
            for name in sorted(files):
                if name.lower() in wanted:
                    found.setdefault(name.lower(), []).append(Path(root) / name)
    return found


def _kern_pairs(
    table: bytes, units: int, advance: Callable[[int], int] | None = None
) -> dict[tuple[int, int], int]:
    """Horizontal kerning {(left glyph, right glyph): font units} summed over a 'kern'
    table's subtables.

    Only plain horizontal format-0 subtables count (not minimum, cross-stream or
    variation; an MS override bit replaces instead of adding), and pairs beyond half an
    em are discarded. With `advance` (glyph -> advance in font units), a pair that would
    make its left glyph's advance negative is discarded too. Anything structurally wrong
    (versions, lengths, a pair array that does not fit its subtable and the table) gives
    {}: never a partial result, never an exception.
    """
    try:
        pairs = _read_kern(table, units)
        if advance is not None:
            pairs = {
                (left, right): value
                for (left, right), value in pairs.items()
                if value >= -advance(left)
            }
        return pairs
    except (struct.error, ValueError, IndexError, OverflowError):
        return {}


def _read_kern(table: bytes, units: int) -> dict[tuple[int, int], int]:
    # Apple: u32 version 1.0, u32 count; 8-byte subtable headers
    if table[:4] == b"\x00\x01\x00\x00":
        count, pos, head = struct.unpack(">I", table[4:8])[0], 8, 8
    # MS: u16 version 0, u16 count; 6-byte headers
    elif table[:2] == b"\x00\x00" and len(table) >= 4:
        count, pos, head = struct.unpack(">H", table[2:4])[0], 4, 6
    else:
        raise ValueError("unknown kern table version")
    apple = head == 8
    # every subtable needs its header and a pair-count header
    if count * (head + 8) > len(table) - pos:
        raise ValueError("subtable count does not fit the table")
    pairs: dict[tuple[int, int], int] = {}
    for _ in range(count):
        if apple:
            length, cov = struct.unpack(">IH", table[pos : pos + 6])
            # format 0; not vertical, cross-stream or variation
            plain, override = cov & 0xE0FF == 0, False
        else:
            _, length, cov = struct.unpack(">HHH", table[pos : pos + 6])
            # format 0, horizontal, not minimum/cross
            plain, override = cov & 0xFF07 == 0x0001, bool(cov & 8)
        end = pos + length
        if length < head + 8 or end > len(table):
            raise ValueError("bad subtable length")
        if plain:
            n = struct.unpack(">H", table[pos + head : pos + head + 2])[0]
            start = pos + head + 8
            if start + 6 * n > end:
                raise ValueError("pair array exceeds its subtable")
            for left, right, value in struct.iter_unpack(
                ">HHh", table[start : start + 6 * n]
            ):
                pairs[left, right] = (
                    value if override else pairs.get((left, right), 0) + value
                )
        pos = end
    return {pair: value for pair, value in pairs.items() if abs(value) <= units / 2}


@dataclass(frozen=True)
class _Face:
    """A registered TrueType face: its unique PDF font name and its glyph
    coverage test.
    """

    name: str
    covers: Callable[[str], bool]


# PDF font name (file + subfont) -> the one face object behind it
_FACES: dict[str, _Face] = {}


def _face_name(path: Path, index: int) -> str:
    """Unique, stable PDF font name for one subfont of one file."""
    return "CP-" + hashlib.sha1(f"{path.resolve()}|{index}".encode()).hexdigest()[:12]


@functools.cache
def _subfont_index(path: str, psname: str, mtime_ns: int) -> int:
    """Index of the face with this PostScript name inside a .ttc (mtime keeps the cache
    honest).
    """
    for index in range(64):
        if TTFontFile(path, subfontIndex=index).name.decode("latin-1") == psname:
            return index
    raise ValueError(f"{psname} not found in {path}")


class NotEmbeddable(Exception):
    """A TrueType face whose license flags do not allow embedding a subset of it (see
    subset_embeddable).
    """


def subset_embeddable(fs_type: int) -> bool:
    """Whether a face with this OS/2 fsType may be embedded as a subset.

    Refused: a restricted license (0x0002) unless preview-and-print (0x0004) or editable
    (0x0008) is also set, no subsetting (0x0100, and we always subset), and bitmap
    embedding only (0x0200).
    """
    restricted = bool(fs_type & 0x0002) and not fs_type & 0x000C
    return not (restricted or fs_type & 0x0100 or fs_type & 0x0200)


def _os2_fs_type(path: Path, index: int = 0) -> int:
    """The OS/2 fsType of the face at `index` in a .ttf or .ttc file; 0 when the face
    has no OS/2 table.

    Read from the raw table directory: reportlab refuses some restricted faces while
    parsing them, so their value is never available from it.
    """
    with path.open("rb") as f:
        base = 0
        # a collection: each face has its own offset table, listed in the header
        if f.read(4) == b"ttcf":
            f.seek(12 + 4 * index)
            (base,) = struct.unpack(">I", f.read(4))
        f.seek(base + 4)
        (count,) = struct.unpack(">H", f.read(2))
        f.seek(base + 12)
        for _ in range(count):
            tag, _, offset, _ = struct.unpack(">4sIII", f.read(16))
            if tag == b"OS/2":
                f.seek(offset + 8)  # fsType is the uint16 at offset 8 of the OS/2 table
                (fs_type,) = struct.unpack(">H", f.read(2))
                return fs_type
    return 0


def _load_ttf(path: Path, psname: str | None) -> _Face:
    """Register one TrueType face with reportlab, once per file and subfont. Raises on
    failure.

    A face whose license does not allow subset embedding raises NotEmbeddable before
    reportlab parses it. Registration, glyph coverage and kerning are created together
    under the same unique name, so repeated resolution in one process always sees a
    consistent face.
    """
    index = _subfont_index(str(path), psname, path.stat().st_mtime_ns) if psname else 0
    name = _face_name(path, index)
    if name not in _FACES:
        if not subset_embeddable(_os2_fs_type(path, index)):
            raise NotEmbeddable(path.name)
        font = TTFont(name, str(path), subfontIndex=index)
        registerFont(font)
        cmap, units, hmetrics = (
            font.face.charToGlyph,
            font.face.unitsPerEm,
            font.face.hmetrics,
        )

        # (advance, lsb) per glyph; glyphs past the table share the last advance
        def advance(glyph: int) -> int:
            return hmetrics[min(glyph, len(hmetrics) - 1)][0]

        try:
            pairs = _kern_pairs(font.face.get_table("kern"), units, advance)
        except KeyError:  # no kern table: lay out without kerning
            pairs = {}
        if pairs:
            _KERNING[name] = lambda a, b: (
                pairs.get((cmap.get(ord(a), -1), cmap.get(ord(b), -1)), 0) / units
            )
        _FACES[name] = _Face(name, lambda ch: ord(ch) in cmap)
    return _FACES[name]


def _first_face(
    candidates: list[tuple[str, str | None]], found: dict[str, list[Path]]
) -> tuple[Path, _Face] | None:
    """The first candidate file (and subfont) that registers. A face that may not be
    embedded ends the search.
    """
    for fname, psname in candidates:
        for path in found.get(fname.lower(), []):
            try:
                return path, _load_ttf(path, psname)
            except NotEmbeddable:
                raise
            except Exception:  # noqa: BLE001, S112
                # unreadable, or no such face: try the next
                continue
    return None


def _resolve(
    dirs: list[Path] | None = None,
) -> tuple[FontSet | None, list[str], list[str]]:
    """Resolve and register all four roles: (fonts or None, roles that cannot be used,
    font files refused).
    """
    found = find_font_files(dirs)
    faces: list[_Face] = []
    files: list[str] = []
    missing: list[str] = []
    refused: list[str] = []
    for role, candidates in FONT_FILES.items():
        try:
            hit = _first_face(candidates, found)
        except NotEmbeddable as e:
            refused.append(str(e))
            hit = None
        if hit is None:
            missing.append(role)
        else:
            files.append(str(hit[0]))
            faces.append(hit[1])
    if missing:
        return None, missing, refused
    # the role order of FONT_FILES
    sans, bold, serif, italic = (face.name for face in faces)
    return (
        FontSet(
            sans=sans,
            bold=bold,
            serif=serif,
            italic=italic,
            supports=lambda ch: all(face.covers(ch) for face in faces),
            files=tuple(files),
        ),
        [],
        [],
    )


def load_fontset(dirs: list[Path] | None = None) -> tuple[FontSet | None, list[str]]:
    """Find the four faces in the font folders and register them with reportlab, each
    face once per process, printing nothing: (the FontSet, []) when every role loads,
    else (None, the roles it could not fill). A role whose face may not be embedded is
    one it could not fill. `dirs` replaces the system and user font folders. Pass the
    FontSet as Options(fonts=...).
    """
    fonts, missing, _ = _resolve(dirs)
    return fonts, missing


def choose_fonts(mode: str | FontSet = "auto") -> FontSet:
    """'auto': embed TrueType fonts if all four roles resolve, else the base-14 fonts
    (never mixed).
    """
    if isinstance(mode, FontSet):
        return mode
    if mode == "base14":
        return BASE14
    if mode != "auto":
        raise ValueError(f"unknown font mode {mode!r}")
    fonts, missing, refused = _resolve()
    if fonts is None:
        if refused:
            reason = f"{', '.join(dict.fromkeys(refused))} may not be embedded as a subset (OS/2 fsType)"
        else:
            reason = f"no TrueType font found for {', '.join(missing)}"
        warnings.warn(
            f"{reason}; using the built-in PDF fonts", KincadeWarning, stacklevel=2
        )
        return BASE14
    return fonts


# --------------------------------------------------------------------------
# Page layout (pt, origin top-left): chart columns, headers, footers and box padding.
# PageGeom derives paper and print-size values. A4 adds vertical room; its narrower
# width affects large-print columns and charts with shadows.
# --------------------------------------------------------------------------

# portrait (width, height) in points
PAPER_SIZES = {"letter": (612, 792), "a4": (595.28, 841.89)}
# header rule and index
LEFT_MARGIN, RIGHT_MARGIN = 18, 19
BOTTOM_INSET = 55.5  # the layout's bottom edge is this far above the page foot
FOOTER_INSET = 42  # footer baseline, measured up from the page foot
FOOTER_SIZE = 8  # the footer and the page number, on that baseline
# the least space between the page number and the footer, in points
PAGE_NUMBER_GAP = 12
# The page number ends this far short of the center line; it may use half the room.
PAGE_NUMBER_EDGE = 6

LABEL_RIGHT_INSET = 18.5  # chart label, measured from the page's right edge
FOOTER_RIGHT_INSET = 19.5  # footer text, measured from the page's right edge
TITLE_BASELINE, TITLE_SIZE = 32, 16
LABEL_BASELINE, LABEL_SIZE = 35, 9
RULE_Y, RULE_WIDTH = 38, 1.0
SUBTITLE_BASELINE, SUBTITLE_SIZE = 46, 8
CHART_LINE_WIDTH = 0.25  # box outlines and connectors
# the right column (boxes 8-15, or 4-7 in large print) spans from here down to the
# layout's bottom edge
Y_TOP = 42.0
# The left generations step right by COLUMN_STEP; the right column starts
# ZONE_CLEARANCE beyond them and ends at RIGHT_EDGE in normal print.
LEFT_X, COLUMN_STEP, ZONE_CLEARANCE, RIGHT_EDGE = 30, 43, 27, 573
RIGHT_EDGE_INSET = 39  # large print: right column inset from the page's right edge
# baselines: name at top+11, then +12, then +10 each; 5 pt below the last
NAME_BASE, DETAIL_GAP, LEADING, BOTTOM_PAD = 11, 12, 10, 5
# box text starts 5 pt inside the left edge, ends 3 pt short of the right
TEXT_INSET_LEFT, TEXT_INSET_RIGHT = 5, 3
TITLE_GAP = 10  # minimum space between the page title and the 'Chart N' label
SIZE = 9  # all box text
# box text in large print; the leading, paddings, insets and record ID scale with it
LARGE_SIZE = 14
LARGE_SCALE = LARGE_SIZE / SIZE
# left zone: trunk sits this far right of the descendant box's left edge
LEFT_TRUNK_DX = 18
# right column: trunk sits this far right of the parent box's right edge
RIGHT_TRUNK_DX = 13
INDEX_SIZE, INDEX_LEADING = 8, 10
# three columns between the rule's ends
INDEX_COLS, INDEX_GUTTER, INDEX_LEFT = 3, 10, LEFT_MARGIN
INDEX_TOP, INDEX_HANGING = 58, 10  # first baseline, wrapped-line indent
# a continuation chart number keeps this far from the page's right edge
CONTINUATION_EDGE = 6
# a box number ends this far left of its box (large print: scaled by 14/9)
BOX_NUMBER_GAP = 4
CONTINUATION_DROP = 3  # baseline below the box's center, scaled with print size
# a continuation chart number starts this far right of its box,
# or of the box's shadow (scaled)
CONTINUATION_GAP = 5
# chart subtitles (continuation line, chart note) end this far left of the right column
SUBTITLE_CLEARANCE = 12
# a record ID (--show-ids): small type, and the name keeps this far from it
RECORD_ID_SIZE, RECORD_ID_GAP = 7, 6
# A record ID is cut with the ellipsis beyond this share of a box's text width (about 83
# pt of 207 in normal print: an ID of some 20 digits). A long record ID (GEDCOM 7 allows
# any length) stays in its box, and the name has the remaining width.
RECORD_ID_SHARE = 0.4
# The drop shadow (--shadow): SHADOW_LAYERS translucent rects, each SHADOW_GROW pt
# larger than the one inside it, all offset SHADOW_OFFSET right and down. Large print
# scales both by its 14/9. No layer is clipped: with shadows on, page_geom gives the
# chart area room for them (shadow_reach), so the bottom edge and, where needed, the
# right column's edge move in by the shadow's reach.
SHADOW_OFFSET, SHADOW_GROW, SHADOW_LAYERS = 2.5, 0.8, 3
# fill alpha of each layer: the core, under all three, is about a third opaque
SHADOW_ALPHA = 0.12


def shadow_reach(large_print: bool = False) -> float:
    """How far a box's shadow extends past the box's right and bottom edges: the offset
    plus the growth of the outermost layer, scaled for large print.
    """
    return (SHADOW_OFFSET + (SHADOW_LAYERS - 1) * SHADOW_GROW) * (
        LARGE_SCALE if large_print else 1.0
    )


def has_marriage_lines(pos: int) -> bool:
    return pos == 1 or pos % 2 == 0  # the root and fathers show m./mp.; mothers do not


def box_height(pos: int, scale: float = 1.0) -> float:
    """Root and fathers: name + 6 detail lines (78 pt); mothers: name + 4 (58 pt). Large
    print scales it.
    """
    lines = 7 if has_marriage_lines(pos) else 5
    return (NAME_BASE + DETAIL_GAP + (lines - 2) * LEADING + BOTTOM_PAD) * scale


def column_layout(depth: int, right_edge: float) -> tuple[float, dict[int, float]]:
    """(box width, left edge of every box) for a chart `depth` generations deep: the
    left zone holds generations 1 to depth - 1 in columns COLUMN_STEP apart; the right
    column (generation `depth`) starts ZONE_CLEARANCE right of the left zone's last
    column; and all boxes are as wide as `right_edge` allows.
    """
    # left edge of the left zone's last column
    last = LEFT_X + COLUMN_STEP * (depth - 2)
    # last + width + ZONE_CLEARANCE + width = right_edge
    width = (right_edge - ZONE_CLEARANCE - last) / 2
    return width, {
        pos: last + width + ZONE_CLEARANCE
        if box_generation(pos) == depth
        else LEFT_X + COLUMN_STEP * (box_generation(pos) - 1)
        for pos in range(1, 2**depth)
    }


BOX_W, BOX_X0 = column_layout(page_depth(), RIGHT_EDGE)
# Letter normal print: the width box text is fitted into (207 pt)
TEXT_WIDTH = BOX_W - TEXT_INSET_LEFT - TEXT_INSET_RIGHT


def _box_tops(y_bottom: float, large_print: bool = False) -> dict[int, float]:
    """The right column (the last generation's boxes) stacked from Y_TOP to y_bottom
    with one uniform gap that fills the space exactly, in both print sizes. Other
    boxes sit midway between their parents' facing edges. The root sits between its
    nearest left-zone neighbors, which are boxes 5 and 6 in normal print.
    """
    scale = LARGE_SCALE if large_print else 1.0
    first = 2 ** (page_depth(large_print) - 1)
    right = range(first, 2 * first)
    heights = {pos: box_height(pos, scale) for pos in range(1, 2 * first)}
    gap = (y_bottom - Y_TOP - sum(heights[pos] for pos in right)) / (len(right) - 1)
    y = Y_TOP
    tops = {}
    for pos in right:
        tops[pos] = y
        y += heights[pos] + gap
    for pos in range(first - 1, 0, -1):
        above, below = (
            (5, 6) if pos == 1 and not large_print else (2 * pos, 2 * pos + 1)
        )
        tops[pos] = (tops[above] + heights[above] + tops[below] - heights[pos]) / 2
    return tops


def _scaled(value: float) -> property:
    """A PageGeom property: `value` times the print size's scale (1 in normal print,
    14/9 in large print).
    """
    return property(lambda geom: value * geom.scale)


@dataclass(frozen=True)
class PageGeom:
    """The layout for one paper size, in normal or large print. Build it with
    `page_geom`, which caches them.
    """

    paper: str
    width: float
    height: float
    y_bottom: float  # bottom edge of the right column, the left zone and the index body
    box_top: Mapping[int, float] = field(compare=False)
    large_print: bool = False  # True: 14 pt text, three generations per page
    box_w: float = BOX_W
    box_x0: Mapping[int, float] = field(
        default_factory=lambda: MappingProxyType(dict(BOX_X0)), compare=False
    )

    @property
    def gens(self) -> int:
        """Generations on a page: 4 (boxes 1-15), or 3 (boxes 1-7) in large print."""
        return page_depth(self.large_print)

    @property
    def first_right(self) -> int:
        """The first position of the right column: 8, or 4 in large print."""
        return 2 ** (self.gens - 1)

    @property
    def size(self) -> float:
        """The box text size."""
        return LARGE_SIZE if self.large_print else SIZE

    @property
    def scale(self) -> float:
        return LARGE_SCALE if self.large_print else 1.0

    # the layout constants, grown with the print size
    name_base = _scaled(NAME_BASE)
    detail_gap = _scaled(DETAIL_GAP)
    leading = _scaled(LEADING)
    bottom_pad = _scaled(BOTTOM_PAD)
    inset_left = _scaled(TEXT_INSET_LEFT)
    inset_right = _scaled(TEXT_INSET_RIGHT)
    id_size = _scaled(RECORD_ID_SIZE)
    id_gap = _scaled(RECORD_ID_GAP)
    box_number_gap = _scaled(BOX_NUMBER_GAP)
    continuation_gap = _scaled(CONTINUATION_GAP)
    continuation_drop = _scaled(CONTINUATION_DROP)

    @property
    def text_w(self) -> float:
        """The width box text is fitted into."""
        return self.box_w - self.inset_left - self.inset_right

    @property
    def id_max(self) -> float:
        """The widest a record ID is drawn: RECORD_ID_SHARE of the box's text width."""
        return RECORD_ID_SHARE * self.text_w

    root_spouse: bool = False  # one extra row on the initial root only

    def h(self, pos: int) -> float:
        """The height of a box, including the initial root's spouse row."""
        extra = self.leading if pos == 1 and self.root_spouse else 0.0
        return box_height(pos, self.scale) + extra

    @property
    def right(self) -> float:
        """Right edge of the header rule and the index: RIGHT_MARGIN in from the page
        edge.
        """
        return self.width - RIGHT_MARGIN

    @property
    def label_right(self) -> float:
        return self.width - LABEL_RIGHT_INSET

    @property
    def footer_right(self) -> float:
        return self.width - FOOTER_RIGHT_INSET

    @property
    def index_col_w(self) -> float:
        return (self.right - INDEX_LEFT - INDEX_GUTTER * (INDEX_COLS - 1)) / INDEX_COLS

    def y(self, top: float) -> float:
        """A layout y (origin top-left) as the PDF's y (origin bottom-left)."""
        return self.height - top


@functools.cache
def page_geom(
    paper: str = "letter", large_print: bool = False, shadow: bool = False
) -> PageGeom:
    """The layout for a paper. With `shadow`, the chart area makes room for the drop
    shadows: its bottom edge rises by shadow_reach, so the lowest shadow fits above
    BOTTOM_INSET. The right column's edge moves in only if a shadow would otherwise pass
    the right margin (A4 normal print). All columns share the resulting width. Without
    `shadow`, no room is reserved for shadows.
    """
    if paper not in PAPER_SIZES:
        raise ValueError(
            f"paper must be one of {', '.join(PAPER_SIZES)}, not {paper!r}"
        )
    width, height = PAPER_SIZES[paper]
    reach = shadow_reach(large_print) if shadow else 0.0
    y_bottom = height - BOTTOM_INSET - reach
    # the right column's right edge
    right = width - RIGHT_EDGE_INSET if large_print else RIGHT_EDGE
    if shadow:
        right = min(right, width - RIGHT_MARGIN - reach)
    box_w, box_x0 = column_layout(page_depth(large_print), right)
    return PageGeom(
        paper,
        width,
        height,
        y_bottom,
        MappingProxyType(_box_tops(y_bottom, large_print)),
        large_print,
        box_w,
        MappingProxyType(box_x0),
    )


LETTER = page_geom("letter")


def stub_y(pos: int, geom: PageGeom) -> float:
    # connectors meet every box at its vertical center
    return geom.box_top[pos] + geom.h(pos) / 2


# --------------------------------------------------------------------------
# Chart pages
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Doc:
    """What drawing a page needs of the document: the tree, the options, the fonts, the
    drawable strings (see _language), the living check, the layout, the drawable footer
    text and the home country for the place shortening (None: no country is dropped).
    """

    tree: Tree
    opts: Options
    fonts: FontSet
    drawable_strings: Mapping[str, Any]
    is_living: Callable[[str | None], bool]
    geom: PageGeom
    footer: str | None = None
    home: str | None = None

    @functools.cached_property
    def rules(self) -> SortRules:
        """The language's sort rules, which also name the surname particles that keep
        their case."""
        return SortRules(self.drawable_strings["sort"])


def _frame(
    c: canvas.Canvas,
    doc: _Doc,
    title: str,
    label: str,
    subtitle: str,
    page_number: str | None = None,
    subtitle_right: float | None = None,
) -> None:
    """Draw text that is already safe for the font set: title, chart label, rule,
    subtitle, footer (none when doc.footer is None) and page number (none when
    page_number is None). Each is fitted (with the ellipsis) into its space. The
    subtitle may run as far right as subtitle_right (default: the rule's end). The page
    number sits bottom left on the footer's baseline, in at most half the room from the
    left margin to PAGE_NUMBER_EDGE short of the center. The footer is fitted to the
    room right of it, at least PAGE_NUMBER_GAP away, and is not drawn when there is
    none.
    """
    fonts, geom, ellipsis = doc.fonts, doc.geom, doc.drawable_strings["ellipsis"]
    left, rule_end, label_right, footer_right = (
        LEFT_MARGIN,
        geom.right,
        geom.label_right,
        geom.footer_right,
    )
    c.setFillColorRGB(0, 0, 0)
    title_room = rule_end - left
    if label:
        title_room = (
            label_right - text_width(label, fonts.sans, LABEL_SIZE) - TITLE_GAP - left
        )
        draw_text(
            c,
            label_right,
            geom.y(LABEL_BASELINE),
            label,
            fonts.sans,
            LABEL_SIZE,
            right=True,
        )
    draw_text(
        c,
        left,
        geom.y(TITLE_BASELINE),
        fit(title, fonts.bold, TITLE_SIZE, title_room, ellipsis),
        fonts.bold,
        TITLE_SIZE,
    )
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(RULE_WIDTH)
    c.line(left, geom.y(RULE_Y), rule_end, geom.y(RULE_Y))
    if subtitle:
        end = rule_end if subtitle_right is None else subtitle_right
        draw_text(
            c,
            left,
            geom.y(SUBTITLE_BASELINE),
            fit(subtitle, fonts.sans, SUBTITLE_SIZE, end - left, ellipsis),
            fonts.sans,
            SUBTITLE_SIZE,
        )
    footer_y = geom.y(geom.height - FOOTER_INSET)
    footer_left: float = left  # the footer may run as far left as this
    if page_number is not None:
        number_room = ((geom.width / 2 - PAGE_NUMBER_EDGE) - left) / 2
        number = fit(page_number, fonts.sans, FOOTER_SIZE, number_room, ellipsis)
        if number:
            draw_text(c, left, footer_y, number, fonts.sans, FOOTER_SIZE)
            footer_left = (
                left + text_width(number, fonts.sans, FOOTER_SIZE) + PAGE_NUMBER_GAP
            )
    if doc.footer is not None and footer_right > footer_left:
        text = fit(
            doc.footer,
            fonts.sans,
            FOOTER_SIZE,
            footer_right - footer_left,
            ellipsis,
        )
        if text:
            draw_text(
                c, footer_right, footer_y, text, fonts.sans, FOOTER_SIZE, right=True
            )


def _shown(chart: Chart, pos: int, empty_boxes: bool) -> bool:
    """Whether a box is drawn: within the chart's generations and, with empty_boxes
    off, known."""
    return pos in chart.drawn and (empty_boxes or chart.slots[pos] is not None)


def _shown_boxes(chart: Chart, empty_boxes: bool) -> list[int]:
    """The positions of the boxes drawn on a chart, in order."""
    return [pos for pos in range(1, 2**chart.depth) if _shown(chart, pos, empty_boxes)]


def _connectors(c: canvas.Canvas, shown: Callable[[int], bool], geom: PageGeom) -> None:
    """Connect each drawn child box to its drawn parent boxes."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(CHART_LINE_WIDTH)
    for d in range(1, geom.first_right):
        kids = [k for k in (2 * d, 2 * d + 1) if shown(k)]
        if not shown(d) or not kids:
            continue
        right = d >= geom.first_right // 2  # its children are in the right column
        tx = (
            geom.box_x0[d] + geom.box_w + RIGHT_TRUNK_DX
            if right
            else geom.box_x0[d] + LEFT_TRUNK_DX
        )
        # the trunk reaches the descendant (hidden behind it on the left)
        ys = [stub_y(k, geom) for k in kids] + [stub_y(d, geom)]
        c.line(tx, geom.y(min(ys)), tx, geom.y(max(ys)))
        if right:
            c.line(
                geom.box_x0[d] + geom.box_w,
                geom.y(stub_y(d, geom)),
                tx,
                geom.y(stub_y(d, geom)),
            )
        for k in kids:
            c.line(tx, geom.y(stub_y(k, geom)), geom.box_x0[k], geom.y(stub_y(k, geom)))


def shadow_layers(
    x0: float, top: float, h: float, geom: PageGeom
) -> list[tuple[float, float, float, float]]:
    """(x, top, width, height) of each layer of a box's drop shadow, innermost first, in
    layout points. Each layer is offset SHADOW_OFFSET right and down and grows
    SHADOW_GROW on every side per layer further out (large print scales both). Every
    layer is drawn whole: page_geom(shadow=True) leaves room for the outermost one.
    """
    s = geom.scale
    layers = []
    for i in range(SHADOW_LAYERS):
        grow = i * SHADOW_GROW * s
        layers.append(
            (
                x0 + SHADOW_OFFSET * s - grow,
                top + SHADOW_OFFSET * s - grow,
                geom.box_w + 2 * grow,
                h + 2 * grow,
            )
        )
    return layers


def _shadow(c: canvas.Canvas, x0: float, top: float, h: float, geom: PageGeom) -> None:
    c.setFillColorRGB(0, 0, 0)
    c.setFillAlpha(SHADOW_ALPHA)  # stacked translucent layers fake a soft edge
    for x, y, w, height in shadow_layers(x0, top, h, geom):
        c.rect(x, geom.y(y + height), w, height, stroke=0, fill=1)
    c.setFillAlpha(1)


def _labeled(label: str, value: str) -> str:
    """A box line's text: "label value", or the one of them that is not empty, so an
    empty label (a language may set one) leaves no leading space."""
    return " ".join(text for text in (label, value) if text)


class BoxLine(NamedTuple):
    """One line of a chart box. label is the name on the name line, else the line's
    label; value is the drawable value, "" when it is empty or hidden for privacy;
    is_place marks a place line, which the place shortening may shorten; note is the
    relationship note after the name (see --adoptive-parents), on the name line only.
    """

    label: str
    value: str
    is_place: bool
    note: str = ""

    @property
    def text(self) -> str:
        return _labeled(self.label, self.value)


def _root_family(tree: Tree, person: Person, selector: object) -> Family | None:
    """The initial root's marriage family: exact first FAMS by default, or a
    selected family that actually names the root as a partner. Accept GEDCOM @IDs@
    and the same case-insensitive ID spelling as root selection.
    """
    if selector is None:
        return tree.families.get(person.families[0]) if person.families else None
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("root_family must be a family record ID")
    key = selector.strip()
    candidates = (key, key.strip("@"))
    family = next((tree.families[c] for c in candidates if c in tree.families), None)
    if family is None:
        folded = {unicodedata.normalize("NFC", c.casefold()) for c in candidates}
        family = next(
            (
                f
                for ident, f in tree.families.items()
                if unicodedata.normalize("NFC", ident.casefold()) in folded
            ),
            None,
        )
    if family is None:
        raise ValueError(f"root_family {selector!r}: no such family record")
    if person.id not in (family.father, family.mother):
        raise ValueError(
            f"root_family {selector!r}: root {person.id!r} is not a partner in that family"
        )
    return family


def _box_lines(doc: _Doc, chart: Chart, pos: int) -> list[BoxLine]:
    """Name line plus labeled detail lines for one box (text already safe for the font
    set). Places have trimmed comma-separated parts, with empty parts omitted. The birth
    and death lines come from birth_source and death_source: a christening, burial or
    cremation stands in when allowed. The name line carries a note from
    Tree.parent_relationship for the family chosen by opts.parents ("birth" or
    "adoptive"); a person who may be living has none under opts.exclude_private. A
    father's marriage lines show the marriage of the family drawn for his child, unless
    one of its parents is the child's step-parent: that is not the marriage of the
    parents drawn (Tree.parents_union). Box 1 of a continuation chart shows the same,
    for the child just below it on the chart it continues, so that it shows what its box
    there showed; box 1 of chart 1 pairs its spouse with its first marriage (FAMS),
    or with the family selected by root_family."""
    tree, opts, fonts, drawable_strings, is_living = (
        doc.tree,
        doc.opts,
        doc.fonts,
        doc.drawable_strings,
        doc.is_living,
    )
    pid = chart.slots[pos]
    p = tree.people.get(pid) if pid else None
    fam = None
    initial_root = pos == 1 and not chart.via
    if initial_root and p is not None:
        fam = _root_family(tree, p, opts.root_family)
    elif has_marriage_lines(pos):
        # Continuation roots and fathers show the union that produced their child.
        child = chart.via if pos == 1 else chart.slots[pos // 2]
        fam = tree.parents_union(child, opts.parents) if child else None
    hide = opts.exclude_private and is_living(pid)
    marr_hide = hide or bool(
        opts.exclude_private
        and fam
        and (is_living(fam.father) or is_living(fam.mother))
    )
    marr = fam.marriage if fam and fam.marriage else Event()
    p = p or Person("")

    def row(label: str, value: str, hidden: bool, place: bool = False) -> BoxLine:
        if place:
            value = ", ".join(place_parts(value))
        return BoxLine(label, "" if hidden else fonts.clean(value), place)

    labels = drawable_strings["labels"]
    birth, birth_key = birth_source(p, opts.event_standins)
    death, death_key = death_source(p, opts.event_standins)
    relationship = tree.parent_relationship(pid, opts.parents) if pid else "birth"
    note = (
        ""
        if hide or relationship == "birth"
        else fonts.clean(drawable_strings["relationship"][relationship])
    )
    name = (
        drawable_strings["living_name"]
        if hide
        else fonts.clean(display_name(p, opts.preserve_case, doc.rules))
    )
    lines = [BoxLine(name, "", False, note)]
    lines += [
        row(labels[birth_key], format_date(birth.date, drawable_strings), hide),
        row(labels[birth_key + "_place"], birth.place, hide, place=True),
    ]
    if initial_root:
        spouse_id = (
            fam.mother
            if fam and fam.father == pid
            else fam.father
            if fam and fam.mother == pid
            else ""
        )
        spouse = tree.people.get(spouse_id)
        spouse_name = (
            drawable_strings["living_name"]
            if opts.exclude_private and is_living(spouse_id)
            else display_name(spouse, opts.preserve_case, doc.rules)
            if spouse
            else ""
        )
        lines.append(row(labels["spouse"], spouse_name, False))
    if has_marriage_lines(pos):
        lines += [
            row(
                labels["marriage"], format_date(marr.date, drawable_strings), marr_hide
            ),
            row(labels["marriage_place"], marr.place, marr_hide, place=True),
        ]
    lines += [
        row(labels[death_key], format_date(death.date, drawable_strings), hide),
        row(labels[death_key + "_place"], death.place, hide, place=True),
    ]
    return lines


# --------------------------------------------------------------------------
# Places: shortening long place lines
# --------------------------------------------------------------------------


def place_parts(place: str) -> list[str]:
    """A place as its comma-separated parts: each trimmed, empty parts left out."""
    return [part.strip() for part in place.split(",") if part.strip()]


def home_country(places: Iterable[str]) -> str | None:
    """The home country of a document: the most common last part of its places (trimmed,
    case-insensitive), if it occurs at least twice and strictly more often than any
    other last part. None otherwise (a tie, or no part that often). The result is
    casefolded.
    """
    counts = Counter(
        parts[-1].casefold() for parts in map(place_parts, places) if parts
    )
    ranked = counts.most_common(2)
    if (
        not ranked
        or ranked[0][1] < 2
        or (len(ranked) > 1 and ranked[1][1] == ranked[0][1])
    ):
        return None
    return ranked[0][0]


def _place_line(label: str, parts: list[str]) -> str:
    return _labeled(label, ", ".join(parts))


def shorten_place_line(
    label: str,
    place: str,
    home: str | None,
    fits: Callable[[str], bool],
    ellipsis: str = "…",
) -> str:
    """The place line "label place" (the place alone for an empty label), with
    trimmed comma-separated parts and empty parts omitted, shortened in steps that
    stop at the first line that `fits`:
    (a) without the home country, the last part, if the place has two or more parts
    and that part is the home country; (b) without the middle parts, one at a time
    starting with the second, keeping the first and the last. The dropped parts are
    marked with one part, the language's `ellipsis` ("A, …, D"). Step (a) leaves no
    mark. Otherwise the result is the last step made: the caller cuts it with the
    ellipsis if it still does not fit. A place with no parts prints only its label."""
    parts = place_parts(place)
    line = _place_line(label, parts)
    if fits(line) or not parts:
        return line
    if home is not None and len(parts) >= 2 and parts[-1].casefold() == home:
        parts = parts[:-1]
        line = _place_line(label, parts)
        if fits(line):
            return line
    first, middle, last = parts[0], parts[1:-1], parts[-1:]
    while middle:
        del middle[0]
        line = _place_line(label, [first, ellipsis, *middle, *last])
        if fits(line):
            return line
    return line


# --------------------------------------------------------------------------
# Chart boxes
# --------------------------------------------------------------------------


def _drawn_places(doc: _Doc, charts: list[Chart]) -> list[str]:
    """The place values the document's boxes draw (privacy applied), each once per box:
    the places home_country counts.
    """
    return [
        line.value
        for chart in charts
        for pos in _shown_boxes(chart, doc.opts.empty_boxes)
        for line in _box_lines(doc, chart, pos)
        if line.is_place and line.value
    ]


def _draw_continuation(
    c: canvas.Canvas, doc: _Doc, x1: float, y: float, number: str
) -> None:
    """A continuation chart number just right of its box (x1 is the box's right edge),
    never dropping a digit.

    It starts beyond the box's drop shadow (shadow_reach() with --shadow) and the
    continuation gap. If it would run past the page's right margin it is condensed, to
    half width at least; if it is still too wide it moves left just enough to end at the
    margin.
    """
    geom = doc.geom
    reach = shadow_reach(doc.opts.large_print) if doc.opts.shadow else 0.0
    x = x1 + reach + geom.continuation_gap
    room = geom.width - CONTINUATION_EDGE - x
    width = text_width(number, doc.fonts.italic, geom.size)
    scale = _squeeze_scale(room, width)
    if width * scale > room:
        x = geom.width - CONTINUATION_EDGE - width * scale
    draw_text(c, x, y, number, doc.fonts.italic, geom.size, scale)


def _record_id(
    pid: str | None,
    show: bool,
    fonts: FontSet,
    strings: Mapping[str, Any],
    size: float = RECORD_ID_SIZE,
    width: float | None = None,
) -> str:
    """The record ID a box (or an index entry) shows: the person's id, through the
    record_id string. "" when IDs are off or the box is empty. With `width`, an ID that
    is wider in `fonts.sans` at `size` is cut with the language's ellipsis: the id
    first, so the template's own text stays ("[WWW…]"), and the whole text only if the
    template alone is too wide.
    """
    if not (show and pid):
        return ""
    ident = fonts.clean(pid)
    record = fill(strings["record_id"], PLACEHOLDERS["record_id"], {"id": ident})
    if width is None or text_width(record, fonts.sans, size) <= width:
        return record
    frame = fill(strings["record_id"], PLACEHOLDERS["record_id"], {"id": ""})
    ident = fit(
        ident,
        fonts.sans,
        size,
        width - text_width(frame, fonts.sans, size),
        strings["ellipsis"],
    )
    record = fill(strings["record_id"], PLACEHOLDERS["record_id"], {"id": ident})
    return fit(record, fonts.sans, size, width, strings["ellipsis"])


def _draw_box_outline(c: canvas.Canvas, geom: PageGeom, pos: int, shadow: bool) -> None:
    """A box: its drop shadow, if wanted, then a white-filled rectangle that masks the
    connectors behind it.
    """
    x0, top, h = geom.box_x0[pos], geom.box_top[pos], geom.h(pos)
    if shadow:
        _shadow(c, x0, top, h, geom)
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0, 0, 0)
    c.rect(x0, geom.y(top + h), geom.box_w, h, stroke=1, fill=1)


SPOUSE_NAME_SCALE = 0.9


def _draw_spouse_line(
    c: canvas.Canvas, doc: _Doc, line: BoxLine, x: float, y: float
) -> None:
    """Keep the detail label small and draw the spouse in the name face."""
    fonts, geom = doc.fonts, doc.geom
    ellipsis = doc.drawable_strings["ellipsis"]
    name_size = geom.size * SPOUSE_NAME_SCALE
    label_room = geom.text_w
    if line.value:
        label_room -= text_width(" ", fonts.serif, geom.size) + text_width(
            ellipsis, fonts.sans, name_size
        )
    label, label_scale = fit_squeezed(
        line.label, fonts.serif, geom.size, max(0, label_room), ellipsis=ellipsis
    )
    prefix = label + " " if label and line.value else label
    prefix_width = text_width(prefix, fonts.serif, geom.size) * label_scale
    name, name_scale = fit_squeezed(
        line.value,
        fonts.sans,
        name_size,
        max(0, geom.text_w - prefix_width),
        ellipsis=ellipsis,
    )
    if prefix:
        draw_text(c, x, y, prefix, fonts.serif, geom.size, label_scale)
    if name:
        draw_text(c, x + prefix_width, y, name, fonts.sans, name_size, name_scale)


def _draw_box_text(c: canvas.Canvas, doc: _Doc, chart: Chart, pos: int) -> None:
    """A box's lines and record ID, its number, and the number of the chart its ancestry
    continues on.
    """
    fonts, geom, opts, ellipsis = (
        doc.fonts,
        doc.geom,
        doc.opts,
        doc.drawable_strings["ellipsis"],
    )
    x0, top, h = geom.box_x0[pos], geom.box_top[pos], geom.h(pos)
    # an ID takes at most id_max, so the name line keeps over half its width
    # (never a negative one)
    record = _record_id(
        chart.slots[pos],
        opts.show_ids and not doc.is_living(chart.slots[pos]),
        fonts,
        doc.drawable_strings,
        geom.id_size,
        geom.id_max,
    )
    id_room = (
        text_width(record, fonts.sans, geom.id_size) + geom.id_gap if record else 0
    )
    for i, line in enumerate(_box_lines(doc, chart, pos)):
        base = (
            top
            + geom.name_base
            + (geom.detail_gap + geom.leading * (i - 1) if i else 0)
        )
        if pos == 1 and geom.root_spouse and i == 3:
            _draw_spouse_line(c, doc, line, x0 + geom.inset_left, geom.y(base))
            continue
        font = fonts.sans if i == 0 else fonts.serif
        # the name line makes room for the record ID
        room = geom.text_w - id_room if i == 0 else geom.text_w
        text = line.text
        if line.is_place and line.value and opts.shorten_places:

            def fits(t: str, font: str = font, room: float = room) -> bool:
                return text_width(t, font, geom.size) <= room / SQUEEZE

            text = shorten_place_line(line.label, line.value, doc.home, fits, ellipsis)
        text, scale = fit_squeezed_noted(
            text, line.note, font, geom.size, room, ellipsis
        )
        draw_text(c, x0 + geom.inset_left, geom.y(base), text, font, geom.size, scale)
    if record:
        # Reportlab's Font stubs omit the face attribute.
        face = getFont(fonts.sans).face  # type: ignore[attr-defined]
        # Embedded fonts supply capHeight;
        # built-in Helvetica's ascent is its cap height.
        cap_height = getattr(face, "capHeight", face.ascent) / 1000
        id_base = top + geom.name_base - (geom.size - geom.id_size) * cap_height
        draw_text(
            c,
            x0 + geom.box_w - geom.inset_right,
            geom.y(id_base),
            record,
            fonts.sans,
            geom.id_size,
            right=True,
        )
    # box number, just outside the left edge: level with the name, or, on the odd boxes
    # of the right column (9, 11, 13, 15; in large print 5 and 7), with the last line
    number_y = (
        top + h - geom.bottom_pad
        if pos >= geom.first_right and pos % 2
        else top + geom.name_base
    )
    draw_text(
        c,
        x0 - geom.box_number_gap,
        geom.y(number_y),
        str(pos),
        fonts.bold,
        geom.size,
        right=True,
    )
    if pos in chart.continuations:  # chart where this ancestor continues
        _draw_continuation(
            c,
            doc,
            x0 + geom.box_w,
            geom.y(top + h / 2 + geom.continuation_drop),
            str(chart.continuations[pos]),
        )


def _chart_label(doc: _Doc, number: int) -> str:
    """Fit a chart label in half the header, keeping its chart-number fields."""
    fonts = doc.fonts
    template = doc.drawable_strings["chart_label"]
    values = {"n": number}
    label = fill(template, PLACEHOLDERS["chart_label"], values)
    room = (doc.geom.label_right - LEFT_MARGIN) / 2
    if text_width(label, fonts.sans, LABEL_SIZE) <= room:
        return label
    ellipsis = doc.drawable_strings["ellipsis"]
    # Drawable templates contain no NUL. fill distinguishes actual fields from
    # escaped braces, so this temporary separator marks only chart-number fields.
    parts = fill(template, PLACEHOLDERS["chart_label"], {"n": "\x00"}).split("\x00")
    if len(parts) == 1:
        return fit(label, fonts.sans, LABEL_SIZE, room, ellipsis)
    shortened: set[int] = set()
    while any(parts):
        index = max(range(len(parts)), key=lambda i: len(parts[i]))
        parts[index] = parts[index][:-1].rstrip()
        shortened.add(index)
        label = str(number).join(
            part + ellipsis if i in shortened else part for i, part in enumerate(parts)
        )
        if text_width(label, fonts.sans, LABEL_SIZE) <= room:
            return label
    # A template with excessive repetitions still identifies the chart once.
    return fit(str(number), fonts.sans, LABEL_SIZE, room, ellipsis)


def _draw_chart(
    c: canvas.Canvas,
    doc: _Doc,
    chart: Chart,
    page_number: str | None = None,
    blank: bool = False,
) -> None:
    """One chart page. `blank` is the sheet render_blank makes: an empty chart without
    its 'Chart N' label."""
    if not chart.via:
        # Center the enlarged root between its neighboring left-zone boxes.
        geom = doc.geom
        above, below = (2, 3) if geom.large_print else (5, 6)
        tops = dict(geom.box_top)
        root_height = geom.h(1) + geom.leading
        tops[1] = (
            geom.box_top[above] + geom.h(above) + geom.box_top[below] - root_height
        ) / 2
        doc = replace(
            doc,
            geom=replace(doc.geom, box_top=MappingProxyType(tops), root_spouse=True),
        )
    drawable_strings, geom, opts = doc.drawable_strings, doc.geom, doc.opts
    subtitle = ""
    if chart.origin:
        subtitle = fill(
            drawable_strings["continuation"],
            PLACEHOLDERS["continuation"],
            {"pos": chart.origin[1], "chart": chart.origin[0]},
        )
    # chart 1 says where its ancestry goes on, if it does
    elif chart.number == 1 and chart.continuations:
        subtitle = drawable_strings["chart_note"]
    label = "" if blank else _chart_label(doc, chart.number)
    # the subtitle runs left of the right column's boxes (all of which share one left
    # edge), never under them
    _frame(
        c,
        doc,
        drawable_strings["title"],
        label,
        subtitle,
        page_number,
        subtitle_right=geom.box_x0[geom.first_right] - SUBTITLE_CLEARANCE,
    )
    _connectors(c, functools.partial(_shown, chart, empty_boxes=opts.empty_boxes), geom)

    boxes = _shown_boxes(chart, opts.empty_boxes)
    c.setLineWidth(CHART_LINE_WIDTH)
    # every box first, white-filled so that it masks the connectors behind it;
    # then the text
    for pos in boxes:
        _draw_box_outline(c, geom, pos, opts.shadow)
    c.setFillColorRGB(0, 0, 0)
    for pos in boxes:
        _draw_box_text(c, doc, chart, pos)
    c.showPage()


# --------------------------------------------------------------------------
# Name index
# --------------------------------------------------------------------------


# the source of a birth -> its index piece
_INDEX_BIRTH = {"birth": "born", "christening": "christened"}
_INDEX_DEATH = {"death": "died", "burial": "buried", "cremation": "cremated"}


def build_index(
    tree: Tree,
    charts: list[Chart],
    is_living: Callable[[str | None], bool],
    exclude_private: bool,
    fonts: FontSet = BASE14,
    strings: Mapping[str, Any] = DEFAULT_STRINGS,
    event_standins: bool = True,
    show_ids: bool = False,
    preserve_case: bool = False,
) -> list[str]:
    """One line per person in a drawn box, sorted by surname, given name (without
    title), birth year and suffix, using the language's [sort] rules (SortRules).
    With exclude_private, living people are omitted from the index.
    With event_standins, a year from a christening, burial or cremation has its own
    piece. With show_ids, each entry carries the person's record ID after the name
    and before the years. A comma
    separates the name and years from the chart-box numbers."""
    where: dict[str, list[tuple[int, int]]] = {}
    for chart in charts:
        for pos in sorted(chart.drawn):
            if pid := chart.slots[pos]:
                where.setdefault(pid, []).append((chart.number, pos))

    rules = SortRules(strings.get("sort", {}))
    index = strings["index"]
    rows = []
    for pid, locs in where.items():
        p = tree.people[pid]
        if exclude_private and is_living(pid):
            continue
        birth, birth_key = birth_source(p, event_standins)
        death, death_key = death_source(p, event_standins)
        born, died = year_of(birth.date), year_of(death.date)
        born_piece, died_piece = _INDEX_BIRTH[birth_key], _INDEX_DEATH[death_key]
        pieces = []
        if born:
            pieces.append(
                fill(
                    index[born_piece],
                    PLACEHOLDERS[f"index.{born_piece}"],
                    {"birth": born},
                )
            )
        if died:
            pieces.append(
                fill(
                    index[died_piece],
                    PLACEHOLDERS[f"index.{died_piece}"],
                    {"death": died},
                )
            )
        joined = index["joiner"].join(pieces)
        years = (
            " " + fill(index["years"], PLACEHOLDERS["index.years"], {"years": joined})
            if joined
            else ""
        )
        record = _record_id(pid, show_ids, fonts, strings)
        places = ", ".join(
            fill(
                index["reference"],
                PLACEHOLDERS["index.reference"],
                {"chart": c, "pos": pos},
            )
            for c, pos in sorted(locs)
        )
        text = (
            index_name(p, preserve_case, rules)
            + (" " + record if record else "")
            + years
            + ", "
            + places
        )
        # displayed as written, but sorted with the surnameless
        blank = is_placeholder_surname(p.surname)
        key = (
            blank,
            "" if blank else rules.fold(p.surname, surname=True),
            rules.fold(p.given),
            born or 9999,
            rules.fold(p.suffix),
            pid,
        )
        rows.append((key, fonts.clean(text)))
    return [text for _, text in sorted(rows)]


IndexLine = tuple[str, float]  # (text, indent)
IndexPages = list[list[list[list[IndexLine]]]]  # pages -> columns -> entries -> lines


def _wrap_index_entry(
    text: str, font: str, col_w: float, ellipsis: str = "…"
) -> list[IndexLine]:
    """Greedy word wrap by kerned width; continuation lines are indented and given that
    much less room.
    """
    lines: list[IndexLine] = []
    current = ""

    def finish_line() -> None:
        indent = INDEX_HANGING if lines else 0
        lines.append((fit(current, font, INDEX_SIZE, col_w - indent, ellipsis), indent))

    for word in text.split():
        trial = f"{current} {word}" if current else word
        if (
            text_width(trial, font, INDEX_SIZE)
            <= col_w - (INDEX_HANGING if lines else 0)
            or not current
        ):
            current = trial
        else:
            finish_line()
            current = word
    if current:
        finish_line()
    return lines


def _index_pages(
    entries: list[str], font: str, geom: PageGeom, ellipsis: str = "…"
) -> IndexPages:
    """Wrap entries (hanging indent) and flow them into pages -> columns -> entries ->
    lines.

    An entry moves to the next column when it does not fit but would fit in a fresh one;
    an entry taller than a whole column (a person met in hundreds of boxes) is split and
    continues in the next column.
    """
    per_col = int((geom.y_bottom - INDEX_TOP) // INDEX_LEADING) + 1
    pages: IndexPages = [[[]]] if entries else []
    used = 0

    def next_column() -> None:
        nonlocal used
        used = 0
        if len(pages[-1]) < INDEX_COLS:
            pages[-1].append([])
        else:
            pages.append([[]])

    for text in entries:
        lines = _wrap_index_entry(text, font, geom.index_col_w, ellipsis)
        if used and used + len(lines) > per_col and len(lines) <= per_col:
            next_column()
        while lines:
            if used >= per_col:
                next_column()
            chunk, lines = lines[: per_col - used], lines[per_col - used :]
            pages[-1][-1].append(chunk)
            used += len(chunk)
    return pages


def _draw_index(
    c: canvas.Canvas,
    doc: _Doc,
    pages: IndexPages,
    page_numbers: list[str | None] | None = None,
) -> None:
    """The index pages from _index_pages; page_numbers, if given, holds the page number
    text of each page. The legend (index.legend, empty for none) is the subtitle line
    under the title of the first page only.
    """
    index = doc.drawable_strings["index"]
    geom = doc.geom
    for i, page in enumerate(pages):
        _frame(
            c,
            doc,
            index["title"],
            "",
            index["legend"] if i == 0 else "",
            page_numbers[i] if page_numbers else None,
        )
        for ci, column in enumerate(page):
            y = INDEX_TOP
            for lines in column:
                for text, indent in lines:
                    draw_text(
                        c,
                        INDEX_LEFT + ci * (geom.index_col_w + INDEX_GUTTER) + indent,
                        geom.y(y),
                        text,
                        doc.fonts.serif,
                        INDEX_SIZE,
                    )
                    y += INDEX_LEADING
        c.showPage()


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


@dataclass
class Options:
    """Everything that changes what render() draws. The names are those of the
    command-line flags, with the on/off flags that remove something (--no-index,
    --no-empty, ...) turned around: `index=False`, `empty_boxes=False`.
    `today` sets the footer date and the year used by the privacy estimate; None
    uses today. `today`, `compress` and `fonts` have no command-line flag.
    """

    # ---- what is drawn
    # --generations: counting the root as 1; None: every known ancestor
    generations: int | None = None
    # --exclude-private: hide names and details of people who may be living
    # (see Person.living)
    exclude_private: bool = False
    # --adoptive-parents: which parent family is drawn for a person who belongs to
    # several: False, the one with the most birth parents (the first birth family);
    # True, a family with an adopted parent first, then one with a foster parent, then
    # as False (see Tree.parent_family). A step-parent is never drawn either way.
    adoptive_parents: bool = False
    # --no-event-standins: True, a christening, baptism, burial or cremation stands in
    # for a missing birth or death in the box lines and the index (see birth_source and
    # death_source). False: only birth and death. Privacy uses all event records
    # regardless of this display option.
    event_standins: bool = True
    # --no-empty: False leaves out the boxes of unknown ancestors
    empty_boxes: bool = True
    show_ids: bool = False  # --show-ids: each box shows its person's id
    # --no-shorten-places: False cuts a place line that does not fit with the ellipsis
    # only; see shorten_place_line
    shorten_places: bool = True
    # ---- the pages
    index: bool = True  # --no-index: False leaves out the name index
    # --no-page-numbers: False leaves out "Page n of N", bottom left of every page
    page_numbers: bool = True
    # --footer / --no-footer: text for every page; False for none; None for the
    # language's footer, "Created <date> using Kincade" in English
    footer: str | Literal[False] | None = None
    # --title: None is the language's title (English: "Cascading Pedigree")
    title: str | None = None
    paper: str = "letter"  # --paper: 'letter' or 'a4' (see PAPER_SIZES)
    # --large-print: 14 pt box text and three generations per page
    large_print: bool = False
    shadow: bool = False  # --shadow: a drop shadow under each box
    # --lang: a language name (kincade/lang/<name>.toml, then ~/.config/kincade/lang/),
    # the path of a .toml file, or a mapping of strings that are laid over the English
    # ones (partial or complete). A bad one raises LangError.
    lang: str | Mapping[str, Any] | None = None
    # ---- not command-line flags
    # The footer date and the privacy estimate's year; None is today.
    today: datetime.date | None = None
    compress: bool = True  # PDF stream compression
    # 'auto' (embed TrueType if available), 'base14', or a FontSet
    fonts: str | FontSet = "auto"
    # --preserve-case: use the surname as recorded instead of uppercasing it
    preserve_case: bool = False
    # --root-family: one initial-root spouse family; None keeps the first FAMS.
    # It does not choose ancestors or affect continuation roots or the index.
    root_family: str | None = None

    @property
    def parents(self) -> str:
        """The word plan_charts and Tree.parent_family take for adoptive_parents:
        "birth" or "adoptive".
        """
        return "adoptive" if self.adoptive_parents else "birth"


def _language(opts: Options) -> tuple[dict[str, Any], str, FontSet, dict[str, Any]]:
    """The raw strings, title, fonts and strings made drawable with those fonts.
    Options.title supplies the title when given."""
    raw_strings = (
        load_strings(None, opts.lang)
        if isinstance(opts.lang, Mapping)
        else load_strings(opts.lang)
    )
    title = opts.title if opts.title is not None else raw_strings["title"]
    fonts = choose_fonts(opts.fonts)
    # every text on the page is made drawable with this font set
    drawable_strings = map_leaves(raw_strings, fonts.clean)
    # Sort rules are never drawn, so they keep their exact characters.
    drawable_strings["sort"] = raw_strings["sort"]
    if opts.title is not None:
        drawable_strings["title"] = fonts.clean(opts.title)
    return raw_strings, title, fonts, drawable_strings


def footer_text(
    footer: str | Literal[False] | None,
    strings: Mapping[str, Any],
    today: datetime.date | None,
) -> str | None:
    """Custom footer, no footer for False, else the language's dated or blank footer."""
    if footer is False:
        return None
    if isinstance(footer, str):
        return footer
    if today is None:
        return strings["footer_blank"]
    date = fill(
        strings["date_format"],
        PLACEHOLDERS["date_format"],
        {
            "day": day_number(today.day, strings),
            "month": strings["months"]["short"][today.month - 1],
            "year": str(today.year),
        },
    )
    return fill(strings["footer"], PLACEHOLDERS["footer"], {"date": date})


def new_canvas(
    width: float, height: float, compress: bool, fonts: FontSet
) -> tuple[io.BytesIO, canvas.Canvas]:
    """A PDF buffer and canvas with the page size, font set and Kincade metadata."""
    buf = io.BytesIO()
    # types-reportlab declares initialFontName a float; reportlab takes a font name
    c = canvas.Canvas(
        buf,
        pagesize=(width, height),
        pageCompression=1 if compress else 0,
        initialFontName=fonts.sans,  # type: ignore[arg-type]
        initialFontSize=SIZE,
    )
    c.setCreator("Kincade")
    c.setAuthor("")
    c.setSubject("")
    return buf, c


def _living_check(
    tree: Tree, charts: list[Chart], opts: Options, this_year: int
) -> Callable[[str | None], bool]:
    """Whether a person may be living, for a render: no one when privacy is off, else
    the estimate (or, for a person who has one, the caller's verdict: Person.living).
    """
    if not opts.exclude_private:
        return nobody_living
    # Estimates come from the whole pedigree, not only the drawn boxes, so a limited
    # render gives every drawn person the status they have in an unlimited run (a deeper
    # appearance can hold a dated descendant)
    # box 1 of chart 1 holds the root person: planning never leaves it empty
    whole = plan_charts(
        tree,
        charts[0].slots[1],  # type: ignore[arg-type]
        None,
        opts.parents,
        opts.large_print,
    )
    return living_checker(tree, whole, this_year)


class Rendered(NamedTuple):
    """A drawn pedigree and what the command line says of it: the PDF's bytes, how many
    of its pages are charts and how many are index pages (none with Options.index off).
    """

    pdf: bytes
    chart_pages: int
    index_pages: int
    root_name: str = ""  # the privacy-safe display name used in PDF metadata

    @property
    def pages(self) -> int:
        return self.chart_pages + self.index_pages


def render(tree: Tree, root: str, options: Options | None = None) -> bytes:
    """The cascading pedigree of the person `root` (an id in `tree.people`) as PDF
    bytes, in one call: the charts are planned (Options.generations, adoptive_parents,
    large_print), who may be living is worked out (exclude_private), and the pages are
    drawn. An unknown `root` is a KeyError, a bad option a ValueError, a bad language a
    LangError. plan_charts and render_pdf are the two halves of this, for callers that
    want to look at the charts between.
    """
    return render_with_counts(tree, root, options).pdf


def render_with_counts(
    tree: Tree, root: str, options: Options | None = None
) -> Rendered:
    """What render does, with the number of charts and of index pages it drew, which the
    command line reports. Not one of the names `kincade` promises.
    """
    opts = options or Options()
    return _draw_document(
        plan_charts(tree, root, opts.generations, opts.parents, opts.large_print),
        tree,
        opts,
    )


def render_pdf(
    charts: list[Chart], tree: Tree, options: Options | None = None
) -> bytes:
    """Charts that plan_charts made, and the index, drawn as PDF bytes. The charts must
    be planned as the options draw them: with the same large_print, and with parents
    "adoptive" exactly when adoptive_parents is on. A chart that differs, or no chart
    at all, is a ValueError."""
    return _draw_document(charts, tree, options or Options()).pdf


def _draw_document(charts: list[Chart], tree: Tree, opts: Options) -> Rendered:
    """Draw planned charts, and the index, as a PDF."""
    if not charts:
        raise ValueError("no charts to draw: plan_charts makes at least one")
    root = tree.people[charts[0].slots[1]]  # type: ignore[index]
    family = _root_family(tree, root, opts.root_family)
    if opts.root_family is not None and family is not None:
        opts = replace(opts, root_family=family.id)
    geom = page_geom(opts.paper, opts.large_print, opts.shadow)
    for chart in charts:
        if chart.depth != geom.gens:
            raise ValueError(
                f"chart {chart.number} is {chart.depth} generations deep, but large_print="
                f"{opts.large_print} draws {geom.gens}: plan the charts with the same large_print"
            )
        if chart.parents != opts.parents:
            raise ValueError(
                f"chart {chart.number} is planned with parents {chart.parents!r}, but "
                f"adoptive_parents={opts.adoptive_parents} draws {opts.parents!r}: plan the "
                "charts with the same parents"
            )
    today = opts.today or datetime.date.today()
    raw_strings, title, fonts, drawable_strings = _language(opts)
    doc = _Doc(
        tree,
        opts,
        fonts,
        drawable_strings,
        _living_check(tree, charts, opts, today.year),
        geom,
        fonts.clean(footer)
        if (footer := footer_text(opts.footer, raw_strings, today)) is not None
        else None,
    )
    if opts.shorten_places:
        # The root-family choice is local to its box. Keep the first FAMS in
        # the country count so it cannot change ancestor or continuation text.
        place_context = replace(doc, opts=replace(opts, root_family=None))
        doc = replace(doc, home=home_country(_drawn_places(place_context, charts)))
    # box 1 of chart 1 holds the root person: planning never leaves it empty
    root = tree.people[charts[0].slots[1]]  # type: ignore[index]
    root_name = (
        raw_strings["living_name"]
        if doc.is_living(root.id)
        else display_name(root, opts.preserve_case, doc.rules)
    )
    buf, c = new_canvas(geom.width, geom.height, opts.compress, fonts)
    document_title = fill(
        raw_strings["meta_title"],
        PLACEHOLDERS["meta_title"],
        {"title": title, "name": root_name},
    )
    c.setTitle(document_title)
    if opts.title is None:
        drawable_strings["title"] = fonts.clean(document_title)
    # the index draws no shadows, so it keeps the plain layout
    index_doc = replace(doc, geom=page_geom(opts.paper, opts.large_print))
    index_pages = []
    if opts.index:
        entries = build_index(
            tree,
            charts,
            is_living=doc.is_living,
            exclude_private=opts.exclude_private,
            fonts=fonts,
            strings=drawable_strings,
            event_standins=opts.event_standins,
            show_ids=opts.show_ids,
            preserve_case=opts.preserve_case,
        )
        index_pages = _index_pages(
            entries, fonts.serif, index_doc.geom, drawable_strings["ellipsis"]
        )
    # the page count is known before the first page is drawn
    total = len(charts) + len(index_pages)
    page_numbers: list[str | None] = [
        fill(
            drawable_strings["page_number"],
            PLACEHOLDERS["page_number"],
            {"page": n, "pages": total},
        )
        if opts.page_numbers
        else None
        for n in range(1, total + 1)
    ]
    # page_numbers go on to number the index pages
    for chart, page_number in zip(charts, page_numbers, strict=False):
        _draw_chart(c, doc, chart, page_number)
    if index_pages:
        _draw_index(c, index_doc, index_pages, page_numbers[len(charts) :])
    c.save()
    return Rendered(buf.getvalue(), len(charts), len(index_pages), root_name)


def render_blank(options: Options | None = None) -> bytes:
    """One blank chart to fill in by hand, as PDF bytes (--blank): one page with the
    title, the numbered boxes of chart 1 (1-15, or 1-7 in large print) and their lines,
    laid out as chart 1 is. Each box holds the labels to write after (b., bp., d., dp.,
    and m., mp. on box 1 and the fathers' boxes) under an empty name line. The root
    also has a spouse line. There is no chart label, page number, note, continuation
    or record ID, and the footer is the language's footer_blank, without the date.

    Needs no tree. Respects paper, large_print, shadow, lang, title, footer, fonts and
    compress; every other option has nothing to apply to and is ignored."""
    # all the boxes, whatever empty_boxes says
    opts = replace(options or Options(), empty_boxes=True)
    geom = page_geom(opts.paper, opts.large_print, opts.shadow)
    raw_strings, title, fonts, drawable_strings = _language(opts)
    buf, c = new_canvas(geom.width, geom.height, opts.compress, fonts)
    c.setTitle(title)
    doc = _Doc(
        Tree(),
        opts,
        fonts,
        drawable_strings,
        nobody_living,
        geom,
        fonts.clean(footer)
        if (footer := footer_text(opts.footer, raw_strings, None)) is not None
        else None,
    )
    chart = Chart(
        1,
        dict.fromkeys(range(1, 16)),
        drawn=frozenset(range(1, 2**geom.gens)),
        depth=geom.gens,
    )
    _draw_chart(c, doc, chart, blank=True)
    c.save()
    return buf.getvalue()

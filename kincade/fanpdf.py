"""Draw a supplied fan on one landscape page, using pdf's fonts and text metrics."""

from __future__ import annotations

import datetime
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from reportlab.pdfbase.pdfmetrics import getAscentDescent
from reportlab.pdfgen import canvas

from . import pdf
from .fan import (
    RING_TEXT_SIZES,
    Fan,
    FanCell,
    cell_angles,
    check_fan,
    fan_radius,
    mark_text,
    middle_angle,
    ring_of,
    ring_radii,
    text_candidates,
)
from .lang import fill, load_strings
from .pdf import FOOTER_SIZE, SQUEEZE, TITLE_SIZE, FontSet

FAN_PAPER = {
    "letter": (792, 612),
    "a4": (841.89, 595.28),
    "tabloid": (1224, 792),
    "a3": (1190.55, 841.89),
}  # landscape page sizes in points
INKS = ("color", "grayscale", "bw")
MARGIN = 36  # clear space at each page edge, in points
TITLE_GAP = 10  # space below the title before the fan, in points
FOOTER_GAP = 10  # space above the footer before the fan and legend, in points
LEADING = 1.15  # cell line spacing as a multiple of its type size
TEXT_MARGIN = 0.3  # space at each text edge as a multiple of the cell type size
MARK_SCALE = 0.7  # bold copy mark's type size as a share of the cell type size
SEPARATOR_WIDTH = 0.5  # cell outlines, in points
HIGHLIGHT_WIDTH = 2  # bw highlighted outline as a multiple of its normal width
EMPTY_DASH = (2, 2)  # empty cells' dash and gap lengths, in points
OUTLINE_GRAY = 0.5  # unfilled and empty cells' outline, from black 0 to white 1
DARK_GRAY = 0.25  # filled cells' outline and legend swatch outline
PALE_GRAY = 0.8  # faded grayscale cells' outline
FADE_WHITE = 3  # parts white mixed with one part of a faded color fill
LEGEND_SIZES = (9, 8.5, 8, 7.5, 7)  # legend type sizes tried in points
LEGEND_LEADING = 1.25  # legend row height as a multiple of its type size
LEGEND_SWATCH = 0.8  # legend swatch side as a multiple of its type size
LEGEND_SWATCH_GAP = 4  # space between a legend swatch and its text, in points
LEGEND_COLUMN_GAP = 14  # space between legend columns, in points
LEGEND_CLEARANCE = 6  # legend clearance from the center disc and gap edges, in points
FAN_SHRINK = 0.95  # radius multiplier between legend searches
MIN_FAN_SCALE = 0.25  # least share of the full radius allowed by the legend search
GAP_HALF_ANGLE = 60  # half the fan's bottom gap, in degrees
LOWER_REACH = 0.5  # sectors reach this share of the radius below the center
ARC_LAST_RING = 3  # last ring whose text follows an arc
RIGHT_ANGLE = 90  # vertical axis and the tangent's turn from a radius, in degrees
HALF_TURN = 180  # reversal that keeps left-side text upright, in degrees


@dataclass
class FanOptions:
    """Ink, paper, language and page text; fonts, date and compression as in Options."""

    ink: str = "color"
    paper: str = "letter"
    lang: str | Mapping[str, Any] | None = None
    title: str | None = None
    footer: str | Literal[False] | None = None
    today: datetime.date | None = None
    compress: bool = True
    fonts: str | FontSet = "auto"


@dataclass(frozen=True)
class LegendBox:
    """One complete legend entry's box, in PDF coordinates from the bottom left."""

    text: str
    color: str | None
    x: float
    y: float
    width: float
    height: float
    size: float


@dataclass(frozen=True)
class PageLayout:
    """Page text, fan scale and legend boxes, in PDF coordinates from the bottom left."""

    width: float
    height: float
    title: str
    footer: str | None
    region_top: float
    region_bottom: float
    center: tuple[float, float]
    radius: float
    scale: float
    units: float
    text_sizes: tuple[float, ...]
    legend: tuple[LegendBox, ...]


def _legend_boxes(
    fan: Fan, layout: PageLayout, fonts: FontSet
) -> tuple[LegendBox, ...] | None:
    cx, cy = layout.center
    center_radius = ring_radii(0)[1] * layout.units
    lowest = cy - max(layout.radius * LOWER_REACH, center_radius)
    entries = [
        (fonts.clean(f"{entry.label} ({entry.count})"), entry.color)
        for entry in fan.legend
    ]
    for size in LEGEND_SIZES:
        row_height = LEGEND_LEADING * size
        widths = [
            LEGEND_SWATCH * size
            + LEGEND_SWATCH_GAP
            + pdf.text_width(text, fonts.sans, size)
            for text, _ in entries
        ]
        for columns in range(1, len(entries) + 1):
            rows = math.ceil(len(entries) / columns)
            column_widths = [
                max(widths[i : i + rows]) for i in range(0, len(entries), rows)
            ]
            width = sum(column_widths) + LEGEND_COLUMN_GAP * (len(column_widths) - 1)
            height = rows * row_height
            top = layout.region_bottom + height
            depth = cy - top
            if (
                width > layout.width - 2 * MARGIN
                or depth < center_radius + LEGEND_CLEARANCE
            ):
                continue
            if (
                top > lowest
                and width / 2
                > depth * math.tan(math.radians(GAP_HALF_ANGLE)) - LEGEND_CLEARANCE
            ):
                continue
            boxes = []
            x = cx - width / 2
            for col, col_width in enumerate(column_widths):
                for row, (text, color) in enumerate(
                    entries[col * rows : (col + 1) * rows]
                ):
                    boxes.append(
                        LegendBox(
                            text,
                            color,
                            x,
                            top - (row + 1) * row_height,
                            col_width,
                            row_height,
                            size,
                        )
                    )
                x += col_width + LEGEND_COLUMN_GAP
            return tuple(boxes)
    return None


def page_layout(
    fan: Fan, options: FanOptions, strings: Mapping[str, Any], fonts: FontSet
) -> PageLayout:
    """Fit the fan below the title, shrinking it until every legend entry fits."""
    width, height = FAN_PAPER[options.paper]
    title = (
        options.title
        if options.title is not None
        else fill(strings["fan_title"], ("name",), {"name": fan.name})
    )
    footer = pdf.footer_text(
        options.footer, strings, options.today or datetime.date.today()
    )
    room = width - 2 * MARGIN
    ellipsis = fonts.clean(strings["ellipsis"])
    footer = (
        pdf.fit(fonts.clean(footer), fonts.sans, FOOTER_SIZE, room, ellipsis)
        if footer is not None
        else None
    )
    top = height - MARGIN - TITLE_SIZE - TITLE_GAP
    bottom = MARGIN + FOOTER_SIZE + FOOTER_GAP if footer else MARGIN
    reach = max(LOWER_REACH, ring_radii(0)[1] / fan_radius(fan.generations))
    full_radius = min(room / 2, (top - bottom) / (1 + reach))
    scale = 1.0
    while True:
        radius = full_radius * scale
        units = radius / fan_radius(fan.generations)
        layout = PageLayout(
            width,
            height,
            title,
            footer,
            top,
            bottom,
            (width / 2, top - radius),
            radius,
            scale,
            units,
            tuple(size * units for size in RING_TEXT_SIZES),
            (),
        )
        if not fan.legend or options.ink == "bw":
            return layout
        boxes = _legend_boxes(fan, layout, fonts)
        if boxes is not None:
            return replace(layout, legend=boxes)
        if scale == MIN_FAN_SCALE:
            raise ValueError(f"legend with {len(fan.legend)} entries does not fit")
        scale = max(MIN_FAN_SCALE, scale * FAN_SHRINK)


def text_direction(slot: int) -> str:
    """Level center, clockwise arc text in rings 1–3, radial text in rings 4–6."""
    ring, middle = ring_of(slot), middle_angle(slot)
    if ring == 0:
        return "level"
    if ring <= ARC_LAST_RING:
        return "clockwise"
    return "inward" if middle > RIGHT_ANGLE else "outward"


@dataclass(frozen=True)
class PlacedLine:
    """A fitted line, with radius for arcs and offset across level or radial text.
    Start and end delimit its centered text room along the baseline.
    """

    text: str
    size: float
    scale: float
    direction: str
    radius: float
    offset: float
    start: float
    end: float


def _line_rooms(
    cell: FanCell, layout: PageLayout, fonts: FontSet, count: int
) -> list[PlacedLine] | None:
    ring = ring_of(cell.slot)
    inner, outer = (r * layout.units for r in ring_radii(ring))
    size = layout.text_sizes[ring]
    margin, direction = TEXT_MARGIN * size, text_direction(cell.slot)
    mark = fonts.clean(mark_text(cell.copies))
    mark_size = MARK_SCALE * size
    mark_room = pdf.text_width(mark, fonts.bold, mark_size) + margin if mark else 0
    band = mark_size + margin if mark else 0
    block = size + (count - 1) * LEADING * size
    angle = math.radians(cell_angles(cell.slot)[0] - cell_angles(cell.slot)[1])
    lines = []
    if (
        direction in ("clockwise", "counterclockwise")
        and block > outer - inner - 2 * margin - band
    ):
        return None
    for i in range(count):
        offset = ((count - 1) / 2 - i) * LEADING * size
        if direction == "level":
            offset -= band / 2
            edge = abs(offset) + size / 2
            if edge >= outer - margin:
                return None
            room = math.sqrt(outer**2 - edge**2) - margin
            line = PlacedLine("", size, 1, direction, 0, offset, -room, room)
        elif direction in ("clockwise", "counterclockwise"):
            radius = (inner + outer - band) / 2
            radius += offset if direction == "clockwise" else -offset
            room = (radius - size / 2) * angle - 2 * margin
            line = PlacedLine("", size, 1, direction, radius, 0, -room / 2, room / 2)
        else:
            edge = abs(offset) + size / 2
            if edge >= outer:
                return None
            start = max(inner + margin, edge / math.tan(angle / 2) + margin)
            end = math.sqrt(outer**2 - edge**2) - margin - mark_room
            line = PlacedLine("", size, 1, direction, 0, offset, start, end)
        lines.append(line)
    return lines


def fit_cell(
    cell: FanCell, geometry: PageLayout, fonts: FontSet, ellipsis: str
) -> list[PlacedLine] | None:
    """The first complete candidate that fits, reserving space for the copy mark."""
    ellipsis = fonts.clean(ellipsis)
    for candidate in text_candidates(cell):
        rooms = _line_rooms(cell, geometry, fonts, len(candidate.lines))
        if rooms is None:
            continue
        placed = []
        for raw_text, line in zip(candidate.lines, rooms, strict=True):
            text = fonts.clean(raw_text)
            room = line.end - line.start
            if room <= 0:
                if candidate.cut:
                    continue
                break
            width = pdf.text_width(text, fonts.sans, line.size)
            if candidate.cut:
                text, scale = pdf.fit_squeezed(
                    text, fonts.sans, line.size, room, ellipsis
                )
            else:
                scale = min(1.0, room / width) if width else 1.0
                if scale < (SQUEEZE if candidate.squeeze else 1.0):
                    break
            if text:
                placed.append(replace(line, text=text, scale=scale))
        else:
            if placed:
                return placed
    return None


def _rgb(color: str) -> tuple[float, float, float]:
    return tuple(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _cell_ink(
    cell: FanCell, fan: Fan, options: FanOptions
) -> tuple[tuple[float, float, float] | None, float, float]:
    faded = bool(fan.highlight) and cell.slot not in fan.highlight
    width = SEPARATOR_WIDTH
    if cell.empty:
        return None, OUTLINE_GRAY, width
    if options.ink == "bw":
        return None, 0, width * (HIGHLIGHT_WIDTH if cell.slot in fan.highlight else 1)
    if options.ink == "grayscale" and faded:
        return None, PALE_GRAY, width
    color = _rgb(cell.fill) if cell.fill else None
    if color is not None and faded:
        color = tuple((channel + FADE_WHITE) / (1 + FADE_WHITE) for channel in color)  # type: ignore[assignment]
    outline = DARK_GRAY if color else OUTLINE_GRAY
    return color, outline, width


def _text_color(color: tuple[float, float, float] | None) -> float:
    if color is None:
        return 0
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in color
    ]
    luminance = sum(
        c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
    )
    return 1 if 1.05 / (luminance + 0.05) > (luminance + 0.05) / 0.05 else 0


def _draw_cell(
    c: canvas.Canvas, cell: FanCell, fan: Fan, options: FanOptions, layout: PageLayout
) -> float:
    color, outline, width = _cell_ink(cell, fan, options)
    c.saveState()
    c.setStrokeColorRGB(outline, outline, outline)
    c.setLineWidth(width)
    if cell.empty:
        c.setDash(EMPTY_DASH)
    if color is not None:
        c.setFillColorRGB(*color)
    cx, cy = layout.center
    inner, outer = (r * layout.units for r in ring_radii(ring_of(cell.slot)))
    if cell.slot == 1:
        c.circle(cx, cy, outer, stroke=1, fill=int(color is not None))
    else:
        start, end = cell_angles(cell.slot)
        path = c.beginPath()
        # types-reportlab declares integer angles; reportlab accepts fractional degrees.
        path.arc(
            cx - outer,
            cy - outer,
            cx + outer,
            cy + outer,
            startAng=end,  # type: ignore[arg-type]
            extent=start - end,  # type: ignore[arg-type]
        )
        path.arcTo(
            cx - inner,
            cy - inner,
            cx + inner,
            cy + inner,
            startAng=start,  # type: ignore[arg-type]
            extent=end - start,  # type: ignore[arg-type]
        )
        path.close()
        c.drawPath(path, stroke=1, fill=int(color is not None))
    c.restoreState()
    return _text_color(color)


def _draw_line(
    c: canvas.Canvas, cell: FanCell, line: PlacedLine, layout: PageLayout, font: str
) -> None:
    cx, cy = layout.center
    ascent, descent = getAscentDescent(font, line.size)
    baseline = (ascent + descent) / 2
    width = pdf.text_width(line.text, font, line.size) * line.scale
    middle = math.radians(middle_angle(cell.slot))
    if line.direction in ("clockwise", "counterclockwise"):
        clockwise = line.direction == "clockwise"
        radius = line.radius - baseline if clockwise else line.radius + baseline
        sign = -1 if clockwise else 1
        cursor = -width / 2
        t = c.beginText()
        t.setFont(font, line.size)
        t.setHorizScale(line.scale * 100)
        for ch, raw_advance in zip(
            line.text, pdf.char_advances(line.text, font, line.size), strict=True
        ):
            advance = raw_advance * line.scale
            angle = middle + sign * (cursor + advance / 2) / radius
            rotation = angle + sign * math.radians(RIGHT_ANGLE)
            cos, sin = math.cos(rotation), math.sin(rotation)
            x = cx + radius * math.cos(angle) - advance / 2 * cos
            y = cy + radius * math.sin(angle) - advance / 2 * sin
            t.setTextTransform(cos, sin, -sin, cos, x, y)
            t.textOut(ch)
            cursor += advance
        t.setHorizScale(100)
        c.drawText(t)
    else:
        c.saveState()
        c.translate(cx, cy)
        if line.direction != "level":
            c.rotate(
                math.degrees(middle) + (HALF_TURN if line.direction == "inward" else 0)
            )
        x = (line.start + line.end - width) / 2
        if line.direction == "inward":
            x = -(line.start + line.end + width) / 2
        pdf.draw_text(
            c, x, line.offset - baseline, line.text, font, line.size, line.scale
        )
        c.restoreState()


def _mark_line(cell: FanCell, layout: PageLayout, fonts: FontSet) -> PlacedLine | None:
    text = fonts.clean(mark_text(cell.copies))
    if not text or cell.empty:
        return None
    ring = ring_of(cell.slot)
    size = layout.text_sizes[ring] * MARK_SCALE
    outer = ring_radii(ring)[1] * layout.units
    margin = TEXT_MARGIN * layout.text_sizes[ring]
    direction = text_direction(cell.slot)
    width = pdf.text_width(text, fonts.bold, size)
    if direction == "level":
        offset = outer - margin - size / 2
        room = math.sqrt(max(0, outer**2 - (offset + size / 2) ** 2)) - margin
        return (
            PlacedLine(text, size, 1, direction, 0, offset, -room, room)
            if width <= 2 * room
            else None
        )
    if direction in ("clockwise", "counterclockwise"):
        return PlacedLine(
            text,
            size,
            1,
            direction,
            outer - margin - size / 2,
            0,
            -width / 2,
            width / 2,
        )
    return PlacedLine(
        text, size, 1, direction, 0, 0, outer - margin - width, outer - margin
    )


def _draw_legend(
    c: canvas.Canvas, box: LegendBox, options: FanOptions, fonts: FontSet
) -> None:
    swatch = LEGEND_SWATCH * box.size
    c.saveState()
    c.setLineWidth(SEPARATOR_WIDTH)
    c.setStrokeColorRGB(DARK_GRAY, DARK_GRAY, DARK_GRAY)
    if box.color:
        c.setFillColorRGB(*_rgb(box.color))
    c.rect(
        box.x,
        box.y + (box.height - swatch) / 2,
        swatch,
        swatch,
        stroke=int(box.color is None or options.ink == "grayscale"),
        fill=int(box.color is not None),
    )
    c.setFillColorRGB(0, 0, 0)
    ascent, descent = getAscentDescent(fonts.sans, box.size)
    pdf.draw_text(
        c,
        box.x + swatch + LEGEND_SWATCH_GAP,
        box.y + (box.height - ascent - descent) / 2,
        box.text,
        fonts.sans,
        box.size,
    )
    c.restoreState()


def render_fan(fan: Fan, options: FanOptions | None = None) -> bytes:
    """Validate and draw a supplied fan, returning one landscape page of PDF bytes."""
    check_fan(fan)
    options = options or FanOptions()
    if options.ink not in INKS:
        raise ValueError(f"ink must be one of {INKS}, not {options.ink!r}")
    if options.paper not in FAN_PAPER:
        raise ValueError(
            f"paper must be one of {tuple(FAN_PAPER)}, not {options.paper!r}"
        )
    strings = (
        load_strings(None, options.lang)
        if isinstance(options.lang, Mapping)
        else load_strings(options.lang)
    )
    fonts = pdf.choose_fonts(options.fonts)
    layout = page_layout(fan, options, strings, fonts)
    buf, c = pdf.new_canvas(layout.width, layout.height, options.compress, fonts)
    c.setTitle(layout.title)
    c.setFillColorRGB(0, 0, 0)
    pdf.draw_text(
        c,
        MARGIN,
        layout.height - MARGIN - TITLE_SIZE,
        pdf.fit(
            fonts.clean(layout.title),
            fonts.bold,
            TITLE_SIZE,
            layout.width - 2 * MARGIN,
            fonts.clean(strings["ellipsis"]),
        ),
        fonts.bold,
        TITLE_SIZE,
    )
    if layout.footer:
        pdf.draw_text(
            c,
            layout.width - MARGIN,
            MARGIN,
            layout.footer,
            fonts.sans,
            FOOTER_SIZE,
            right=True,
        )
    colors = [_draw_cell(c, cell, fan, options, layout) for cell in fan.cells]
    # Planning stops at unknown parents; outline every remaining position for writing in.
    supplied_slots = {cell.slot for cell in fan.cells}
    for slot in range(1, 2**fan.generations):
        if slot not in supplied_slots:
            _draw_cell(c, FanCell(slot, empty=True), fan, options, layout)
    for cell, color in zip(fan.cells, colors, strict=True):
        c.setFillColorRGB(color, color, color)
        for line in fit_cell(cell, layout, fonts, strings["ellipsis"]) or []:
            _draw_line(c, cell, line, layout, fonts.sans)
        mark = _mark_line(cell, layout, fonts)
        if mark is not None:
            _draw_line(c, cell, mark, layout, fonts.bold)
    for box in layout.legend:
        _draw_legend(c, box, options, fonts)
    c.showPage()
    c.save()
    return buf.getvalue()
